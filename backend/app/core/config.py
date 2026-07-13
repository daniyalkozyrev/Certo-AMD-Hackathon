"""Application settings, loaded from environment / `.env` via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    env: Literal["local", "staging", "production"] = "local"
    debug: bool = True
    api_prefix: str = "/api/v1"
    project_name: str = "Certo"

    # CORS: comma-separated origins allowed to call the API from a browser.
    # e.g. "http://localhost:3000,http://localhost:5173"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://certo:certo@localhost:5432/certo"
    db_echo: bool = False
    # Create tables on startup via SQLAlchemy create_all (instead of Alembic).
    # On managed Postgres (e.g. Railway) this gives a fresh, consistent schema
    # without running migrations — set AUTO_CREATE_TABLES=true there.
    auto_create_tables: bool = False
    # Seed a demo agent + benchmark on first boot so a fresh deploy is usable.
    seed_on_start: bool = False
    # Use a pgvector column for skill embeddings. Off by default so create_all
    # works on a plain managed Postgres (no `vector` extension required); the MVP
    # doesn't run similarity search yet, so JSON storage is fine.
    pgvector_enabled: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Managed Postgres hands out `postgres://` / `postgresql://` URLs, but the
        async engine needs the asyncpg driver. Rewrite the scheme transparently."""
        if v.startswith("postgresql+asyncpg://") or v.startswith("sqlite"):
            return v
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        return v

    # ── Redis / Arq ──────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    # Local dev without Redis: run evaluations in-process instead of via Arq.
    run_worker_inline: bool = False

    # ── E2B sandbox ──────────────────────────────────────────
    e2b_api_key: str | None = None
    mock_sandbox: bool = True

    # ── SWE-bench harness (Linux-only → invoked inside WSL2 on Windows) ──
    # The official harness imports the Unix `resource` module and drives Docker,
    # so the Certo backend (on Windows) shells out to it inside a WSL2 distro
    # where swebench + Docker live. Defaults match the local Ubuntu setup.
    swebench_enabled: bool = False
    swebench_wsl_distro: str = "Ubuntu"
    swebench_python: str = "/opt/swebench-venv/bin/python"
    swebench_workdir: str = "/root/swebench-runs"
    swebench_dataset: str = "SWE-bench/SWE-bench_Lite"
    swebench_max_workers: int = 1
    swebench_timeout: int = 1800  # per-instance test timeout (seconds)

    # ── Judge #1: self-hosted vLLM (OpenAI-compatible) ──
    judge_base_url: str = "http://localhost:8000/v1"
    judge_api_key: str = "EMPTY"
    judge_model: str = "qwen3.6-27b"
    mock_judge: bool = True
    # Qwen/Gemma vLLM are reasoning models that write a long hidden "thinking"
    # section before every answer (slow, token-hungry). Grading is rubric-driven,
    # so we disable it → ~7x faster judging. Sends `chat_template_kwargs:
    # {enable_thinking: false}` via extra_body on every judge call.
    judge_disable_thinking: bool = True
    # Comma-separated fallback base URLs for the vLLM judge. The trycloudflare
    # tunnel URL rotates on every server restart; when a judge call fails on the
    # current URL the client rotates to the next one instead of failing the whole
    # run. Put the freshest known URLs here (oldest last).
    judge_fallback_base_urls: str = ""

    # ── TrustScore blend ─────────────────────────────────────
    # Per-task quality  q = correctness * (trust_beta + (1-trust_beta)*process).
    # Correctness is a HARD GATE: a wrong final answer (c=0) -> 0, no matter how
    # clean the process. trust_beta = the floor a CORRECT-but-messy answer keeps
    # (so luck is penalised but a right answer isn't zeroed). trust_lambda splits
    # step-quality vs the holistic grade inside `process` (where a holistic exists).
    # Both are calibratable against human trust labels — see scripts/calibrate_*.
    trust_beta: float = 0.4
    trust_lambda: float = 0.4

    # ── Fireworks AI (AMD) — the security-audit judge ────────
    # A model served on Fireworks AI (running on AMD infrastructure) evaluates each
    # audit probe against a fixed rubric and returns a structured JSON verdict.
    # OpenAI-compatible endpoint. Leave the key empty to run the audit in demo mode
    # (deterministic checks only). Use a Gemma model here for the Gemma bonus.
    fireworks_api_key: str | None = None
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"
    # Primary + optional secondary judge model. Two models = a real ensemble
    # (consensus score + disagreement). Leave the 2nd empty for a single judge.
    fireworks_model: str = "accounts/fireworks/models/gpt-oss-120b"
    fireworks_model_2: str = ""
    # Third Fireworks model — the remediation engine. Given a failed finding it
    # generates a concrete, applyable fix (the "Generate fix" button). Distinct from
    # the two judges so it's an independent third model.
    fireworks_fixer_model: str = "accounts/fireworks/models/deepseek-v4-pro"

    @property
    def fireworks_enabled(self) -> bool:
        return bool(self.fireworks_api_key)

    @property
    def fireworks_models(self) -> list[str]:
        return [m for m in (self.fireworks_model, self.fireworks_model_2) if m]

    @property
    def fireworks_fixer_enabled(self) -> bool:
        return bool(self.fireworks_api_key and self.fireworks_fixer_model)

    # ── Judge: Anthropic Claude (optional primary, replaces the vLLM judge) ──
    # Set enabled=true to use Claude as the PRIMARY judge instead of the vLLM one.
    # Note: "Sonnet 3.5" is retired (404s) — claude-sonnet-4-6 is the drop-in successor.
    judge_anthropic_enabled: bool = False
    judge_anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("judge_anthropic_api_key", "anthropic_api_key"),
    )
    judge_anthropic_model: str = "claude-sonnet-4-6"

    # ── Judge #2: secondary LLM judge (ensemble) ─────────────
    # Removes single-judge subjectivity by averaging an independent grader.
    # >>> PLUG IN ANOTHER LLM HERE <<<  — set enabled=true and fill in the
    # base_url / api_key / model of any OpenAI-compatible endpoint (OpenAI,
    # Anthropic-compatible gateway, another vLLM, etc.). Disabled by default.
    judge_secondary_enabled: bool = False
    judge_secondary_base_url: str = "https://api.openai.com/v1"
    judge_secondary_api_key: str | None = None
    judge_secondary_model: str = "gpt-4o-mini"

    # ── Agent-under-test default inference ───────────────────
    agent_default_base_url: str = "https://api.openai.com/v1"
    agent_default_api_key: str | None = None
    agent_default_model: str = "gpt-4o-mini"
    # Max steps an agentic/multi-agent run may take inside the sandbox.
    agent_max_steps: int = Field(default=6, ge=1, le=20)
    # Per-request timeout for the agent-under-test endpoint. Bounds a misconfigured
    # or hung endpoint so an evaluation can't stall for the SDK's 600s default.
    agent_request_timeout: int = Field(default=90, ge=5, le=600)

    # ── Scoring ──────────────────────────────────────────────
    reward_pass_threshold: int = Field(default=4, ge=1, le=5)
    # Judge every step of an agent-supplied trajectory (one judge call per span).
    # The cap bounds judge cost on very long runs; spans beyond it still reach
    # the judge inside the holistic trajectory grade, just not individually.
    judge_grade_steps: bool = True
    judge_span_limit: int = Field(default=12, ge=1, le=50)

    # ── Security / Auth ──────────────────────────────────────
    secret_key: str = "change-me-in-production"
    access_token_days: int = 30
    code_ttl_minutes: int = 10

    # Frontend origin (for OAuth redirects back to the app)
    frontend_url: str = "http://localhost:3000"

    # Email delivery for login codes.
    #   "console" — dev: logs the code (and returns it in local mode).
    #   "smtp"    — classic SMTP (blocked outbound on many PaaS incl. Railway).
    #   "brevo"/"sendgrid"/"resend" — HTTP email APIs over :443 (work on Railway).
    email_mode: Literal["console", "smtp", "brevo", "sendgrid", "resend"] = "console"
    email_from: str = "Certo <no-reply@certo.local>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_tls: bool = True
    # HTTP email-API keys (used when email_mode is the matching provider).
    brevo_api_key: str | None = None
    sendgrid_api_key: str | None = None
    resend_api_key: str | None = None

    # Google OAuth (optional — fill in to enable "Continue with Google")
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def expose_dev_code(self) -> bool:
        """In local console mode, return the login code in the API response so it
        can be tested without a real mail server."""
        return self.env == "local" and self.email_mode == "console"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def allow_code_execution(self) -> bool:
        """Whether it is safe to run user-supplied `test_code`.

        Real E2B sandboxes isolate execution, so it's always safe. The local
        mocks run code on the HOST, which is fine for single-user dev (env=local)
        but must NEVER run untrusted code on a shared deployment — so a non-local
        env left in mock mode refuses to execute test_code."""
        return (not self.mock_sandbox) or self.env == "local"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor (import this everywhere)."""
    return Settings()


settings = get_settings()
