"""Ensemble judge tests (run offline in mock mode, no external services)."""

from __future__ import annotations

import asyncio

from app.services.judge.base import JudgeRequest
from app.services.judge.ensemble import EnsembleJudge, _disagreement_level
from app.services.judge.secondary import SecondaryLLMJudge
from app.services.judge.vllm_judge import VLLMJudge


def test_disagreement_levels():
    assert _disagreement_level(0) == "Low"
    assert _disagreement_level(1) == "Low"
    assert _disagreement_level(2) == "Medium"
    assert _disagreement_level(4) == "High"


def test_ensemble_two_judges_consensus():
    judges = [VLLMJudge(), SecondaryLLMJudge()]
    judge = EnsembleJudge(judges=judges)
    req = JudgeRequest(
        instruction="Print the sum of 2 and 3.",
        response="5",
        rubric="Score 5 if it outputs 5.",
        reference_answer="5",
    )
    result = asyncio.run(judge.grade(req))

    assert len(result.votes) == 2
    assert 1 <= result.score <= 5
    assert result.disagreement in {"Low", "Medium", "High"}
    # combined feedback is labeled with each judge's name
    assert judges[0].name in result.feedback


def test_ensemble_single_judge_default():
    judge = EnsembleJudge(judges=[VLLMJudge()])
    req = JudgeRequest(instruction="x", response="hello world output", rubric="")
    result = asyncio.run(judge.grade(req))
    assert len(result.votes) == 1
    assert result.disagreement == "Low"
