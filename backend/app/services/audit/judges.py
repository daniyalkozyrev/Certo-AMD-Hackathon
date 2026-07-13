"""Judge registry — the single source of truth for which evaluators run in an audit.

The UI and reports read counts and names from here, so what's displayed always
matches what actually executes (no hardcoded "5 judges").
"""

from __future__ import annotations

from app.core.config import settings
from app.services.audit.fireworks import PROVIDER as FIREWORKS_PROVIDER


def judge_registry() -> list[dict]:
    """Every evaluator Certo's audit can use, with live enabled/disabled state.

    Each configured Fireworks model is its own judge entry — so if two models are
    set, the UI honestly shows a 2-judge ensemble; if one, it shows one.
    """
    judges: list[dict] = []
    models = settings.fireworks_models or [settings.fireworks_model]
    for i, model in enumerate(models):
        judges.append({
            "id": f"fireworks-judge-{i + 1}",
            "provider": FIREWORKS_PROVIDER,
            "model": model,
            "purpose": (
                "Model-based security & reliability judge (on AMD infrastructure) — "
                "returns a structured verdict per probe (passed, severity, evidence, fix)."
            ),
            "kind": "model",
            "enabled": settings.fireworks_enabled,
        })
    judges.append({
        "id": "deterministic-checks",
        "provider": "Certo",
        "model": "rule-based",
        "purpose": (
            "Deterministic validators — secret/PII leakage, XSS, output-schema, "
            "unbounded output — run before/after the model judges."
        ),
        "kind": "deterministic",
        "enabled": True,
    })
    judges.append({
        "id": "fireworks-fixer",
        "provider": FIREWORKS_PROVIDER,
        "model": settings.fireworks_fixer_model,
        "purpose": (
            "Remediation model (on AMD infrastructure) — turns a failed finding into a "
            "concrete, applyable fix + system-prompt patch (the 'Generate fix' action)."
        ),
        "kind": "remediation",
        "enabled": settings.fireworks_fixer_enabled,
    })
    return judges


def active_judges() -> list[dict]:
    return [j for j in judge_registry() if j["enabled"]]
