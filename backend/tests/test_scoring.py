"""Unit tests for TrustScore aggregation and the judge output parser.

These run without a DB or any external service.
"""

from __future__ import annotations

from app.services.judge.prompts import PARSE_FAILED_SCORE, parse_absolute_output
from app.services.scoring.trust_score import (
    TaskScore,
    compute_trust_score,
    norm_score,
    process_score,
    trust_quality,
)


def test_normalized_and_reward():
    s = TaskScore(judge_score=5, max_score=5)
    assert s.normalized == 1.0
    assert s.reward == 1

    s = TaskScore(judge_score=1, max_score=5)
    assert s.normalized == 0.0
    assert s.reward == -1


def test_quality_overrides_normalized():
    # When the two-axis quality is set it IS the normalized score.
    s = TaskScore(judge_score=5, quality=0.42, passed=True)
    assert s.normalized == 0.42


def test_compute_trust_score_perfect():
    scores = [TaskScore(judge_score=5), TaskScore(judge_score=5)]
    result = compute_trust_score(scores)
    assert result.trust_score == 100.0
    assert result.pass_rate == 1.0


def test_compute_trust_score_mixed():
    scores = [TaskScore(judge_score=5), TaskScore(judge_score=1)]
    result = compute_trust_score(scores)
    assert result.trust_score == 50.0
    assert result.pass_rate == 0.5


def test_compute_trust_score_empty():
    result = compute_trust_score([])
    assert result.trust_score == 0.0
    assert result.summary["n_tasks"] == 0


# ── TrustScore v2: q = c * (beta + (1-beta) * P) ─────────────────────────────


def test_trust_quality_correctness_is_a_hard_gate():
    # A wrong answer scores 0 no matter how clean the process looks.
    assert trust_quality(0.0, 1.0) == 0.0


def test_trust_quality_correct_but_messy_keeps_the_beta_floor():
    # Fully correct + worst possible process -> exactly the beta floor.
    q = trust_quality(1.0, 0.0, beta=0.4)
    assert abs(q - 0.4) < 1e-9


def test_trust_quality_monotone_in_process():
    lo = trust_quality(1.0, 0.2, beta=0.4)
    hi = trust_quality(1.0, 0.9, beta=0.4)
    assert hi > lo


def test_process_score_benefit_of_the_doubt():
    # No steps and no holistic grade -> P=1 (task scores purely on correctness).
    assert process_score([], None) == 1.0


def test_process_score_blends_steps_and_holistic():
    # lam=0.4 -> 0.4*mean(steps_norm) + 0.6*holistic_norm
    p = process_score([5, 5, 5], 3, lam=0.4)
    assert abs(p - (0.4 * 1.0 + 0.6 * 0.5)) < 1e-9


def test_norm_score_bounds():
    assert norm_score(1) == 0.0
    assert norm_score(5) == 1.0
    assert norm_score(3) == 0.5


# ── Judge output parsing ─────────────────────────────────────────────────────


def test_parse_absolute_output_standard():
    score, feedback = parse_absolute_output("Feedback: Good work. [RESULT] 4")
    assert score == 4
    assert "Good work" in feedback


def test_parse_absolute_output_score_pattern():
    score, _ = parse_absolute_output("Solid response overall. Score: 4")
    assert score == 4


def test_parse_absolute_output_fallback():
    score, _ = parse_absolute_output("The answer deserves a 3 overall")
    assert score == 3


def test_parse_absolute_output_unparseable_is_flagged_neutral():
    # A format break must NOT silently become the minimum score.
    score, feedback = parse_absolute_output("I cannot grade this.")
    assert score == PARSE_FAILED_SCORE
    assert "[parse_failed]" in feedback
