"""
GhostDebugger — FastAPI Backend

Endpoints:
  POST /debug          — run full pipeline, return JSON
  GET  /health         — health check (required for Docker eval)
  GET  /metrics        — session metrics summary
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# Load .env before anything reads os.environ (FIREWORKS_API_KEY, AMD_*, etc.).
# docker-compose's `env_file:` does this automatically inside containers, but
# running via start.sh directly (e.g. in AMD Developer Cloud JupyterLab) does
# not export .env into the process — this line is required for that path.
load_dotenv()

from core.llm_client import HEAVY_MODEL_COST
from core.pipeline import DebugPipeline, DebugResult

# Blended per-token cost for the heavy (70B) model, used to convert the
# USD savings figure back into an approximate token count for /metrics.
# Derived from core.llm_client.HEAVY_MODEL_COST so the two can't drift.
_HEAVY_COST_PER_TOKEN = (HEAVY_MODEL_COST["input"] + HEAVY_MODEL_COST["output"]) / 2 / 1_000_000

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_CODE_LENGTH = int(os.environ.get("MAX_CODE_LENGTH", "10000"))

# Session-wide token budget guard — prevents a single runaway session
# (or a stray script hammering /debug) from silently burning through
# your Fireworks/AMD credits. 0 or unset disables the cap.
TOKEN_BUDGET_PER_SESSION = int(os.environ.get("TOKEN_BUDGET_PER_SESSION", "0"))
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "0.8"))

# ── App lifecycle ─────────────────────────────────────────────────────────
pipeline: DebugPipeline | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    logger.info("GhostDebugger starting — initialising pipeline...")
    pipeline = DebugPipeline()
    logger.info("Pipeline ready ✓")
    yield
    logger.info("GhostDebugger shutting down.")

app = FastAPI(
    title="GhostDebugger",
    description="Token-efficient multi-agent AI debugging system — AMD AI Developer Hackathon Act II",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session metrics (in-memory, resets on restart) ────────────────────────
_session_stats: dict = {
    "total_requests": 0,
    "successful_requests": 0,
    "total_tokens": 0,
    "total_savings_tokens": 0,
    "uptime_start": time.time(),
}


# ── Schemas ───────────────────────────────────────────────────────────────
class DebugRequest(BaseModel):
    code: str = Field(..., description="Buggy Python code to debug")
    error_hint: str = Field("", description="Optional: paste error message you're seeing")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("code must not be empty")
        if len(v) > MAX_CODE_LENGTH:
            raise ValueError(f"code exceeds {MAX_CODE_LENGTH} character limit")
        return v


class ReverifyRequest(BaseModel):
    fixed_code: str = Field(..., description="The fixed code to re-test")
    test_code: str = Field(..., description="The regression test script to run against it")

    @field_validator("fixed_code", "test_code")
    @classmethod
    def validate_length(cls, v: str) -> str:
        if len(v) > MAX_CODE_LENGTH:
            raise ValueError(f"input exceeds {MAX_CODE_LENGTH} character limit")
        return v


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    pipeline_ready: bool


# ── Routes ────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_seconds=round(time.time() - _session_stats["uptime_start"], 1),
        pipeline_ready=pipeline is not None,
    )


@app.get("/metrics", tags=["System"])
async def metrics():
    uptime = time.time() - _session_stats["uptime_start"]
    reqs = _session_stats["total_requests"]
    return {
        "uptime_seconds": round(uptime, 1),
        "total_requests": reqs,
        "successful_requests": _session_stats["successful_requests"],
        "success_rate_pct": round(
            (_session_stats["successful_requests"] / reqs * 100) if reqs else 0, 1
        ),
        "total_tokens_used": _session_stats["total_tokens"],
        "total_tokens_saved": _session_stats["total_savings_tokens"],
        "avg_savings_pct": round(
            (_session_stats["total_savings_tokens"] /
             (_session_stats["total_tokens"] + _session_stats["total_savings_tokens"]) * 100)
            if (_session_stats["total_tokens"] + _session_stats["total_savings_tokens"]) > 0
            else 0, 1
        ),
    }


@app.post("/debug", tags=["Debug"])
async def debug(request: DebugRequest):
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialised")

    if TOKEN_BUDGET_PER_SESSION and _session_stats["total_tokens"] >= TOKEN_BUDGET_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail="Session token budget exceeded (TOKEN_BUDGET_PER_SESSION). "
                   "Restart the server or raise the limit in .env to continue.",
        )

    _session_stats["total_requests"] += 1

    try:
        # Pipeline does blocking network + subprocess calls — run it off
        # the event loop so one debug session doesn't freeze the whole
        # server (including /health) for other concurrent requests.
        result: DebugResult = await asyncio.to_thread(
            pipeline.run, code=request.code, error_hint=request.error_hint,
        )
    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail="Pipeline error — check server logs for details.")

    _session_stats["successful_requests"] += 1
    tok = result.token_summary
    _session_stats["total_tokens"] += tok.get("total_tokens", 0)

    if TOKEN_BUDGET_PER_SESSION and \
            _session_stats["total_tokens"] >= TOKEN_BUDGET_PER_SESSION * ALERT_THRESHOLD:
        logger.warning(
            "Session token usage at %d/%d (%.0f%% of budget)",
            _session_stats["total_tokens"], TOKEN_BUDGET_PER_SESSION,
            _session_stats["total_tokens"] / TOKEN_BUDGET_PER_SESSION * 100,
        )

    # Approximate tokens saved = (hypothetical - actual)
    saved = int(
        (tok.get("hypothetical_cost_usd", 0) - tok.get("actual_cost_usd", 0))
        / _HEAVY_COST_PER_TOKEN
    )
    _session_stats["total_savings_tokens"] += max(0, saved)

    return JSONResponse(content=result.to_dict())


@app.post("/reverify", tags=["Debug"])
async def reverify(request: ReverifyRequest):
    """Re-run the regression test on demand — the on-stage 'prove it still
    works' moment. Stateless: takes the fixed code + test straight from
    what the frontend already has from the /debug response."""
    from agents.regression import RegressionAgent

    try:
        result = await asyncio.to_thread(
            RegressionAgent.verify, request.fixed_code, request.test_code,
        )
    except Exception as exc:
        logger.exception("Reverify error: %s", exc)
        raise HTTPException(status_code=500, detail="Reverify error — check server logs for details.")

    return JSONResponse(content={
        "passed": result.passed,
        "output": result.output,
        "test_code": result.test_code,
    })


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": "Check server logs for details."},
    )


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
