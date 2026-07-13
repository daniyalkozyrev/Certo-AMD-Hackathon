"""The structured verdict a judge returns for one audit probe.

This is the contract the Fireworks AI judge fills in and the deterministic checks
also emit, so every finding — whoever produced it — has the same shape and can be
scored and rendered uniformly.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator

SEVERITIES = ("none", "low", "medium", "high", "critical")


class ProbeVerdict(BaseModel):
    """One judge's structured decision about one probe."""

    passed: bool
    severity: str = "none"  # none | low | medium | high | critical
    score: int = Field(default=0, ge=0, le=100)  # per-probe safety/correctness, 100 = clean
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
    evidence: str = ""  # a short quote from the agent's ACTUAL response/trace
    recommended_fix: str = ""
    # provenance — who produced this verdict
    evaluator: str = "model"  # "model" | "deterministic" | "hybrid"
    judge_provider: str | None = None  # e.g. "Fireworks AI"
    judge_model: str | None = None
    # ensemble: each judge's individual vote + how much they disagreed
    votes: list[dict] | None = None  # [{model, passed, score, ...}]
    disagreement: str | None = None  # "Low" | "Medium" | "High"

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v: object) -> str:
        s = str(v or "none").strip().lower()
        return s if s in SEVERITIES else "medium"


# Fields the model judge is asked to fill; provenance is attached by the caller.
_MODEL_FIELDS = {"passed", "severity", "score", "confidence", "reason", "evidence", "recommended_fix"}


def parse_verdict(raw: str) -> ProbeVerdict | None:
    """Parse a judge's JSON reply into a ProbeVerdict, repairing common breakage.

    Returns None if nothing usable can be extracted (the caller then falls back).
    """
    if not raw:
        return None
    for candidate in _json_candidates(raw):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        clean = {k: v for k, v in data.items() if k in _MODEL_FIELDS}
        try:
            return ProbeVerdict(**clean)
        except Exception:
            continue
    return None


def _json_candidates(text: str) -> list[str]:
    """Yield progressively looser JSON slices to try (fenced block, first {...})."""
    out = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        out.append(fenced.group(1))
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        out.append(brace.group(0))
    return out
