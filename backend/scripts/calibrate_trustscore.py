"""Calibrate the TrustScore constants (beta, lambda) against human trust labels.

The per-task TrustScore is  q = c * (beta + (1-beta) * P),  where
P = lambda * mean(step grades) + (1-lambda) * holistic  (see docs/TRUSTSCORE.md).
beta and lambda are currently 0.4 / 0.4 "by design". This script makes them
data-driven: it grid-searches (beta, lambda) to best match a small set of runs
that a human scored for trust (scripts/data/trust_gold.jsonl), and reports the
fit vs. the current defaults.

    cd backend && .venv/Scripts/python -m scripts.calibrate_trustscore

Add rows to the JSONL (label `human_trust` 0-100) to tighten the fit. This turns
"beta=0.4 by taste" into "beta*, lambda* fit to human trust."
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from app.services.scoring.trust_score import process_score, trust_quality

DATA = Path(__file__).parent / "data" / "trust_gold.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _predict(row: dict, beta: float, lam: float) -> float:
    c = float(row["correctness"])
    P = process_score(row.get("step_scores") or [], row.get("holistic"), lam=lam)
    return 100.0 * trust_quality(c, P, beta=beta)


def _mae(rows: list[dict], beta: float, lam: float) -> float:
    return sum(abs(_predict(r, beta, lam) - r["human_trust"]) for r in rows) / len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    args = ap.parse_args()
    rows = _load(Path(args.data))
    print(f"Loaded {len(rows)} human-labelled runs.\n")

    # Grid search beta in [0,0.5], lambda in [0,1].
    betas = [i / 100 for i in range(0, 51, 2)]
    lams = [i / 100 for i in range(0, 101, 5)]
    best = min(
        ((b, lam, _mae(rows, b, lam)) for b in betas for lam in lams), key=lambda t: t[2]
    )
    b_star, l_star, mae_star = best

    def _boot_mae(
        beta: float, lam: float, n_boot: int = 2000, seed: int = 7
    ) -> tuple[float, float]:
        """Percentile-bootstrap 95% CI on the MAE — honesty about the small sample."""
        rng = random.Random(seed)
        vals = []
        for _ in range(n_boot):
            sample = [rows[rng.randrange(len(rows))] for _ in range(len(rows))]
            err = sum(abs(_predict(r, beta, lam) - r["human_trust"]) for r in sample)
            vals.append(err / len(sample))
        vals.sort()
        return vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot)]

    cur_mae = _mae(rows, 0.4, 0.4)
    cur_lo, cur_hi = _boot_mae(0.4, 0.4)
    best_lo, best_hi = _boot_mae(b_star, l_star)
    print("=== Fit to human trust (mean abs error, 0-100 scale) ===")
    print(
        f"  current defaults  beta=0.40 lambda=0.40 -> MAE {cur_mae:5.1f}  "
        f"95%CI [{cur_lo:.1f},{cur_hi:.1f}]"
    )
    print(
        f"  best on grid      beta={b_star:.2f} lambda={l_star:.2f} -> MAE {mae_star:5.1f}  "
        f"95%CI [{best_lo:.1f},{best_hi:.1f}]"
    )
    if cur_lo <= mae_star <= cur_hi:
        print(
            "  note: the CIs overlap -> the defaults are statistically indistinguishable "
            "from the grid optimum on this sample; keep 0.40/0.40 until more runs are labelled."
        )

    print("\n=== Per-run: human vs current vs best ===")
    print(f"{'id':>3} {'human':>6} {'cur(.4/.4)':>11} {'best':>6}  note")
    for r in rows:
        print(f"{r['id']:>3} {r['human_trust']:>6} {_predict(r,0.4,0.4):>11.1f} "
              f"{_predict(r,b_star,l_star):>6.1f}  {r.get('note','')}")

    print(f"\nRecommendation: set trust_beta={b_star:.2f}, trust_lambda={l_star:.2f} in config "
          f"(add more labelled runs first to trust this fit).")


if __name__ == "__main__":
    main()
