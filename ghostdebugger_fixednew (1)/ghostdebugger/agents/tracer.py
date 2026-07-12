"""
GhostDebugger — Agent 3: Tracer

Given the original code + real traceback from the Reproducer,
the Tracer performs deep root-cause analysis:
  - Follows the execution path backwards from the crash point
  - Identifies the ACTUAL source of failure (not just the symptom)
  - Pinpoints the exact line(s) and variable(s) responsible
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from agents.reproducer import ReproducerResult
from agents.router import RouterResult
from core.llm_client import LLMClient, SessionTokenTracker

logger = logging.getLogger(__name__)


@dataclass
class TracerResult:
    root_cause: str
    faulty_lines: list[int]
    faulty_code_snippet: str
    execution_path: str
    variable_states: str
    confidence: float
    token_count: int


_SYSTEM = """\
You are a senior software engineer performing root-cause analysis.
Your job is NOT to fix the code — only to find WHY it broke.
Be precise. Trace execution backwards from the crash point to the true origin.
Respond ONLY with valid JSON.
"""

_USER_TEMPLATE = """\
Analyse this Python code and its error. Find the ROOT CAUSE.

## Original Code
```python
{code}
```

## Error Reproduced
{error_summary}

Return JSON with exactly these fields:
{{
  "root_cause": "clear one-paragraph explanation of WHY the code fails, not just what error occurred",
  "faulty_lines": [list of integer line numbers that are the source of the problem],
  "faulty_code_snippet": "the specific lines of code that are wrong",
  "execution_path": "brief description of what Python executed before the crash",
  "variable_states": "key variables and their values at the point of failure",
  "confidence": float 0.0-1.0
}}
"""


class TracerAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def trace(
        self,
        code: str,
        reproducer: ReproducerResult,
        router: RouterResult,
        tracker: SessionTokenTracker | None = None,
    ) -> TracerResult:
        prompt = _USER_TEMPLATE.format(
            code=code,
            error_summary=reproducer.summary if reproducer.reproduced
                         else "No runtime error. Possible logic/output bug. Analyse the code for logical flaws.",
        )

        raw, usage = self._client.chat(
            router.model_key,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.1,
            tracker=tracker,
            json_mode=True,
        )

        parsed = self._parse(raw)
        result = TracerResult(
            root_cause=parsed.get("root_cause", "Root cause analysis incomplete."),
            faulty_lines=parsed.get("faulty_lines", []),
            faulty_code_snippet=parsed.get("faulty_code_snippet", ""),
            execution_path=parsed.get("execution_path", ""),
            variable_states=parsed.get("variable_states", ""),
            confidence=float(parsed.get("confidence", 0.7)),
            token_count=usage.total_tokens,
        )

        logger.info(
            "Tracer → root_cause found | faulty_lines=%s tokens=%d confidence=%.2f",
            result.faulty_lines, result.token_count, result.confidence,
        )
        return result

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("Tracer JSON parse failed. Raw: %s", raw[:300])
            return {
                "root_cause": raw[:500],
                "faulty_lines": [],
                "faulty_code_snippet": "",
                "execution_path": "",
                "variable_states": "",
                "confidence": 0.4,
            }
