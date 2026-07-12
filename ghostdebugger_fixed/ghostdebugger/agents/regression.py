"""
GhostDebugger — Regression Test Agent

Auto-generates a minimal regression test proving the fix is durable
(not just "ran once without crashing" like the Fixer's basic verification),
and exposes a re-run entry point for the on-demand "verify again" button.

Reuses core.sandbox.run_code — no new isolation mechanism, no new
dependency (deliberately NOT using pytest, to avoid adding a new
requirement this close to deadline; tests are plain assert-based scripts,
consistent with how sandbox.run_code already executes arbitrary scripts).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.llm_client import LLMClient, SessionTokenTracker
from core.sandbox import run_code

logger = logging.getLogger(__name__)


@dataclass
class RegressionResult:
    test_code: str
    passed: bool
    output: str
    generated: bool  # False if generation failed and we skipped verification


_SYSTEM = """\
You are a test-generation agent. Given a bug description and a fixed piece
of Python code, write a SHORT, SELF-CONTAINED regression script that:
  1. Defines or calls the fixed function/code directly (it will run in the
     SAME file as the fixed code — do not import anything)
  2. Contains plain `assert` statements that would have FAILED against the
     original buggy behavior and PASS against the fix
  3. Prints "REGRESSION_PASS" as the final line if all asserts succeed
  4. Uses no external libraries, no network, no file I/O

Respond ONLY with the raw Python script. No markdown fences, no explanation.
"""

_USER_TEMPLATE = """\
ROOT CAUSE THAT WAS FIXED:
{root_cause}

FIXED CODE (this will be prepended before your test — do not redefine it,
just call it and assert on results):
```python
{fixed_code}
```

Write the regression test script now. End with print("REGRESSION_PASS") only
if every assertion passes.
"""


def _clean(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:python)?\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


class RegressionAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def generate_and_verify(
        self,
        fixed_code: str,
        root_cause: str,
        tracker: SessionTokenTracker | None = None,
    ) -> RegressionResult:
        prompt = _USER_TEMPLATE.format(root_cause=root_cause, fixed_code=fixed_code)

        try:
            raw, _usage = self._client.chat(
                "mid",  # regression test generation doesn't need the heavy tier
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.1,
                tracker=tracker,
            )
        except Exception as exc:
            logger.warning("Regression test generation failed: %s", exc)
            return RegressionResult(test_code="", passed=False, output=str(exc), generated=False)

        test_code = _clean(raw)
        result = self.verify(fixed_code, test_code)
        return result

    @staticmethod
    def verify(fixed_code: str, test_code: str) -> RegressionResult:
        """Re-runs fixed_code + test_code together. Used both for the
        initial generation pass and for the on-demand 'verify again' button."""
        combined = f"{fixed_code}\n\n# --- regression test ---\n{test_code}\n"
        execution = run_code(combined)

        passed = execution.succeeded and "REGRESSION_PASS" in execution.stdout
        output = execution.stdout if execution.succeeded else execution.error_output

        return RegressionResult(
            test_code=test_code,
            passed=passed,
            output=output,
            generated=True,
        )
