"""OMNICORE: deterministic, cross-domain tool-execution resilience kernel.

Tool adapters own preflight, action, postcondition and rollback. The model never
decides VERIFIED by text; only a tool-specific postcondition can establish it.
"""
from __future__ import annotations
import asyncio
import enum
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

class State(str, enum.Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"

class ErrorKind(str, enum.Enum):
    TRANSIENT = "TRANSIENT"
    PERMISSION = "PERMISSION"
    SANDBOX = "SANDBOX"
    AUTH = "AUTH"
    CONFIG = "CONFIG"
    RESOURCE = "RESOURCE"
    DEPENDENCY = "DEPENDENCY"
    COMPATIBILITY = "COMPATIBILITY"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    data: Any = None
    code: str = ""
    stderr: str = ""
    exit_code: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ToolSpec:
    name: str
    action: Callable[[dict[str, Any]], Awaitable[ToolOutcome]]
    verify: Callable[[ToolOutcome, dict[str, Any]], Awaitable[bool]]
    preflight: Callable[[dict[str, Any]], Awaitable[bool]]
    idempotent: bool = False
    max_attempts: int = 1
    timeout_s: float = 90.0
    rollback: Callable[[dict[str, Any]], Awaitable[None]] | None = None

@dataclass
class ExecutionReport:
    state: State
    tool: str
    attempts: int
    error_kind: ErrorKind | None
    evidence: list[dict[str, Any]]
    message: str
    verified: bool = False

class ResilienceKernel:
    """Fail-closed retry policy. No unbounded repeats or fake success."""
    def __init__(self, failure_threshold: int = 3, circuit_seconds: float = 120.0):
        self.failures: dict[str, int] = {}
        self.blocked_until: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.failure_threshold = failure_threshold
        self.circuit_seconds = circuit_seconds

    @staticmethod
    def classify(outcome: ToolOutcome) -> ErrorKind:
        s = (outcome.code + " " + outcome.stderr).lower()
        if any(x in s for x in ("sandbox", "seatbelt", "isolation unavailable")):
            return ErrorKind.SANDBOX
        if any(x in s for x in ("permission denied", "operation not permitted", "read-only file system")):
            return ErrorKind.PERMISSION
        if any(x in s for x in ("unauthorized", "invalid token", "http 401", "http 403")):
            return ErrorKind.AUTH
        if any(x in s for x in ("disk full", "no space left", "out of memory")):
            return ErrorKind.RESOURCE
        if any(x in s for x in ("no module named", "dependency", "package not found")):
            return ErrorKind.DEPENDENCY
        if any(x in s for x in ("unsupported architecture", "incompatible", "wrong platform")):
            return ErrorKind.COMPATIBILITY
        if any(x in s for x in ("timeout", "timed out", "connection reset", "temporarily unavailable", "http 502", "http 503", "http 504")):
            return ErrorKind.TRANSIENT
        if any(x in s for x in ("blocked by policy", "unsafe", "disallowed")):
            return ErrorKind.UNSAFE
        if any(x in s for x in ("missing config", "invalid configuration", "not configured")):
            return ErrorKind.CONFIG
        return ErrorKind.UNKNOWN

    async def execute(self, spec: ToolSpec, args: dict[str, Any]) -> ExecutionReport:
        key = spec.name + ":" + hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            evidence: list[dict[str, Any]] = []
            if self.blocked_until.get(spec.name, 0) > time.monotonic():
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.TRANSIENT, evidence, "Circuit breaker open")
            try:
                allowed = await asyncio.wait_for(spec.preflight(args), timeout=min(spec.timeout_s, 20))
            except Exception as exc:
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.CONFIG, evidence, f"Preflight error: {type(exc).__name__}")
            if not allowed:
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.UNSAFE, evidence, "Preflight rejected")
            maximum = max(1, min(spec.max_attempts, 4)) if spec.idempotent else 1
            latest = ErrorKind.UNKNOWN
            for attempt in range(1, maximum + 1):
                try:
                    result = await asyncio.wait_for(spec.action(args), timeout=spec.timeout_s)
                except asyncio.TimeoutError:
                    result = ToolOutcome(False, code="TIMEOUT", stderr="timed out")
                except Exception as exc:
                    result = ToolOutcome(False, code=type(exc).__name__, stderr=str(exc)[:250])
                latest = self.classify(result) if not result.ok else None
                proof = {"attempt": attempt, "ok": result.ok, "exit_code": result.exit_code,
                         "error_kind": latest.value if latest else None, "proof": result.evidence}
                evidence.append(proof)
                if result.ok:
                    try:
                        validated = await asyncio.wait_for(spec.verify(result, args), timeout=min(spec.timeout_s, 30))
                    except Exception:
                        validated = False
                    if validated:
                        self.failures.pop(spec.name, None)
                        return ExecutionReport(State.VERIFIED, spec.name, attempt, None, evidence, "Independent postcondition passed", True)
                    latest = ErrorKind.UNKNOWN
                    evidence[-1]["postcondition"] = "FAILED"
                if latest != ErrorKind.TRANSIENT or attempt == maximum:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
            self.failures[spec.name] = self.failures.get(spec.name, 0) + 1
            if self.failures[spec.name] >= self.failure_threshold:
                self.blocked_until[spec.name] = time.monotonic() + self.circuit_seconds
            if spec.rollback:
                try:
                    await asyncio.wait_for(spec.rollback(args), timeout=min(spec.timeout_s, 30))
                    evidence.append({"rollback": "OK"})
                except Exception as exc:
                    evidence.append({"rollback": "FAILED", "error": type(exc).__name__})
            return ExecutionReport(State.BLOCKED if latest in {ErrorKind.PERMISSION, ErrorKind.SANDBOX, ErrorKind.AUTH, ErrorKind.UNSAFE} else State.FAILED,
                                   spec.name, len([e for e in evidence if "attempt" in e]), latest, evidence,
                                   "No verified completion; do not report success")
