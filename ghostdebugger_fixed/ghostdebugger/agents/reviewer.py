"""
GhostDebugger — Agent 5: Reviewer

Uses Gemma 4 31B (accounts/fireworks/models/gemma-4-31b-it) to write
a senior-developer style post-mortem explanation. This:
  - Explains what the bug was and why it happened
  - Describes what the fix does
  - Provides best-practice advice to prevent recurrence
  - Unlocks the AMD Gemma prize category

Gemma is used here specifically because:
  1. It's a Google DeepMind model on AMD hardware → prize eligibility
  2. 256K context window → can see the full code + all agent outputs
  3. Strong instruction following → produces clean, readable explanations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.fixer import FixerResult
from agents.reproducer import ReproducerResult
from agents.router import RouterResult
from agents.tracer import TracerResult
from core.llm_client import LLMClient, SessionTokenTracker

logger = logging.getLogger(__name__)


@dataclass
class ReviewerResult:
    explanation: str
    severity: str          # LOW | MEDIUM | HIGH | CRITICAL
    prevention_tips: list[str]
    code_quality_notes: list[str]
    token_count: int
    confidence: float = 0.0        # 0.0-1.0 — how confident Reviewer is the fix is correct
    fix_risks: list[str] = None    # short risk flags, e.g. "untested edge case"

    def __post_init__(self):
        if self.fix_risks is None:
            self.fix_risks = []


_SYSTEM = """\
You are a principal software engineer conducting a code review and post-mortem.
Write clearly for a developer audience. Be direct, specific, and actionable.
Avoid generic advice. Reference the actual code, variable names, and line numbers where relevant.
"""

_USER_TEMPLATE = """\
Write a post-mortem debugging report for the following session.

## Original Buggy Code
```python
{code}
```

## Fixed Code
```python
{fixed_code}
```

## Root Cause Found
{root_cause}

## Changes Made
{changes}

## Error That Was Fixed
{error_summary}

## Was Fix Verified?
{verified}

Write a post-mortem report with these four sections:

**What happened**: Explain the bug in plain English. What did the code try to do, and what went wrong?

**Why it happened**: Explain the underlying technical reason. Reference specific line numbers and variable names.

**What was fixed**: Describe each change made and why that specific change resolves the root cause.

**How to prevent this**: Give 2-3 concrete, specific best practices to avoid this class of bug in future.

Also provide:
- severity: one of LOW | MEDIUM | HIGH | CRITICAL
- confidence: a float 0.0-1.0 for how confident YOU are that this fix correctly
  resolves the root cause without introducing new problems. Use these bands:
    0.9-1.0 = fix directly addresses root cause, verified execution, no visible side effects
    0.6-0.89 = likely correct, but touches shared state or has untested edge cases
    0.3-0.59 = fix suppresses the symptom without clearly addressing the root cause
    <0.3 = speculative or unverified
- fix_risks: list of 0-2 short risk flags if confidence < 0.9 (e.g. "assumes input is never None"), empty list if none
- prevention_tips: list of 2-3 specific actionable tips (strings)
- code_quality_notes: list of 1-2 additional code quality observations unrelated to the bug (strings)

Format your response as:

EXPLANATION:
[your four-section post-mortem here]

SEVERITY: [LOW|MEDIUM|HIGH|CRITICAL]

CONFIDENCE: [a number between 0.0 and 1.0]

FIX_RISKS:
- risk 1 (omit this section entirely if no risks)

PREVENTION_TIPS:
- tip 1
- tip 2
- tip 3

CODE_QUALITY_NOTES:
- note 1
- note 2
"""


def _parse_reviewer_output(raw: str) -> tuple[str, str, list[str], list[str], float, list[str]]:
    """Parse the structured text output from Gemma."""
    explanation = ""
    severity = "MEDIUM"
    prevention_tips: list[str] = []
    code_quality_notes: list[str] = []
    confidence = 0.7  # neutral default if model omits the field
    fix_risks: list[str] = []

    current_section = None

    for line in raw.splitlines():
        line_stripped = line.strip()

        if line_stripped.startswith("EXPLANATION:"):
            current_section = "explanation"
        elif line_stripped.startswith("SEVERITY:"):
            sev = line_stripped.replace("SEVERITY:", "").strip().upper()
            if sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                severity = sev
            current_section = None
        elif line_stripped.startswith("CONFIDENCE:"):
            raw_val = line_stripped.replace("CONFIDENCE:", "").strip()
            try:
                val = float(raw_val)
                confidence = max(0.0, min(1.0, val))
            except ValueError:
                pass  # keep neutral default
            current_section = None
        elif line_stripped.startswith("FIX_RISKS:"):
            current_section = "fix_risks"
        elif line_stripped.startswith("PREVENTION_TIPS:"):
            current_section = "prevention"
        elif line_stripped.startswith("CODE_QUALITY_NOTES:"):
            current_section = "quality"
        elif current_section == "explanation":
            explanation += line + "\n"
        elif current_section == "fix_risks" and line_stripped.startswith("- "):
            fix_risks.append(line_stripped[2:].strip())
        elif current_section == "prevention" and line_stripped.startswith("- "):
            prevention_tips.append(line_stripped[2:].strip())
        elif current_section == "quality" and line_stripped.startswith("- "):
            code_quality_notes.append(line_stripped[2:].strip())

    # Fallback if parsing fails
    if not explanation:
        explanation = raw

    return explanation.strip(), severity, prevention_tips, code_quality_notes, confidence, fix_risks


class ReviewerAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def review(
        self,
        code: str,
        tracer: TracerResult,
        fixer: FixerResult,
        reproducer: ReproducerResult,
        router: RouterResult,
        tracker: SessionTokenTracker | None = None,
    ) -> ReviewerResult:
        changes_text = "\n".join(f"- {c}" for c in fixer.changes_made) \
                       if fixer.changes_made else "See fixed code above."

        prompt = _USER_TEMPLATE.format(
            code=code,
            fixed_code=fixer.fixed_code,
            root_cause=tracer.root_cause,
            changes=changes_text,
            error_summary=reproducer.summary if reproducer.reproduced else "Logic error (no traceback)",
            verified="YES — fix confirmed by re-running the code" if fixer.verified
                     else "NO — fix is best-effort, requires manual verification",
        )

        raw, usage = self._client.chat(
            "reviewer",   # Always Gemma 4 regardless of complexity tier
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
            temperature=0.2,
            tracker=tracker,
        )

        explanation, severity, prevention_tips, quality_notes, confidence, fix_risks = \
            _parse_reviewer_output(raw)

        result = ReviewerResult(
            explanation=explanation,
            severity=severity,
            prevention_tips=prevention_tips,
            code_quality_notes=quality_notes,
            token_count=usage.total_tokens,
            confidence=confidence,
            fix_risks=fix_risks,
        )

        logger.info(
            "Reviewer → severity=%s | confidence=%.2f | tokens=%d | tips=%d",
            result.severity, result.confidence, result.token_count, len(result.prevention_tips),
        )
        return result
