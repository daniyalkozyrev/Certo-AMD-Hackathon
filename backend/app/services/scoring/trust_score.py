"""TrustScore aggregation.

MVP formula: TrustScore = 100 * weighted mean of per-task normalized judge
scores. `pass_rate` is reported separately. The structure (weights, named
dimensions) is intentionally extensible so we can add safety / efficiency /
robustness dimensions later without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class TaskScore:
    """Per-task scoring input."""

    judge_score: int  # 1..5
    max_score: int = 5
    passed: bool | None = None  # for grading_type=CODE; None -> derive from threshold
    quality: float | None = None  # precomputed trust quality in [0,1]; overrides normalized

    @property
    def normalized(self) -> float:
        """Map to [0, 1]. Uses the two-axis `quality` when set, else min-max on judge_score."""
        if self.quality is not None:
            return max(0.0, min(1.0, self.quality))
        denom = max(self.max_score - 1, 1)
        return max(0.0, min(1.0, (self.judge_score - 1) / denom))

    @property
    def reward(self) -> int:
        """+1 if the task is considered passed, else -1."""
        if self.passed is not None:
            return 1 if self.passed else -1
        return 1 if self.judge_score >= settings.reward_pass_threshold else -1


def norm_score(x: float, max_score: int = 5) -> float:
    """Min-max a Likert score onto [0,1]: ñ(x) = (x-1)/(max-1)."""
    return max(0.0, min(1.0, (x - 1) / max(max_score - 1, 1)))


def process_score(
    step_scores: list[int],
    holistic: int | None = None,
    *,
    lam: float | None = None,
    max_score: int = 5,
) -> float:
    """Trajectory/process quality P ∈ [0,1].

    Combines the mean per-step grade with an optional holistic grade
    (P = λ·steps + (1-λ)·holistic). Falls back to whichever exists; when NOTHING
    is graded (answer-only, no trace) it returns 1.0 — "benefit of the doubt", so
    the task then scores purely on correctness rather than being penalised for
    having no visible process.
    """
    lam = settings.trust_lambda if lam is None else lam
    step_p = (
        sum(norm_score(s, max_score) for s in step_scores) / len(step_scores)
        if step_scores
        else None
    )
    hol_p = norm_score(holistic, max_score) if holistic is not None else None
    if step_p is not None and hol_p is not None:
        return lam * step_p + (1 - lam) * hol_p
    if step_p is not None:
        return step_p
    if hol_p is not None:
        return hol_p
    return 1.0


def trust_quality(correctness: float, process: float, *, beta: float | None = None) -> float:
    """Per-task TrustScore quality q ∈ [0,1] = c·(β + (1-β)·P).

    Correctness c is a HARD GATE: a wrong answer (c=0) → 0 regardless of how good
    the process P was. β is the floor a fully-correct-but-messy run keeps, so a
    lucky guess is penalised but a right answer is never zeroed by process alone.
    """
    beta = settings.trust_beta if beta is None else beta
    c = max(0.0, min(1.0, correctness))
    p = max(0.0, min(1.0, process))
    return c * (beta + (1 - beta) * p)


@dataclass
class TrustScoreResult:
    trust_score: float  # 0..100
    pass_rate: float  # 0..1
    summary: dict = field(default_factory=dict)


def compute_trust_score(
    scores: list[TaskScore],
    *,
    weights: list[float] | None = None,
) -> TrustScoreResult:
    """Aggregate per-task scores into an overall TrustScore."""
    if not scores:
        return TrustScoreResult(trust_score=0.0, pass_rate=0.0, summary={"n_tasks": 0})

    if weights is None:
        weights = [1.0] * len(scores)
    if len(weights) != len(scores):
        raise ValueError("weights length must match scores length")

    total_w = sum(weights) or 1.0
    weighted = sum(s.normalized * w for s, w in zip(scores, weights, strict=True))
    trust = 100.0 * weighted / total_w

    n_passed = sum(1 for s in scores if s.reward > 0)
    pass_rate = n_passed / len(scores)

    summary = {
        "n_tasks": len(scores),
        "n_passed": n_passed,
        "mean_judge_score": round(
            sum(s.judge_score for s in scores) / len(scores), 3
        ),
        "trust_score": round(trust, 2),
        "pass_rate": round(pass_rate, 3),
    }
    return TrustScoreResult(
        trust_score=round(trust, 2), pass_rate=round(pass_rate, 4), summary=summary
    )
