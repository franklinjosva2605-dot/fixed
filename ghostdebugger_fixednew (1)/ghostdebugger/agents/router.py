"""
GhostDebugger — Agent 1: Complexity Router

Classifies incoming buggy code into one of three tiers:
  SIMPLE  → syntax / name errors    → qwen3-8b  (cheapest)
  MEDIUM  → logic / runtime errors  → llama-8b  (balanced)
  COMPLEX → architecture / design   → llama-70b (most capable)

Uses the router model itself for classification — spends ~50 tokens
to route correctly, saving hundreds on the downstream agents.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum

from core.llm_client import LLMClient, SessionTokenTracker

logger = logging.getLogger(__name__)


class ComplexityTier(str, Enum):
    SIMPLE  = "SIMPLE"
    MEDIUM  = "MEDIUM"
    COMPLEX = "COMPLEX"


# Maps tier → model key used by downstream agents
TIER_MODEL_MAP: dict[ComplexityTier, str] = {
    ComplexityTier.SIMPLE:  "mid",     # qwen is router-only; mid handles fixes
    ComplexityTier.MEDIUM:  "mid",
    ComplexityTier.COMPLEX: "heavy",
}


@dataclass
class RouterResult:
    tier: ComplexityTier
    model_key: str
    bug_type: str
    language: str
    reasoning: str
    token_count: int
    confidence: float


_SYSTEM = """\
You are a code complexity classifier for a token-efficient debugging system.
Classify the given code and its error to decide which LLM tier should handle it.

Respond ONLY with valid JSON — no markdown, no explanation outside the JSON.
"""

_USER_TEMPLATE = """\
Classify this code and error:

```
{code}
```

Error / symptom:
{error_hint}

Return JSON with exactly these fields:
{{
  "tier": "SIMPLE" | "MEDIUM" | "COMPLEX",
  "bug_type": short label e.g. "SyntaxError" | "LogicError" | "ArchitectureIssue",
  "language": detected language e.g. "Python",
  "reasoning": one sentence why you chose this tier,
  "confidence": float 0.0-1.0
}}

Tier definitions:
- SIMPLE: syntax errors, undefined variables, import errors, typos — fixable by reading the traceback
- MEDIUM: logic bugs, off-by-one, wrong algorithm, runtime type errors, data flow issues
- COMPLEX: architectural flaws, concurrency issues, incorrect design patterns, multi-module dependencies
"""


class RouterAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def route(
        self,
        code: str,
        error_hint: str = "",
        tracker: SessionTokenTracker | None = None,
    ) -> RouterResult:
        prompt = _USER_TEMPLATE.format(
            code=code[:3000],  # cap to keep routing cheap
            error_hint=error_hint[:500] if error_hint else "No error provided — infer from code.",
        )

        raw, usage = self._client.chat(
            "router",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
            temperature=0.0,
            tracker=tracker,
            json_mode=True,
        )

        parsed = self._parse(raw)
        tier = ComplexityTier(parsed.get("tier", "MEDIUM").upper())

        result = RouterResult(
            tier=tier,
            model_key=TIER_MODEL_MAP[tier],
            bug_type=parsed.get("bug_type", "Unknown"),
            language=parsed.get("language", "Python"),
            reasoning=parsed.get("reasoning", ""),
            token_count=usage.total_tokens,
            confidence=float(parsed.get("confidence", 0.8)),
        )

        logger.info(
            "Router → tier=%s model=%s bug_type=%s tokens=%d",
            result.tier, result.model_key, result.bug_type, result.token_count,
        )
        return result

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            # Strip markdown fences if model ignores json_mode
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("Router JSON parse failed — defaulting to MEDIUM. Raw: %s", raw[:200])
            return {"tier": "MEDIUM", "bug_type": "Unknown", "language": "Python",
                    "reasoning": "Parse failed", "confidence": 0.5}
