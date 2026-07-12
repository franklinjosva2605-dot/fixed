"""
GhostDebugger — Sandbox
Executes untrusted Python code in a separate subprocess with a hard
timeout plus best-effort memory/CPU/process-count limits (Linux/macOS
only via `resource`).

IMPORTANT — scope of isolation: this is PROCESS-level isolation only.
It does NOT restrict filesystem access or network access, and it is not
a substitute for container/VM-level sandboxing (gVisor, nsjail,
Firecracker, etc). Treat any code reaching this function as capable of
reading/writing anything the running user can, and reaching the network.
Run the app as a non-root user with minimal filesystem permissions, and
avoid exposing debug endpoints without authentication.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass

try:
    import resource  # POSIX only — not available on Windows
except ImportError:  # pragma: no cover
    resource = None


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def error_output(self) -> str:
        """Combined error info for agents to reason about."""
        parts = []
        if self.timed_out:
            parts.append("[TIMEOUT] Execution exceeded time limit.")
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        if not self.succeeded and self.stdout.strip():
            parts.append(f"[stdout before crash]\n{self.stdout.strip()}")
        return "\n".join(parts) if parts else ""

    @property
    def success_output(self) -> str:
        return self.stdout.strip()


def _limit_resources(memory_mb: int, cpu_seconds: int) -> None:
    """
    preexec_fn: applied in the child process right after fork(), before
    exec(). Caps address space, CPU time, and process count so a single
    submission can't exhaust host memory/CPU or fork-bomb the box.
    Best-effort — failures to set a given limit are swallowed so a
    restrictive host (e.g. limits already lower than requested) doesn't
    break execution entirely.
    """
    if resource is None:
        return
    mem_bytes = memory_mb * 1024 * 1024
    for limit, value in (
        (resource.RLIMIT_AS, (mem_bytes, mem_bytes)),
        (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds)),
        (getattr(resource, "RLIMIT_NPROC", None), (32, 32)),
    ):
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, value)
        except (ValueError, OSError):
            pass


def run_code(code: str, timeout: int | None = None) -> ExecutionResult:
    """
    Execute Python code in a subprocess with a hard timeout and
    best-effort memory/CPU/process-count limits.

    - Writes code to a temp file (no shell injection risk)
    - Hard timeout via subprocess
    - Captures all output
    - Never raises — always returns ExecutionResult

    See module docstring: this is process-level isolation, not a full
    sandbox — it does not restrict filesystem or network access.
    """
    timeout = timeout or int(os.environ.get("SANDBOX_TIMEOUT", "10"))
    memory_mb = int(os.environ.get("SANDBOX_MEMORY_MB", "256"))

    # Wrap code so syntax errors surface cleanly
    safe_code = textwrap.dedent(code)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(safe_code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=(lambda: _limit_resources(memory_mb, timeout + 2))
                       if resource is not None else None,
        )
        return ExecutionResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            stdout="",
            stderr="",
            returncode=-1,
            timed_out=True,
        )
    except Exception as exc:
        return ExecutionResult(
            stdout="",
            stderr=str(exc),
            returncode=-1,
            timed_out=False,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
