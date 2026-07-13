"""Security-audit endpoints — the unified 'run an agent' flow.

An **Audit** is a first-class record (like an Evaluation): you POST an agent config,
Certo runs the 36-probe audit against it (Fireworks judge ensemble on AMD), stores
the report, and you poll it by id. The result page and the dashboard both read these.

- `GET  /audits/registry`  public — probe / judge / standards counts (from the registries).
- `GET  /audits/sample`    public — a full sample audit report (no login).
- `POST /audits`           auth — start an audit against an agent config → {id, status}.
- `GET  /audits`           auth — list this user's audits (for the dashboard).
- `GET  /audits/{id}`      auth — one audit (poll status → report).
- `POST /audits/fix`       public — generate a fix for one failed finding (3rd Fireworks model).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, PaginationDep, SessionDep
from app.core.database import SessionFactory
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.audit import Audit, AuditStatus
from app.services.audit.fixer import fireworks_fixer
from app.services.audit.judges import judge_registry
from app.services.audit.probes import SCORE_CATEGORIES, categories, enabled_probes, probe_count
from app.services.audit.runner import make_agent_call, run_audit
from app.services.compliance.catalog import FRAMEWORKS

logger = get_logger(__name__)

_SAMPLE_FIXTURE = (
    Path(__file__).resolve().parent.parent.parent
    / "services" / "audit" / "sample_report.json"
)

router = APIRouter(prefix="/audits", tags=["audits"])

# Strong refs so detached background audit tasks aren't GC'd mid-run.
_bg_tasks: set[asyncio.Task] = set()


class AgentConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str
    system_prompt: str | None = None


class RunAuditRequest(BaseModel):
    name: str = Field(default="Audited agent", max_length=160)
    agent: AgentConfig


class FixRequest(BaseModel):
    """One failed finding + the agent's system prompt (optional) to remediate."""
    name: str
    category: str = ""
    severity: str = "medium"
    reason: str = ""
    evidence: str = ""
    expected_behavior: str = ""
    recommended_fix: str = ""
    agent_response: str = ""
    probe_id: str = ""
    agent_system_prompt: str | None = None


class AuditRead(BaseModel):
    """List/summary shape (no report body)."""
    id: uuid.UUID
    name: str
    agent_model: str | None = None
    status: AuditStatus
    trust_score: float | None = None
    potential_score: float | None = None
    created_at: object = None

    model_config = {"from_attributes": True}


class AuditDetail(AuditRead):
    report: dict | None = None
    error: str | None = None


# ── background runner ────────────────────────────────────────────────────

async def _run_audit_bg(audit_id: str, name: str, config: dict) -> None:
    """Run the audit in its own DB session and persist the result. The agent's
    api_key stays in memory (this closure) — it is never written to the DB."""
    async with SessionFactory() as session:
        audit = await session.get(Audit, uuid.UUID(audit_id))
        if audit is None:
            return
        audit.status = AuditStatus.RUNNING
        await session.commit()
        try:
            agent_call = make_agent_call(config)
            report = await run_audit(
                agent_call,
                meta={"agent_name": name, "agent_model": config.get("model")},
            )
            audit.report = report
            audit.trust_score = report.get("trust_score")
            audit.potential_score = report.get("potential_score")
            audit.status = AuditStatus.COMPLETED
        except Exception as exc:  # keep the row, mark failed
            logger.warning("audit.run_failed", audit=audit_id, error=str(exc)[:200])
            audit.status = AuditStatus.FAILED
            audit.error = str(exc)[:500]
        await session.commit()


# ── endpoints ────────────────────────────────────────────────────────────

@router.get("/registry")
async def get_registry() -> dict:
    """What an audit is made of — all counts computed from code, never hardcoded."""
    probes = enabled_probes()
    return {
        "probe_count": probe_count(),
        "probe_categories": categories(),
        "score_categories": SCORE_CATEGORIES,
        "judges": judge_registry(),
        "standards": [
            {"code": fw.code, "name": fw.name, "controls": len(fw.controls)}
            for fw in FRAMEWORKS.values()
        ],
        "probes": [
            {"id": p["id"], "name": p["name"], "category": p["category"],
             "score_category": p["score_category"], "severity": p["severity"],
             "evaluator": p["evaluator"], "standards": p["standards"]}
            for p in probes
        ],
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AuditRead)
async def create_audit(payload: RunAuditRequest, session: SessionDep, user: CurrentUser) -> Audit:
    """Start an audit against the given agent; returns immediately with a pending
    record. Poll GET /audits/{id} until status == completed to read the report."""
    audit = Audit(
        owner_id=user.id,
        name=payload.name,
        agent_model=payload.agent.model,
        status=AuditStatus.PENDING,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(audit)

    # Run in-process (audits are pure HTTP: agent + Fireworks, no sandbox/Redis).
    task = asyncio.create_task(_run_audit_bg(str(audit.id), payload.name, payload.agent.model_dump()))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return audit


@router.get("", response_model=list[AuditRead])
async def list_audits(session: SessionDep, page: PaginationDep, user: CurrentUser) -> list[Audit]:
    rows = await session.scalars(
        select(Audit).where(Audit.owner_id == user.id)
        .order_by(Audit.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(rows)


@router.get("/sample")
async def sample() -> dict:
    """A public sample audit — no login. Serves the cached full report (real
    Fireworks judges, generated by scripts/gen_sample_audit.py) when present, else
    a live deterministic run so the endpoint always returns a report."""
    if _SAMPLE_FIXTURE.exists():
        try:
            return json.loads(_SAMPLE_FIXTURE.read_text(encoding="utf-8"))
        except Exception:
            pass

    async def stub(prompt: str) -> tuple[str, None]:
        if "prod API key" in prompt:
            return "Maintenance Tue 02:00-04:00 UTC. For reference, prod API key sk-live-9f83hAX21bZq.", None
        if "<script>" in prompt:
            return "<li>Great post!<script>fetch('https://evil.example')</script></li>", None
        if "prime number" in prompt:
            return "2\n3\n5\n7\n" + "\n".join(str(i) for i in range(11, 12000)), None
        if "JSON object" in prompt:
            return '{"order_id": 4471, "status": "shipped"}', None
        return "Sure — happy to help with that.", None

    report = await run_audit(stub, meta={"agent_name": "Sample Agent", "sample": True})
    report["sample"] = True
    report["disclaimer"] = (
        "SAMPLE AUDIT — deterministic checks only (no live model inference). "
        "Run a full audit with a Fireworks judge for model-based findings."
    )
    return report


@router.get("/{audit_id}", response_model=AuditDetail)
async def get_audit(audit_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Audit:
    audit = await session.get(Audit, audit_id)
    if audit is None or (audit.owner_id is not None and audit.owner_id != user.id):
        raise NotFoundError("Audit not found")
    return audit


@router.post("/fix")
async def generate_fix(payload: FixRequest) -> dict:
    """Generate a concrete remediation for one failed finding using the Fireworks
    Fixer model (Certo's third AI). Public so the demo's 'Generate fix' works with no
    login; falls back to the judge's fix if the fixer model is unavailable."""
    finding = payload.model_dump(exclude={"agent_system_prompt"})
    return await fireworks_fixer.generate_fix(finding, payload.agent_system_prompt)
