"""
GhostDebugger — Agent 2: Reproducer

Executes the buggy code in a safe sandbox to:
  1. Confirm the bug actually exists
  2. Capture the exact traceback
  3. Normalise the error for downstream agents

Zero LLM tokens used here — pure subprocess execution.
This is what separates GhostDebugger from chatbot-based debuggers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.sandbox import ExecutionResult, run_code

logger = logging.getLogger(__name__)


@dataclass
class ReproducerResult:
    reproduced: bool
    stdout: str
    stderr: str
    traceback: str
    error_type: str
    error_message: str
    exit_code: int
    timed_out: bool

    @property
    def summary(self) -> str:
        if not self.reproduced:
            return "Code executed successfully — no error reproduced."
        lines = []
        if self.error_type:
            lines.append(f"Error Type: {self.error_type}")
        if self.error_message:
            lines.append(f"Message: {self.error_message}")
        if self.traceback:
            lines.append(f"Traceback:\n{self.traceback}")
        return "\n".join(lines)


def _extract_error_type(stderr: str) -> tuple[str, str]:
    """Parse 'ErrorType: message' from stderr."""
    for line in reversed(stderr.strip().splitlines()):
        line = line.strip()
        if ": " in line and not line.startswith(" ") and not line.startswith("File"):
            parts = line.split(": ", 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
        elif line and not line.startswith(" ") and not line.startswith("File") \
                and not line.startswith("Traceback"):
            return line, ""
    return "UnknownError", ""


class ReproducerAgent:
    def reproduce(self, code: str) -> ReproducerResult:
        result: ExecutionResult = run_code(code)

        if result.succeeded:
            logger.info("Reproducer → code ran successfully, no error")
            return ReproducerResult(
                reproduced=False,
                stdout=result.stdout,
                stderr="",
                traceback="",
                error_type="",
                error_message="",
                exit_code=0,
                timed_out=False,
            )

        error_type, error_message = _extract_error_type(result.stderr)
        logger.info(
            "Reproducer → error reproduced: %s | exit_code=%d | timed_out=%s",
            error_type, result.returncode, result.timed_out,
        )

        return ReproducerResult(
            reproduced=True,
            stdout=result.stdout,
            stderr=result.stderr,
            traceback=result.stderr,  # Python stderr IS the traceback
            error_type=error_type,
            error_message=error_message,
            exit_code=result.returncode,
            timed_out=result.timed_out,
        )
