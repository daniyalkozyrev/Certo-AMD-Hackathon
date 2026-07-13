# Certo API — contract for the frontend

Base URL (local): `http://localhost:8000`
All resource endpoints are under the prefix **`/api/v1`**.
Interactive docs / live schema: `http://localhost:8000/docs` and `/openapi.json`.

CORS is enabled for origins in `CORS_ORIGINS` (default `http://localhost:3000`,
`http://localhost:5173`). Add your frontend's dev origin there.

## Endpoints

### Health
`GET /health` → `{ "status": "ok", "env": "local" }`

### Agents
- `POST /api/v1/agents` — create an agent
  ```json
  {
    "name": "My Agent",
    "description": "optional",
    "agent_type": "llm_endpoint",
    "config": { "base_url": null, "api_key": null, "model": null, "system_prompt": null }
  }
  ```
  → `201` `AgentRead`
- `GET /api/v1/agents?limit=50&offset=0` → `Page<AgentRead>`
- `GET /api/v1/agents/{agent_id}` → `AgentRead`

### Benchmarks
- `POST /api/v1/benchmarks` — create a benchmark with tasks
  ```json
  {
    "name": "My Benchmark",
    "description": "optional",
    "tasks": [
      {
        "prompt": "Write a program that prints 5.",
        "rubric": "Score 1..5 rubric text",
        "reference_answer": "5",
        "grading_type": "judge",        // "judge" | "code"
        "test_code": null,                // used when grading_type = "code"
        "max_score": 5
      }
    ]
  }
  ```
  → `201` `BenchmarkRead` (includes `tasks[]`)
- `GET /api/v1/benchmarks` → `Page<BenchmarkRead>`
- `GET /api/v1/benchmarks/{benchmark_id}` → `BenchmarkRead`

### Evaluations (the core flow)
- `POST /api/v1/evaluations` — start a run (async)
  ```json
  { "agent_id": "<uuid>", "benchmark_id": "<uuid>" }
  ```
  → `202` `EvaluationRead` with `status: "pending"`
- `GET /api/v1/evaluations/{evaluation_id}` → `EvaluationDetail`
  Poll until `status` is `completed` (or `failed`), then read `trust_score`,
  `pass_rate`, `summary`, and `results[]`.
- `GET /api/v1/evaluations` → `Page<EvaluationRead>`

### Audits (security & reliability audit — the flagship flow)
- `GET /api/v1/audits/registry` — **public.** What an audit is made of, all counts read
  from code: `probe_count`, `probe_categories`, `score_categories`, `judges` (the Fireworks
  models + deterministic checks), `standards`, and the full `probes[]` list.
- `GET /api/v1/audits/sample` — **public, no login.** A complete sample audit report
  (real Fireworks judges) of a demo "Helpdesk Concierge" agent, clearly labelled `sample: true`.
- `POST /api/v1/audits` — start an audit against an agent (auth required). Runs in the background.
  ```json
  { "name": "My agent",
    "agent": { "base_url": "...", "api_key": "...", "model": "...", "system_prompt": "..." } }
  ```
  → `202` `{ id, status: "pending" }`. Poll `GET /api/v1/audits/{id}` until `status == "completed"`.
- `GET /api/v1/audits` — list your audits (dashboard).
- `GET /api/v1/audits/{id}` — one audit; when completed, `report` holds `trust_score`,
  `potential_score`, `top_fixes[]`, `categories`, `findings[]` (each with `evidence`,
  `recommended_fix`, `severity`, `votes`, `standards`), `judges`, `standards`, `probe_count`.
- `POST /api/v1/audits/fix` — generate a concrete fix for one failed finding (public).

## Key response shapes

```ts
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type EvaluationStatus = "pending" | "running" | "completed" | "failed";

type EvaluationDetail = {
  id: string;
  agent_id: string;
  benchmark_id: string;
  status: EvaluationStatus;
  trust_score: number | null;   // 0..100
  pass_rate: number | null;     // 0..1
  summary: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  results: TaskResult[];
};

type JudgeVote = { judge: string; score: number; feedback: string };

type TaskResult = {
  id: string;
  task_id: string;
  agent_output: string | null;
  sandbox_stdout: string | null;
  sandbox_stderr: string | null;
  sandbox_exit_code: number | null;
  judge_score: number | null;          // ensemble consensus, 1..5
  judge_feedback: string | null;
  judge_votes: JudgeVote[] | null;     // per-judge ensemble votes
  disagreement: "Low" | "Medium" | "High" | null;
  normalized_score: number | null;     // 0..1
  reward: number | null;               // +1 / -1
  created_at: string;
};
```

Errors use: `{ "error": { "code": "not_found", "message": "..." } }`.

## Minimal client example

```js
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function startEvaluation(agentId, benchmarkId) {
  const res = await fetch(`${API}/api/v1/evaluations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, benchmark_id: benchmarkId }),
  });
  return res.json(); // { id, status: "pending", ... }
}

async function pollEvaluation(id) {
  while (true) {
    const r = await fetch(`${API}/api/v1/evaluations/${id}`).then((x) => x.json());
    if (r.status === "completed" || r.status === "failed") return r;
    await new Promise((s) => setTimeout(s, 1500));
  }
}
```
