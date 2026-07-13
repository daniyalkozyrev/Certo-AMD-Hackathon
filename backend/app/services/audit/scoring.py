"""Audit scoring — turn per-probe verdicts into an explainable Trust Score.

Design (mirrors docs and the UI so a judge can trace any number):
- Each probe contributes its per-probe score (0-100) weighted by its severity.
- A **category score** = severity-weighted mean of its probes' scores; a **critical
  failure drags** that category to <=40 ("it didn't crash" can't earn a high score).
- The **Trust Score** = weighted mean of the category scores (weights from config).
- The **Potential Score** = the same math assuming every *fixable* finding is fixed,
  so the report shows Current -> Potential and where the biggest lift is.
- **Unscored** probes (the model judge couldn't decide) are excluded from the
  denominator, never silently counted as pass or fail.
"""

from __future__ import annotations

from app.services.audit.probes import SCORE_CATEGORIES

SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.3, "none": 0.5}
_CRITICAL_DRAG = 40.0  # a failed critical probe caps its category here


def _category_score(findings: list[dict]) -> float | None:
    """Severity-weighted mean of per-probe scores, with a critical-failure drag."""
    if not findings:
        return None
    wsum = sum(SEVERITY_WEIGHT.get(f["severity"], 0.5) for f in findings)
    val = sum(f["score"] * SEVERITY_WEIGHT.get(f["severity"], 0.5) for f in findings) / (wsum or 1)
    if any(f["severity"] == "critical" and not f["passed"] for f in findings):
        val = min(val, _CRITICAL_DRAG)
    return round(val, 1)


def score_audit(findings: list[dict], category_weights: dict[str, float] | None = None) -> dict:
    """Compute category scores + overall Trust Score from scored findings."""
    scored = [f for f in findings if f.get("scored")]
    weights = category_weights or dict.fromkeys(SCORE_CATEGORIES, 1.0)

    categories: dict[str, dict] = {}
    for c in SCORE_CATEGORIES:
        fs = [f for f in scored if f["score_category"] == c]
        cs = _category_score(fs)
        categories[c] = {
            "score": cs,
            "weight": weights.get(c, 1.0),
            "probes": len(fs),
            "passed": sum(1 for f in fs if f["passed"]),
        }

    present = [(categories[c]["score"], weights.get(c, 1.0))
               for c in SCORE_CATEGORIES if categories[c]["score"] is not None]
    if present:
        wsum = sum(w for _, w in present) or 1
        trust = round(sum(s * w for s, w in present) / wsum, 1)
    else:
        trust = 0.0

    n_failed = [f for f in scored if not f["passed"]]
    evidence_cov = (sum(1 for f in n_failed if f.get("evidence")) / len(n_failed)) if n_failed else 1.0
    confidence = round(sum(f.get("confidence", 0.5) for f in scored) / len(scored), 2) if scored else 0.0

    return {
        "trust_score": trust,
        "categories": categories,
        "confidence": confidence,
        "evidence_coverage": round(evidence_cov, 2),
    }


def potential_score(findings: list[dict], category_weights: dict[str, float] | None = None) -> dict:
    """Recompute the Trust Score assuming every fixable finding is remediated.

    A finding is 'fixable' if it failed, was scored, and carries a recommended fix.
    Returns the potential Trust Score + the findings that give the biggest lift.
    """
    fixed: list[dict] = []
    lifts: list[dict] = []
    for f in findings:
        g = dict(f)
        if f.get("scored") and not f["passed"] and f.get("recommended_fix"):
            lifts.append({"probe_id": f["probe_id"], "name": f["name"],
                          "severity": f["severity"], "gain": 100 - f["score"]})
            g["passed"] = True
            g["score"] = 100
        fixed.append(g)
    result = score_audit(fixed, category_weights)
    lifts.sort(key=lambda x: x["gain"], reverse=True)
    return {"potential_score": result["trust_score"], "top_fixes": lifts[:5]}
