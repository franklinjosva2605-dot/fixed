"""
GhostDebugger — Pipeline Orchestrator

Coordinates all 5 agents in sequence:
  Router → Reproducer → Tracer → Fixer → Reviewer

Returns a structured DebugResult with full agent outputs
and token efficiency metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from agents.fixer import FixerResult, FixerAgent
from agents.reproducer import ReproducerResult, ReproducerAgent
from agents.reviewer import ReviewerResult, ReviewerAgent
from agents.router import RouterResult, RouterAgent
from agents.tracer import TracerResult, TracerAgent
from agents.regression import RegressionResult, RegressionAgent
from core.llm_client import LLMClient, SessionTokenTracker

logger = logging.getLogger(__name__)


@dataclass
class DebugResult:
    # Agent outputs
    router: RouterResult
    reproducer: ReproducerResult
    tracer: TracerResult
    fixer: FixerResult
    reviewer: ReviewerResult
    regression: RegressionResult | None = None

    # Performance
    token_summary: dict = field(default_factory=dict)
    total_latency_ms: float = 0.0
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "error": self.error,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "routing": {
                "tier": self.router.tier.value,
                "model_used": self.router.model_key,
                "bug_type": self.router.bug_type,
                "language": self.router.language,
                "reasoning": self.router.reasoning,
                "confidence": self.router.confidence,
            },
            "reproduction": {
                "reproduced": self.reproducer.reproduced,
                "error_type": self.reproducer.error_type,
                "error_message": self.reproducer.error_message,
                "traceback": self.reproducer.traceback,
            },
            "root_cause": {
                "explanation": self.tracer.root_cause,
                "faulty_lines": self.tracer.faulty_lines,
                "faulty_snippet": self.tracer.faulty_code_snippet,
                "execution_path": self.tracer.execution_path,
                "variable_states": self.tracer.variable_states,
                "confidence": self.tracer.confidence,
            },
            "fix": {
                "fixed_code": self.fixer.fixed_code,
                "verified": self.fixer.verified,
                "verification_output": self.fixer.verification_output,
                "changes_made": self.fixer.changes_made,
                "attempts": self.fixer.attempts,
            },
            "review": {
                "explanation": self.reviewer.explanation,
                "severity": self.reviewer.severity,
                "prevention_tips": self.reviewer.prevention_tips,
                "code_quality_notes": self.reviewer.code_quality_notes,
                "confidence": self.reviewer.confidence,
                "fix_risks": self.reviewer.fix_risks,
            },
            "regression": {
                "generated": self.regression.generated if self.regression else False,
                "passed": self.regression.passed if self.regression else False,
                "test_code": self.regression.test_code if self.regression else "",
                "output": self.regression.output if self.regression else "",
            },
            "token_efficiency": self.token_summary,
        }


class DebugPipeline:
    def __init__(self) -> None:
        client = LLMClient()
        self._router     = RouterAgent(client)
        self._reproducer = ReproducerAgent()
        self._tracer     = TracerAgent(client)
        self._fixer      = FixerAgent(client)
        self._reviewer   = ReviewerAgent(client)
        self._regression = RegressionAgent(client)

    def run(self, code: str, error_hint: str = "") -> DebugResult:
        tracker = SessionTokenTracker()
        start = time.perf_counter()

        logger.info("Pipeline start | code_len=%d", len(code))

        # ── Agent 1: Route ────────────────────────────────────────────────
        router_result = self._router.route(code, error_hint, tracker)

        # ── Agent 2: Reproduce ────────────────────────────────────────────
        reproducer_result = self._reproducer.reproduce(code)

        # ── Agent 3: Trace ────────────────────────────────────────────────
        tracer_result = self._tracer.trace(
            code, reproducer_result, router_result, tracker
        )

        # ── Agent 4: Fix ──────────────────────────────────────────────────
        fixer_result = self._fixer.fix(
            code, tracer_result, reproducer_result, router_result, tracker
        )

        # ── Agent 5: Review ───────────────────────────────────────────────
        reviewer_result = self._reviewer.review(
            code, tracer_result, fixer_result,
            reproducer_result, router_result, tracker,
        )

        # ── Agent 6: Regression test (only if Fixer's fix is verified —
        #     no point durability-testing a fix we already know fails) ────
        regression_result = None
        if fixer_result.verified:
            try:
                regression_result = self._regression.generate_and_verify(
                    fixer_result.fixed_code, tracer_result.root_cause, tracker,
                )
            except Exception as exc:
                logger.warning("Regression test step failed, continuing: %s", exc)

        latency_ms = (time.perf_counter() - start) * 1000
        token_summary = tracker.summary()

        logger.info(
            "Pipeline complete | latency=%.0fms tokens=%d savings=%.1f%% regression_passed=%s",
            latency_ms, token_summary["total_tokens"], token_summary["savings_pct"],
            regression_result.passed if regression_result else "skipped",
        )

        return DebugResult(
            router=router_result,
            reproducer=reproducer_result,
            tracer=tracer_result,
            fixer=fixer_result,
            reviewer=reviewer_result,
            regression=regression_result,
            token_summary=token_summary,
            total_latency_ms=latency_ms,
            success=True,
        )
