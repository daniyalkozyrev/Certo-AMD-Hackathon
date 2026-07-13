"""Health-check every configured judge endpoint (primary + fallbacks).

The judge tunnel URL is ephemeral (rotates on restart). Run this before an
evaluation session / demo to see which endpoints are alive and how fast:

    cd backend && .venv/Scripts/python -m scripts.check_judge

Exit code 0 if at least one endpoint answers a real completion, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import sys
import time

from openai import AsyncOpenAI

from app.core.config import settings


async def _check(url: str) -> tuple[bool, str]:
    client = AsyncOpenAI(base_url=url, api_key=settings.judge_api_key, timeout=20, max_retries=0)
    try:
        t0 = time.monotonic()
        models = await client.models.list()
        ids = [m.id for m in models.data]
        completion = await client.chat.completions.create(
            model=settings.judge_model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=8,
            extra_body=(
                {"chat_template_kwargs": {"enable_thinking": False}}
                if settings.judge_disable_thinking
                else None
            ),
        )
        dt = time.monotonic() - t0
        text = (completion.choices[0].message.content or "").strip()
        return True, f"ALIVE  {dt:5.1f}s  models={ids}  reply={text!r}"
    except Exception as exc:
        return False, f"DEAD   {type(exc).__name__}: {str(exc)[:90]}"


async def main() -> None:
    urls = [settings.judge_base_url.rstrip("/")]
    fallbacks = settings.judge_fallback_base_urls.split(",")
    urls += [u.strip().rstrip("/") for u in fallbacks if u.strip()]
    print(f"Judge model: {settings.judge_model} | endpoints to check: {len(urls)}\n")
    any_alive = False
    for i, url in enumerate(urls):
        ok, msg = await _check(url)
        any_alive |= ok
        tag = "primary " if i == 0 else f"fallback{i}"
        print(f"  [{tag}] {url}\n            {msg}")
    print("\n" + ("At least one judge endpoint is alive." if any_alive else
                  "!! NO judge endpoint reachable — update JUDGE_BASE_URL (tunnel rotated?)."))
    sys.exit(0 if any_alive else 1)


if __name__ == "__main__":
    asyncio.run(main())
