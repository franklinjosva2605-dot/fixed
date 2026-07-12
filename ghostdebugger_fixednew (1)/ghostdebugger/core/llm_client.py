"""
GhostDebugger — LLM Client
OpenAI-compatible wrapper for Fireworks AI with full token tracking.
Supports graceful fallback: Fireworks → AMD Cloud.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ── Model Registry ────────────────────────────────────────────────────────
# Verified model IDs from Fireworks AI as of July 2026
MODELS = {
    # Router — smallest, fastest, cheapest (routing only)
    "router": "accounts/fireworks/models/qwen3-8b",

    # Workhorse — mid-range for most debugging tasks
    "mid":    "accounts/fireworks/models/llama-v3p1-8b-instruct",

    # Heavy — complex architectural bugs only
    "heavy":  "accounts/fireworks/models/llama-v3p1-70b-instruct",

    # Reviewer — Gemma 4 (unlocks AMD Gemma prize category)
    "reviewer": "accounts/fireworks/models/gemma-4-31b-it",
}

# Token cost per 1M tokens (USD) — for savings calculation display
TOKEN_COST = {
    "accounts/fireworks/models/qwen3-8b":              {"input": 0.20,  "output": 0.20},
    "accounts/fireworks/models/llama-v3p1-8b-instruct":{"input": 0.20,  "output": 0.20},
    "accounts/fireworks/models/llama-v3p1-70b-instruct":{"input": 0.90, "output": 0.90},
    "accounts/fireworks/models/gemma-4-31b-it":        {"input": 0.90,  "output": 0.90},
}

# Hypothetical cost if we routed everything to the heavy model
HEAVY_MODEL_COST = TOKEN_COST["accounts/fireworks/models/llama-v3p1-70b-instruct"]


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    hypothetical_cost_usd: float = 0.0  # Cost if heavy model used instead

    @property
    def savings_usd(self) -> float:
        return max(0.0, self.hypothetical_cost_usd - self.cost_usd)

    @property
    def savings_pct(self) -> float:
        if self.hypothetical_cost_usd == 0:
            return 0.0
        return (self.savings_usd / self.hypothetical_cost_usd) * 100


@dataclass
class SessionTokenTracker:
    """Accumulates token usage across all agents in a debug session."""
    usages: list[TokenUsage] = field(default_factory=list)

    def add(self, usage: TokenUsage) -> None:
        self.usages.append(usage)

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self.usages)

    @property
    def total_cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.usages)

    @property
    def hypothetical_cost_usd(self) -> float:
        return sum(u.hypothetical_cost_usd for u in self.usages)

    @property
    def total_savings_usd(self) -> float:
        return max(0.0, self.hypothetical_cost_usd - self.total_cost_usd)

    @property
    def total_savings_pct(self) -> float:
        if self.hypothetical_cost_usd == 0:
            return 0.0
        return (self.total_savings_usd / self.hypothetical_cost_usd) * 100

    def summary(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "actual_cost_usd": round(self.total_cost_usd, 6),
            "hypothetical_cost_usd": round(self.hypothetical_cost_usd, 6),
            "savings_usd": round(self.total_savings_usd, 6),
            "savings_pct": round(self.total_savings_pct, 1),
            "breakdown": [
                {
                    "model": u.model,
                    "tokens": u.total_tokens,
                    "cost_usd": round(u.cost_usd, 6),
                    "savings_usd": round(u.savings_usd, 6),
                }
                for u in self.usages
            ],
        }


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    costs = TOKEN_COST.get(model, {"input": 0.90, "output": 0.90})
    return (prompt_tokens / 1_000_000 * costs["input"]) + \
           (completion_tokens / 1_000_000 * costs["output"])


def _compute_hypothetical_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1_000_000 * HEAVY_MODEL_COST["input"]) + \
           (completion_tokens / 1_000_000 * HEAVY_MODEL_COST["output"])


class LLMClient:
    """
    Single client for all LLM calls in GhostDebugger.
    Uses Fireworks AI with automatic AMD Developer Cloud fallback.
    """

    def __init__(self) -> None:
        fireworks_key = os.environ.get("FIREWORKS_API_KEY")
        if not fireworks_key:
            raise RuntimeError(
                "Missing FIREWORKS_API_KEY environment variable. "
                "Copy .env.example to .env and add your Fireworks API key "
                "(https://fireworks.ai/account/api-keys) before starting GhostDebugger."
            )
        self._fireworks = OpenAI(
            base_url="https://api.fireworks.ai/inference/v1",
            api_key=fireworks_key,
        )

        # AMD Developer Cloud fallback (same OpenAI-compatible API)
        amd_key = os.environ.get("AMD_API_KEY")
        amd_endpoint = os.environ.get(
            "AMD_CLOUD_ENDPOINT",
            "https://api.amd.developer.cloud/inference/v1",
        )
        self._amd: Optional[OpenAI] = (
            OpenAI(base_url=amd_endpoint, api_key=amd_key)
            if amd_key else None
        )

    def chat(
        self,
        model_key: str,
        messages: list[dict],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        tracker: Optional[SessionTokenTracker] = None,
        json_mode: bool = False,
    ) -> tuple[str, TokenUsage]:
        """
        Call the LLM. Returns (response_text, TokenUsage).
        Falls back to AMD Cloud if Fireworks fails.
        """
        model = MODELS[model_key]
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        start = time.perf_counter()
        response = self._call_with_fallback(kwargs)
        latency_ms = (time.perf_counter() - start) * 1000

        content = response.choices[0].message.content or ""
        usage_data = response.usage

        prompt_t = usage_data.prompt_tokens if usage_data else 0
        completion_t = usage_data.completion_tokens if usage_data else 0
        total_t = usage_data.total_tokens if usage_data else 0

        token_usage = TokenUsage(
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            total_tokens=total_t,
            model=model,
            cost_usd=_compute_cost(model, prompt_t, completion_t),
            hypothetical_cost_usd=_compute_hypothetical_cost(prompt_t, completion_t),
        )

        logger.info(
            "LLM call | model=%s key=%s tokens=%d latency=%.0fms cost=$%.6f",
            model, model_key, total_t, latency_ms, token_usage.cost_usd,
        )

        if tracker:
            tracker.add(token_usage)

        return content, token_usage

    def _call_with_fallback(self, kwargs: dict):
        """Try Fireworks first; fall back to AMD Cloud if available."""
        try:
            return self._fireworks.chat.completions.create(**kwargs)
        except Exception as fw_err:
            if self._amd:
                logger.warning(
                    "Fireworks call failed (%s). Falling back to AMD Cloud.", fw_err
                )
                try:
                    return self._amd.chat.completions.create(**kwargs)
                except Exception as amd_err:
                    logger.error("AMD Cloud fallback also failed: %s", amd_err)
                    raise amd_err
            raise fw_err
