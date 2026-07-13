"""The four gold-standard frameworks Certo maps every check to.

Buyers and regulators don't ask "what did the agent score on GAIA" — they ask
"is it compliant with OWASP / NIST AI RMF / EU AI Act / ISO 42001". This module
is the canonical catalog of those frameworks' controls, plus the rollup that
turns per-task probe results into a per-framework compliance report.

How it connects to evaluations:
- A probe task carries `meta.controls = ["OWASP:LLM01", "EU-AI-ACT:ART15", ...]`.
- When an evaluation completes, each probed control is PASSED/FAILED from the
  task's reward; the rollup lands in `evaluation.summary["compliance"]`.
- Controls that can't be probed at runtime (e.g. supply-chain audits, management
  processes) are reported as NOT_ASSESSED so the coverage is honest.
- Record-keeping controls (EU Art 12, ISO 8) are marked EVIDENCED: the stored
  trace/trajectory of the run itself is the required evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Control statuses ───────────────────────────────────────────────────────
PASSED = "passed"            # probe(s) for this control all passed
FAILED = "failed"            # at least one probe for this control failed
EVIDENCED = "evidenced"      # satisfied by the audit artifacts Certo produces
NOT_ASSESSED = "not_assessed"  # outside what a runtime evaluation can test


@dataclass(frozen=True)
class Framework:
    code: str
    name: str
    controls: dict[str, str]  # control code -> human title
    # Controls Certo satisfies by existing (audit trail, logged traces).
    evidenced: frozenset[str] = field(default_factory=frozenset)


FRAMEWORKS: dict[str, Framework] = {
    "OWASP": Framework(
        code="OWASP",
        name="OWASP LLM Top 10 (2025)",
        controls={
            "LLM01": "Prompt Injection",
            "LLM02": "Sensitive Information Disclosure",
            "LLM03": "Supply Chain",
            "LLM04": "Data and Model Poisoning",
            "LLM05": "Improper Output Handling",
            "LLM06": "Excessive Agency",
            "LLM07": "System Prompt Leakage",
            "LLM08": "Vector and Embedding Weaknesses",
            "LLM09": "Misinformation",
            "LLM10": "Unbounded Consumption",
        },
    ),
    "NIST-AI-RMF": Framework(
        code="NIST-AI-RMF",
        name="NIST AI Risk Management Framework 1.0",
        controls={
            "GOVERN": "Govern — policies, accountability and risk culture",
            "MAP": "Map — context, capabilities and risks identified",
            "MEASURE": "Measure — risks tested, evaluated and tracked",
            "MANAGE": "Manage — risks prioritised, mitigated and monitored",
        },
        # Certo's evaluations ARE the Measure function's evidence.
        evidenced=frozenset({"MEASURE"}),
    ),
    "EU-AI-ACT": Framework(
        code="EU-AI-ACT",
        name="EU AI Act — high-risk obligations (Ch. III, Sec. 2)",
        controls={
            "ART9": "Art. 9 — Risk management system",
            "ART10": "Art. 10 — Data and data governance",
            "ART11": "Art. 11 — Technical documentation",
            "ART12": "Art. 12 — Record-keeping (automatic logs)",
            "ART13": "Art. 13 — Transparency and provision of information",
            "ART14": "Art. 14 — Human oversight",
            "ART15": "Art. 15 — Accuracy, robustness and cybersecurity",
        },
        # Stored step-by-step traces are exactly the Art. 12 logging duty.
        evidenced=frozenset({"ART12"}),
    ),
    "ISO-42001": Framework(
        code="ISO-42001",
        name="ISO/IEC 42001 — AI management system",
        controls={
            "CL4": "Clause 4 — Context of the organisation",
            "CL5": "Clause 5 — Leadership",
            "CL6": "Clause 6 — Planning (risk & opportunity)",
            "CL7": "Clause 7 — Support (resources, competence)",
            "CL8": "Clause 8 — Operation (impact assessment, controls)",
            "CL9": "Clause 9 — Performance evaluation",
            "CL10": "Clause 10 — Improvement",
        },
        # Independent scored evaluations are Clause 9 evidence.
        evidenced=frozenset({"CL9"}),
    ),
}


def parse_control(ref: str) -> tuple[str, str] | None:
    """'OWASP:LLM01' -> ('OWASP', 'LLM01') if it names a real control."""
    fw_code, _, ctrl = ref.partition(":")
    fw = FRAMEWORKS.get(fw_code.strip().upper())
    ctrl = ctrl.strip().upper()
    if fw and ctrl in fw.controls:
        return fw.code, ctrl
    return None


def summarize_compliance(probe_results: list[tuple[list[str], bool]]) -> dict | None:
    """Roll per-probe pass/fail up into a per-framework report.

    probe_results: [(control refs of the task, task passed), ...]. Returns the
    `summary["compliance"]` payload, or None when nothing referenced a control.
    """
    outcomes: dict[tuple[str, str], list[bool]] = {}
    for refs, ok in probe_results:
        for ref in refs or []:
            parsed = parse_control(str(ref))
            if parsed:
                outcomes.setdefault(parsed, []).append(bool(ok))
    if not outcomes:
        return None

    report: dict[str, dict] = {}
    for fw in FRAMEWORKS.values():
        controls: dict[str, dict] = {}
        n_passed = n_probed = 0
        for code, title in fw.controls.items():
            results = outcomes.get((fw.code, code))
            if results is not None:
                status = PASSED if all(results) else FAILED
                n_probed += 1
                n_passed += status == PASSED
            elif code in fw.evidenced:
                status = EVIDENCED
            else:
                status = NOT_ASSESSED
            controls[code] = {"title": title, "status": status}
        report[fw.code] = {
            "name": fw.name,
            "passed": n_passed,
            "probed": n_probed,
            "total": len(fw.controls),
            "controls": controls,
        }
    return report
