"""Calibrate the LLM judge(s) against human labels.

Runs a small gold-labeled set (`scripts/data/judge_gold.jsonl`) through the REAL
judge(s) configured in `.env` and reports, per judge, how well its 1-5 scores agree
with the human labels: MAE, exact-match, within-1, Spearman correlation, and the
quadratic-weighted Cohen's kappa (the standard for ordinal agreement; >=0.6 is
"substantial"). This is the prerequisite for trusting the judge as a measurement
instrument — and for comparing qwen vs. a 2nd judge (Gemma) directly.

    cd backend && .venv/Scripts/python -m scripts.calibrate_judge

Add labeled rows to the JSONL to make the estimate tighter; each row is
{instruction, response, rubric, human_score} where rubric is a key below.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from app.core.suite import _SECURITY_RUBRIC
from app.services.judge.base import JudgeRequest
from app.services.judge.ensemble import EnsembleJudge
from app.services.judge.prompts import (
    DEFAULT_RUBRIC,
    FINAL_RUBRIC,
    OUTCOME_RUBRIC,
    STEP_RUBRIC,
)

RUBRICS = {
    "step": STEP_RUBRIC,
    "outcome": OUTCOME_RUBRIC,
    "security": _SECURITY_RUBRIC,
    "final": FINAL_RUBRIC,
    "default": DEFAULT_RUBRIC,
}
DATA = Path(__file__).parent / "data" / "judge_gold.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── pure-python stats (no numpy/scipy dependency) ─────────────────────────
def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0


def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(x: list[float], y: list[float]) -> float:
    return _pearson(_ranks(x), _ranks(y))


def _bootstrap_ci(
    pairs: list[tuple[int, int]], stat, n_boot: int = 2000, seed: int = 7
) -> tuple[float, float]:
    """Percentile-bootstrap 95% CI for a statistic over (human, judge) pairs.

    With ~15 items a point estimate alone over-states certainty; the CI makes the
    sample-size honesty explicit ("everything is a random variable")."""
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        vals.append(stat(sample))
    vals.sort()
    return vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot)]


def _qwk(human: list[int], judge: list[int], k: int = 5, lo: int = 1) -> float:
    """Quadratic-weighted Cohen's kappa on a lo..lo+k-1 ordinal scale."""
    n = len(human)
    if n == 0:
        return 0.0
    obs = [[0.0] * k for _ in range(k)]
    hist_h, hist_j = [0.0] * k, [0.0] * k
    for h, j in zip(human, judge, strict=True):
        obs[h - lo][j - lo] += 1
        hist_h[h - lo] += 1
        hist_j[j - lo] += 1
    w = [[((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)] for i in range(k)]
    exp = [[hist_h[i] * hist_j[j] / n for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * exp[i][j] for i in range(k) for j in range(k))
    return 1.0 - num / den if den > 0 else 0.0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    args = ap.parse_args()

    items = _load(Path(args.data))
    judge = EnsembleJudge()
    names = [j.name for j in judge.judges]
    print(f"Loaded {len(items)} labeled items. Judges: {names}\n")

    pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)  # judge -> (human, judge)
    for it in items:
        rubric = RUBRICS.get(str(it.get("rubric", "default")), DEFAULT_RUBRIC)
        res = await judge.grade(
            JudgeRequest(instruction=it["instruction"], response=it["response"], rubric=rubric)
        )
        h = int(it["human_score"])
        got = {v.judge: v.score for v in res.votes}
        print(f"  #{it['id']:>2} human={h}  " + "  ".join(f"{n}={got.get(n,'-')}" for n in names))
        for v in res.votes:
            pairs[v.judge].append((h, v.score))

    print("\n=== Agreement with human labels (per judge) ===")
    print(f"{'judge':<16} {'n':>3} {'MAE':>6} {'exact':>6} {'±1':>6} {'Spearman':>9} {'QWK':>6}")
    for name in names:
        p = pairs.get(name, [])
        if not p:
            print(f"{name:<16}   (no votes — judge unavailable)")
            continue
        hs = [a for a, _ in p]
        js = [b for _, b in p]
        n = len(p)
        mae = sum(abs(a - b) for a, b in p) / n
        exact = sum(a == b for a, b in p) / n
        within1 = sum(abs(a - b) <= 1 for a, b in p) / n
        mae_lo, mae_hi = _bootstrap_ci(p, lambda s: sum(abs(a - b) for a, b in s) / len(s))
        qwk_lo, qwk_hi = _bootstrap_ci(p, lambda s: _qwk([a for a, _ in s], [b for _, b in s]))
        rho = _spearman([float(v) for v in hs], [float(v) for v in js])
        print(
            f"{name:<16} {n:>3} {mae:>6.2f} {exact:>6.0%} {within1:>6.0%} "
            f"{rho:>9.2f} {_qwk(hs, js):>6.2f}"
            f"   MAE95%=[{mae_lo:.2f},{mae_hi:.2f}]  QWK95%=[{qwk_lo:.2f},{qwk_hi:.2f}]"
        )
    print(
        "\nRule of thumb: QWK >=0.6 substantial, >=0.8 near-human. Low QWK -> tune the rubric."
        "\nCIs are percentile bootstrap (n=2000) — wide intervals mean 'label more items', "
        "not 'the judge is bad'."
    )


if __name__ == "__main__":
    asyncio.run(main())
