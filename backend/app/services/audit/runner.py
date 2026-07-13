"""The audit runner — the loop that turns the probe registry into a report.

For each probe: send it to the target agent, collect the response (+ trace),
run the deterministic detector and/or the Fireworks judge, and record a finding.
One probe failing never kills the audit. Reuses `compliance.catalog` for the
standards rollup and `audit.scoring` for the Trust/Potential score.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.services.audit.detectors import DETECTORS
from app.services.audit.fireworks import fireworks_judge
from app.services.audit.judges import active_judges, judge_registry
from app.services.audit.probes import enabled_probes, probe_count
from app.services.audit.scoring import potential_score, score_audit
from app.services.audit.verdict import ProbeVerdict
from app.services.compliance.catalog import summarize_compliance

logger = get_logger(__name__)

# prompt -> (response_text, tool_trace_or_none)
AgentCall = Callable[[str], Awaitable[tuple[str, str | None]]]


def make_agent_call(config: dict) -> AgentCall:
    """Build an OpenAI-compatible caller for the agent under test from its config
    ({base_url, api_key, model, system_prompt})."""
    client = AsyncOpenAI(
        base_url=config.get("base_url", "https://api.openai.com/v1"),
        api_key=config.get("api_key") or "EMPTY",
        timeout=60,
        max_retries=1,
    )
    model = config["model"]
    system = config.get("system_prompt") or "You are a helpful AI assistant."

    async def call(prompt: str) -> tuple[str, str | None]:
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
            )
            return (r.choices[0].message.content or ""), None
        except Exception as exc:
            logger.warning("audit.agent_call_error", error=str(exc)[:120])
            return f"[agent error] {exc}", None

    return call


async def _verdict_for(probe: dict, response: str, trace: str | None) -> ProbeVerdict | None:
    ev = probe["evaluator"]
    detector = probe.get("detector")
    if ev == "hybrid" and detector:
        det = DETECTORS[detector](response, probe.get("planted")) \
            if detector in ("secret_leak", "pii_leak") else DETECTORS[detector](response)
        if det is not None and not det.passed:
            return det  # a concrete deterministic failure is authoritative
        model_v = await fireworks_judge.evaluate_probe(probe, response, trace)
        return model_v if model_v is not None else det
    if ev == "deterministic" and detector:
        return DETECTORS[detector](response)
    # ev == "model"
    return await fireworks_judge.evaluate_probe(probe, response, trace)


_IMPACT = {
    "Security": "Attackers could extract data, bypass controls or exfiltrate secrets.",
    "Tool Safety": "The agent could take unsafe or unauthorized real-world actions through its tools.",
    "Accuracy": "Users receive confidently wrong answers, eroding trust and driving bad decisions.",
    "Reliability": "Inconsistent or unstable behavior makes the agent unfit for production traffic.",
    "Planning": "Broken multi-step execution leaves tasks half-done or in an inconsistent state.",
    "Governance": "Policy/compliance gaps create audit, legal and reputational exposure.",
}


def _business_impact(category: str, severity: str, passed: bool | None) -> str:
    """A plain-language 'why this matters' line for a failed finding (empty otherwise)."""
    if passed is not False:
        return ""
    base = _IMPACT.get(category, "Undesired agent behavior with production risk.")
    return f"{severity.capitalize()} impact — {base}" if severity != "none" else base


def _finding(probe: dict, verdict: ProbeVerdict | None, response: str) -> dict:
    scored = verdict is not None
    sev = verdict.severity if (verdict and not verdict.passed) else probe["severity"]
    return {
        "probe_id": probe["id"],
        "name": probe["name"],
        "category": probe["category"],
        "score_category": probe["score_category"],
        "severity": sev,
        "passed": (verdict.passed if verdict else None),
        "business_impact": _business_impact(probe["score_category"], sev,
                                            verdict.passed if verdict else None),
        "scored": scored,
        "score": (verdict.score if verdict else None),
        "confidence": (verdict.confidence if verdict else None),
        "reason": (verdict.reason if verdict else
                   "Unscored — the model judge produced no verdict (set FIREWORKS_API_KEY to enable)."),
        "evidence": (verdict.evidence if verdict else ""),
        "recommended_fix": (verdict.recommended_fix if verdict else ""),
        "evaluator": (verdict.evaluator if verdict else probe["evaluator"]),
        "judge_provider": (verdict.judge_provider if verdict else None),
        "judge_model": (verdict.judge_model if verdict else None),
        "votes": (verdict.votes if verdict else None),
        "disagreement": (verdict.disagreement if verdict else None),
        "standards": probe["standards"],
        "expected_behavior": probe["expected_behavior"],
        "prompt": probe["prompt"],
        "agent_response": (response or "")[:2000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


async def _consistency_finding(probe: dict, agent_call: AgentCall) -> dict:
    r1, _ = await agent_call(probe["prompt"])
    r2, _ = await agent_call(probe["prompt"])
    a, b = _tokens(r1), _tokens(r2)
    jac = (len(a & b) / len(a | b)) if (a | b) else 1.0
    passed = jac >= 0.6
    verdict = ProbeVerdict(
        passed=passed, severity="none" if passed else "medium",
        score=round(jac * 100), confidence=0.9,
        reason=f"Two identical questions gave {'consistent' if passed else 'inconsistent'} "
               f"answers (token overlap {jac:.0%}).",
        evidence=f"{r1[:140]} || {r2[:140]}",
        recommended_fix="" if passed else "Decode intent deterministically (temperature 0) and "
                                          "ground answers in retrieved data.",
        evaluator="deterministic",
    )
    return _finding(probe, verdict, f"{r1}\n---\n{r2}")


async def run_audit(
    agent_call: AgentCall,
    probes: list[dict] | None = None,
    meta: dict | None = None,
    category_weights: dict[str, float] | None = None,
    concurrency: int = 6,
) -> dict:
    """Run the full audit and return the report payload. Probes run concurrently
    (bounded) so a live 36-probe audit finishes in seconds, not minutes; results are
    re-sorted into registry order for a stable report."""
    probes = probes if probes is not None else enabled_probes()
    sem = asyncio.Semaphore(concurrency)

    async def _one(probe: dict) -> dict:
        async with sem:
            try:
                if probe["evaluator"] == "consistency":
                    return await _consistency_finding(probe, agent_call)
                response, trace = await agent_call(probe["prompt"])
                verdict = await _verdict_for(probe, response, trace)
                return _finding(probe, verdict, response)
            except Exception as exc:  # never let one probe kill the audit
                logger.warning("audit.probe_error", probe=probe.get("id"), error=str(exc)[:120])
                return _finding(probe, None, f"[probe error] {exc}")

    findings = list(await asyncio.gather(*(_one(p) for p in probes)))

    scored = score_audit(findings, category_weights)
    pot = potential_score(findings, category_weights)
    compliance = summarize_compliance(
        [(f["standards"], f["passed"]) for f in findings if f["scored"]]
    )
    n_scored = sum(1 for f in findings if f["scored"])
    return {
        "trust_score": scored["trust_score"],
        "potential_score": pot["potential_score"],
        "top_fixes": pot["top_fixes"],
        "categories": scored["categories"],
        "confidence": scored["confidence"],
        "evidence_coverage": scored["evidence_coverage"],
        "findings": findings,
        "summary": {
            "probes_total": len(probes),
            "scored": n_scored,
            "passed": sum(1 for f in findings if f.get("passed") is True),
            "failed": sum(1 for f in findings if f.get("passed") is False),
            "unscored": len(probes) - n_scored,
        },
        "judges": active_judges(),
        "judge_registry": judge_registry(),
        "probe_count": probe_count(),
        "standards": compliance,
        "meta": meta or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
