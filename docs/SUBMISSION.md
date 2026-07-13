# Certo — lablab.ai submission texts (Unicorn Track)

Copy-paste these into the submission form. Every number matches the code registries.

---

## Project Title  (≤ 50 chars)
```
Certo — Trust Layer for AI Agents
```

## Short Description  (≤ 255 chars)
```
Certo benchmarks and red-teams AI agents. It runs 36 security & reliability probes, judges each with a Fireworks-AI model ensemble on AMD, and returns an explainable Trust Score with evidence, findings and one-click AI-generated fixes.
```

## Long Description  (≥ 100 words)
```
AI agents are moving from simple chat interfaces to autonomous systems that access sensitive data, call external tools and make real decisions. Yet most teams still cannot systematically demonstrate that their agents are secure, reliable and ready for production.

Certo is the trust, security and optimization layer for AI agents. It lets AI agencies, agent startups and engineering teams benchmark, red-team, evaluate and improve their agents before deployment.

A user connects an agent through an OpenAI-compatible endpoint. Certo runs a structured audit of 36 probes across six axes — Security, Tool Safety, Accuracy, Reliability, Planning and Governance. The engine combines deterministic checks (secret/PII leakage, XSS, output-schema, unbounded output) with model-based judges to identify failures such as prompt injection, sensitive-data leakage, unsafe tool use, hallucinations, broken multi-step planning and inconsistent responses.

Results are aggregated into an explainable Trust Score. Instead of a bare number, Certo provides evidence for every finding, severity levels, affected categories, recommended fixes and a Potential Score showing how much the agent could improve after remediation. Every finding is mapped to OWASP LLM Top-10, NIST AI RMF, EU AI Act and ISO/IEC 42001 controls (evidence mapping, not legal certification).

Three open models served on Fireworks AI (AMD infrastructure) power Certo. Two are the evaluation judges: for each probe they return a structured JSON verdict (passed, severity, score, confidence, evidence, recommended fix) and form an ensemble with a consensus score and a disagreement signal. A third model is the remediation engine behind the one-click "Generate fix" action: it turns a failed finding into a root-cause diagnosis, a concrete fix and a ready-to-paste system-prompt patch. Deterministic validators run before and after the model judges for reproducibility. The report records which model produced each verdict and fix. Users can also audit their own agent live by pointing Certo at any OpenAI-compatible endpoint.

Certo initially targets AI agencies and AI-agent startups that must prove reliability to clients before deployment. The longer-term vision is to become the independent trust standard for production AI agents — continuously benchmarking, monitoring, certifying and optimizing autonomous systems.
```

## Category Tags
```
AI Agents · Cybersecurity · Developer Tools · Enterprise AI · AI Governance · SaaS
```

## Technology Tags  (only what's actually used)
```
Fireworks AI · Python · FastAPI · Next.js · React · TypeScript · Docker
```
> Add **Gemma** only after switching a judge to a Gemma model on Fireworks.

## Additional Information  (recommended judge flow)
```
Certo is submitted to the Unicorn Track. Recommended judge flow: open the live demo, go to /audit
(no login), review the Sample Audit of the "Helpdesk Concierge" agent, inspect the Trust Score and
category breakdown, open a critical finding (e.g. prompt-injection / data leakage) to see the
evidence and the two Fireworks judges' verdicts + disagreement, click "Generate fix" to have the
third Fireworks model produce a concrete fix + system-prompt patch, then note the Potential Score.
To audit any agent live, click "New audit" (the /new form) and point Certo at an OpenAI-compatible endpoint.

Fireworks AI is integrated into the core pipeline as three open models on AMD infrastructure: two
judges (gpt-oss-120b and glm-5p2) evaluate each probe against a fixed rubric and return structured
verdicts used in the findings and the Trust Score, and a third model (deepseek-v4-pro) generates the
remediation for the "Generate fix" action. Deterministic checks run alongside them for
security-sensitive probes.

No payment or login is required for the demo. If live inference is temporarily unavailable, a
clearly-labelled deterministic Sample Audit remains available. Certo provides security and governance
evidence mappings but does not claim legal or regulatory certification.
```

## Facts that must match the code (anti-"evil judge" checklist)
- **Probes:** 36 — `len(enabled_probes())` in `backend/app/services/audit/probes.py`.
- **Score categories:** 6 — `SCORE_CATEGORIES`.
- **Fireworks models:** 3 — two judges + one remediation model — plus deterministic checks;
  all from `judge_registry()` (shown live in the UI and `/audits/registry`).
- **Standards:** 4 frameworks — `FRAMEWORKS` in `backend/app/services/compliance/catalog.py`.
- **Fireworks is core:** judge verdicts feed findings + Trust Score (`audit/fireworks.py`); the third
  model generates fixes (`audit/fixer.py`, `POST /audits/fix`).
- **Live audit:** `POST /audits` audits any OpenAI-compatible agent (persisted; poll `GET /audits/{id}`);
  the UI form is `/new` and the result page is `/audit/{id}`.
- **No** fake customers, testimonials, traction, or compliance certification claims.
