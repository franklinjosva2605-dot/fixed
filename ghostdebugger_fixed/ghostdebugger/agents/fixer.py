"""
GhostDebugger — Agent 4: Fixer

Generates a verified patch:
  1. LLM produces fixed code based on root cause
  2. Sandbox re-runs the fixed code
  3. If still failing → retry once with more context
  4. Reports whether fix is verified or best-effort
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from agents.reproducer import ReproducerResult
from agents.router import RouterResult
from agents.tracer import TracerResult
from core.llm_client import LLMClient, SessionTokenTracker
from core.sandbox import run_code

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


@dataclass
class FixerResult:
    fixed_code: str
    verified: bool
    verification_output: str
    changes_made: list[str]
    token_count: int
    attempts: int


_SYSTEM = """\
You are a senior Python engineer. Your job is to fix buggy code.
Apply the minimal change necessary to fix the root cause identified.
Do NOT rewrite the entire program. Preserve the original structure.
Respond ONLY with valid JSON.
"""

_USER_TEMPLATE = """\
Fix this Python code based on the root cause analysis below.

## Original Code
```python
{code}
```

## Root Cause
{root_cause}

## Faulty Lines
{faulty_lines}

## Error
{error_summary}

Return JSON with exactly these fields:
{{
  "fixed_code": "the complete corrected Python code",
  "changes_made": ["list of specific changes you made, one per item"]
}}

Rules:
- Return the COMPLETE fixed file, not just the changed lines
- Make ONLY changes necessary to fix the root cause
- Preserve all variable names, structure, and comments
- Do not add unnecessary imports or complexity
"""


class FixerAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def fix(
        self,
        code: str,
        tracer: TracerResult,
        reproducer: ReproducerResult,
        router: RouterResult,
        tracker: SessionTokenTracker | None = None,
    ) -> FixerResult:
        total_tokens = 0
        attempts = 0
        last_raw = ""

        for attempt in range(1, MAX_RETRIES + 1):
            attempts = attempt
            prompt = _USER_TEMPLATE.format(
                code=code,
                root_cause=tracer.root_cause,
                faulty_lines=tracer.faulty_lines or "See root cause above",
                error_summary=reproducer.summary if reproducer.reproduced else "Logic error — no traceback",
            )

            raw, usage = self._client.chat(
                router.model_key,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.05,
                tracker=tracker,
                json_mode=True,
            )
            total_tokens += usage.total_tokens
            last_raw = raw

            parsed = self._parse(raw)
            fixed_code = parsed.get("fixed_code", "").strip()
            changes_made = parsed.get("changes_made", [])

            if not fixed_code:
                logger.warning("Fixer attempt %d: empty fixed_code returned", attempt)
                continue

            # Verify the fix by actually running the patched code
            verification = run_code(fixed_code)
            if verification.succeeded:
                logger.info(
                    "Fixer → fix VERIFIED on attempt %d | tokens=%d",
                    attempt, total_tokens,
                )
                return FixerResult(
                    fixed_code=fixed_code,
                    verified=True,
                    verification_output=verification.stdout,
                    changes_made=changes_made,
                    token_count=total_tokens,
                    attempts=attempts,
                )

            logger.warning(
                "Fixer attempt %d: fix NOT verified | stderr=%s",
                attempt, verification.stderr[:200],
            )

        # Return best-effort fix even if unverified
        parsed = self._parse(last_raw)
        logger.warning("Fixer → returning unverified fix after %d attempts", attempts)
        return FixerResult(
            fixed_code=parsed.get("fixed_code", code),
            verified=False,
            verification_output="Verification failed — fix may require manual review.",
            changes_made=parsed.get("changes_made", []),
            token_count=total_tokens,
            attempts=attempts,
        )

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            # Last resort: try extracting code block directly
            code_match = re.search(r"```(?:python)?\n([\s\S]+?)```", raw)
            if code_match:
                return {"fixed_code": code_match.group(1), "changes_made": []}
            logger.error("Fixer JSON parse completely failed")
            return {"fixed_code": "", "changes_made": []}
