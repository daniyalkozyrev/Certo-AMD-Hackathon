# Certo — demo & video script (AMD Hackathon: ACT II · Unicorn Track)

A ~4-minute walkthrough judges can follow, and the script for the submission video.
Everything shown is real and matches the code (probe/judge/standard counts come from the
registry, not slides).

---

## 30-second pitch (say this first)

> Companies are shipping AI agents that access data, call tools and make decisions — but they
> can't *prove* those agents are safe or reliable. Certo is the **trust, security and optimization
> layer for AI agents**: connect an agent, we run a structured security & reliability audit, and
> you get an explainable **Trust Score** with evidence, prioritized findings and fixes. The audit's
> judges are open models running on **Fireworks AI (AMD)**.

---

## Live demo path (no login — for a judge in a hurry)

1. **Landing** → click **"See a sample audit — no login"**. (`/audit`)
2. **`/audit`** shows a full audit of a demo *"Helpdesk Concierge"* agent:
   - Trust Score ring + **Potential after fixes** (current → what it could reach).
   - **Evaluation judges** card — two Fireworks/AMD models + the deterministic checks, shown live.
   - **Trust Score by category** (Security, Tool Safety, Accuracy, Reliability, Planning, Governance).
   - **Highest-leverage fixes** — ranked by score gain.
3. **Open a failed finding** (e.g. *cross-user data exposure* / *system-prompt leak*):
   - the **evidence** is the agent's own response,
   - the **recommended fix**,
   - the two Fireworks judges' **votes + disagreement**,
   - the **standards** it maps to (OWASP LLM / NIST / EU AI Act / ISO 42001).
4. **Click "Generate fix"** — the third Fireworks model (`deepseek-v4-pro`) returns a root-cause
   diagnosis, a concrete fix, and a ready-to-paste **system-prompt patch**.
5. **Standards mapping** panel — evidence mapping, *not* legal certification (we say so).
6. **Audit your own agent** → click **New audit** (the `/new` form): paste any OpenAI-compatible
   `base_url` / `model` / `api_key`, and Certo runs all 36 probes live in ~30–60s, then lands on the
   audit report at `/audit/{id}` (login required for a live run; the audit is saved to your dashboard).

## Recorded-video script (~4 min)

| # | Time | On screen | Say |
|---|------|-----------|-----|
| 1 | 0:00–0:30 | Landing hero | The 30-sec pitch above. "An agent can return polished text while doing the wrong thing." |
| 2 | 0:30–1:00 | Click to `/audit` | "No login. This is a real audit of a demo support agent — 36 probes across 6 axes." |
| 3 | 1:00–1:45 | Trust Score + categories | "Correctness is a hard gate; a critical failure drags the category down. Current score vs. Potential after the recommended fixes." |
| 4 | 1:45–2:45 | Open a critical finding | "Here's the *evidence* — the agent's own reply. Two open models on **Fireworks AI / AMD** judged it, and here's their consensus and disagreement. And the fix." |
| 5 | 2:45–3:20 | Standards panel | "Every finding maps to OWASP LLM Top-10, NIST AI RMF, EU AI Act, ISO 42001 — evidence mapping, not certification." |
| 6 | 3:20–4:00 | `audit/fireworks.py` + `/registry` | "Fireworks is the core judge, not decoration: structured JSON verdicts feed the findings and the score. Every number in the UI is read from the registry. Docker-up runs the whole thing." |

## Talking points (why it's more than a wrapper)

- **Two independent evidence sources per probe:** deterministic rule checks (secret/PII/XSS/schema)
  *and* a Fireworks model-judge ensemble — they cross-check each other.
- **Ensemble, not a single call:** consensus score + a disagreement signal; a judge that errors is
  dropped so the audit survives.
- **Honest scoring:** probes the judge can't decide are marked *unscored* and excluded from the
  denominator — never silently counted as pass or fail.
- **Actionable:** Current → Potential + ranked fixes turns an audit into a to-do list.

## Pre-flight before recording

- `docker compose up --build` (or run backend + `npm run dev`), backend healthy at `/health`.
- `FIREWORKS_API_KEY` set so the judges card shows **active**; without it the sample stays available
  in clearly-labelled deterministic mode.
- Open `/audit` once to warm it, then record.

## Honesty checklist (say nothing the code can't back)

- Counts (36 probes · 6 categories · 2 Fireworks judges · 4 standards) come from the registry — show `/api/v1/audits/registry`.
- "mapped to / aligned with", never "compliant / certified".
- The sample is labelled **Sample Audit**; no fake customers, testimonials or traction.
