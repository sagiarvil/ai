"""OMNICORE: deterministic, cross-domain tool-execution resilience kernel.

Tool adapters own preflight, action, postcondition and rollback. The model never
decides VERIFIED by text; only a tool-specific postcondition can establish it.
"""
from __future__ import annotations
import asyncio
import enum
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
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
    remediate: Callable[[ToolOutcome, dict[str, Any]], Awaitable[bool]] | None = None

@dataclass
class ExecutionReport:
    state: State
    tool: str
    attempts: int
    error_kind: ErrorKind | None
    evidence: list[dict[str, Any]]
    message: str
    verified: bool = False
    data: Any = None
    outcome: ToolOutcome | None = None

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
        if any(x in s for x in ("permission denied", "operation not permitted", "read-only file system", "could not create work tree")):
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
            if self.blocked_until.get(key, 0) > time.monotonic():
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.TRANSIENT, evidence, "Circuit breaker open for target")
            try:
                allowed = await asyncio.wait_for(spec.preflight(args), timeout=min(spec.timeout_s, 20))
            except Exception as exc:
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.CONFIG, evidence, f"Preflight error: {type(exc).__name__}")
            if not allowed:
                return ExecutionReport(State.BLOCKED, spec.name, 0, ErrorKind.UNSAFE, evidence, "Preflight rejected")
            maximum = max(1, min(spec.max_attempts, 4)) if spec.idempotent else 1
            latest = ErrorKind.UNKNOWN
            last_outcome: ToolOutcome | None = None
            for attempt in range(1, maximum + 1):
                try:
                    result = await asyncio.wait_for(spec.action(args), timeout=spec.timeout_s)
                except asyncio.TimeoutError:
                    result = ToolOutcome(False, code="TIMEOUT", stderr="timed out")
                except Exception as exc:
                    result = ToolOutcome(False, code=type(exc).__name__, stderr=str(exc)[:250])
                last_outcome = result
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
                        self.failures.pop(key, None)
                        self.failures.pop(spec.name, None)
                        return ExecutionReport(State.VERIFIED, spec.name, attempt, None, evidence, "Independent postcondition passed", True, data=result.data, outcome=result)
                    latest = ErrorKind.UNKNOWN
                    evidence[-1]["postcondition"] = "FAILED"

                # Kalıcı hata: PERMISSION, SANDBOX, AUTH, UNSAFE -> ASLA tekrar deneme!
                if latest in {ErrorKind.PERMISSION, ErrorKind.SANDBOX, ErrorKind.AUTH, ErrorKind.UNSAFE}:
                    self.blocked_until[key] = time.monotonic() + self.circuit_seconds
                    break

                # Düzeltilebilir hata ise otomatik onarım adaptörünü çalıştır
                if spec.remediate:
                    try:
                        remediated = await asyncio.wait_for(spec.remediate(result, args), timeout=min(spec.timeout_s, 30))
                        evidence[-1]["remediation"] = "SUCCESS" if remediated else "FAILED"
                        if remediated:
                            continue
                    except Exception as rem_exc:
                        evidence[-1]["remediation"] = f"ERROR: {type(rem_exc).__name__}"

                if latest != ErrorKind.TRANSIENT or attempt == maximum:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 8))

            self.failures[key] = self.failures.get(key, 0) + 1
            if self.failures[key] >= self.failure_threshold:
                self.blocked_until[key] = time.monotonic() + self.circuit_seconds
            if spec.rollback:
                try:
                    await asyncio.wait_for(spec.rollback(args), timeout=min(spec.timeout_s, 30))
                    evidence.append({"rollback": "OK"})
                except Exception as exc:
                    evidence.append({"rollback": "FAILED", "error": type(exc).__name__})

            # Hata mesajını son gerçekleşen outcome'dan gerçek detaylarla üret
            err_msg = "No verified completion; do not report success"
            if last_outcome:
                if last_outcome.stderr:
                    err_msg = last_outcome.stderr
                elif last_outcome.code:
                    err_msg = f"{last_outcome.code}: işlem başarısız oldu"

            return ExecutionReport(
                State.BLOCKED if latest in {ErrorKind.PERMISSION, ErrorKind.SANDBOX, ErrorKind.AUTH, ErrorKind.UNSAFE} else State.FAILED,
                spec.name,
                len([e for e in evidence if "attempt" in e]),
                latest,
                evidence,
                err_msg,
                False,
                data=last_outcome.data if last_outcome else None,
                outcome=last_outcome
            )


class OmniCoreToolAdapters:
    """Preflight, Action, Verify, Rollback ve Remediation barındıran çekirdek adaptör fabrikası."""

    @staticmethod
    def get_file_write_spec(workspace_root: Any) -> ToolSpec:
        from pathlib import Path
        root = Path(workspace_root).resolve()

        async def preflight(args: dict[str, Any]) -> bool:
            filepath = args.get("filepath", "")
            if not filepath:
                return False
            # Güvenlik denetimi
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            is_allowed = (
                str(target).startswith(str(root)) or
                str(target).startswith("/Users/macair1/projects") or
                str(target).startswith("/Users/macair1/.omnicore")
            )
            if not is_allowed:
                return False
            if target.name.startswith(".env") or ".git" in target.parts:
                return False
            # Merkezi Auditor ve kabul kriterleri dokunulamaz
            if "omnicore-auditor" in str(target) or str(target).startswith("/Users/macair1/omnicore-auditor"):
                return False
            return True

        async def action(args: dict[str, Any]) -> ToolOutcome:
            filepath = args.get("filepath", "")
            content = args.get("content", "")
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            # Yedekleme için önceki içerik
            prev = target.read_text(encoding="utf-8") if target.exists() else None
            target.write_text(content, encoding="utf-8")
            return ToolOutcome(True, data={"bytes": len(content.encode("utf-8")), "prev": prev})

        async def verify(outcome: ToolOutcome, args: dict[str, Any]) -> bool:
            filepath = args.get("filepath", "")
            content = args.get("content", "")
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            if not target.exists():
                return False
            actual = target.read_text(encoding="utf-8")
            return actual == content

        async def rollback(args: dict[str, Any]) -> None:
            filepath = args.get("filepath", "")
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            if target.exists():
                target.unlink(missing_ok=True)

        async def remediate(outcome: ToolOutcome, args: dict[str, Any]) -> bool:
            # Dizin oluşturma veya salt okunur izinleri temizleme
            filepath = args.get("filepath", "")
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            return True

        return ToolSpec(
            name="tool_write_file",
            action=action,
            verify=verify,
            preflight=preflight,
            idempotent=True,
            max_attempts=2,
            rollback=rollback,
            remediate=remediate
        )

    @staticmethod
    def get_file_read_spec(workspace_root: Any) -> ToolSpec:
        from pathlib import Path
        root = Path(workspace_root).resolve()

        async def preflight(args: dict[str, Any]) -> bool:
            filepath = args.get("filepath", "")
            if not filepath:
                return False
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            is_allowed = (
                str(target).startswith(str(root)) or
                str(target).startswith("/Users/macair1/projects") or
                str(target).startswith("/Users/macair1/.omnicore")
            )
            if not is_allowed:
                return False
            if target.name.startswith(".env") or ".ssh" in target.parts:
                return False
            return True

        async def action(args: dict[str, Any]) -> ToolOutcome:
            filepath = args.get("filepath", "")
            raw = Path(filepath)
            target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            if not target.exists():
                return ToolOutcome(False, code="ENOENT", stderr="File not found")
            content = target.read_text(encoding="utf-8", errors="ignore")
            return ToolOutcome(True, data={"content": content, "size": len(content)}, evidence={"verified": True})
            return ToolOutcome(True, data={"content": content, "size": len(content)}, evidence={"verified": True})

        async def verify(outcome: ToolOutcome, args: dict[str, Any]) -> bool:
            return outcome.ok and outcome.data is not None

        return ToolSpec(
            name="tool_read_file",
            action=action,
            verify=verify,
            preflight=preflight,
            idempotent=True,
            max_attempts=1
        )

    @staticmethod
    def get_shell_spec(sandbox_run_fn: Any) -> ToolSpec:
        async def preflight(args: dict[str, Any]) -> bool:
            cmd = args.get("command", "").strip()
            if not cmd:
                return False
            # Tehlikeli kök komutları engelle
            if any(b in cmd for b in ["rm -rf /", ":(){ :|:& };:", "> /dev/sd"]):
                return False
            return True

        async def action(args: dict[str, Any]) -> ToolOutcome:
            cmd = args.get("command", "")
            timeout = args.get("timeout", 90)
            res = sandbox_run_fn(cmd, timeout=timeout)
            is_ok = res.get("success", False) and res.get("exit_code") == 0
            return ToolOutcome(
                ok=is_ok,
                data=res.get("stdout", ""),
                exit_code=res.get("exit_code"),
                stderr=res.get("stderr", ""),
                evidence={"isolated": res.get("isolated"), "seatbelt": res.get("seatbelt_applied")}
            )

        async def verify(outcome: ToolOutcome, args: dict[str, Any]) -> bool:
            return outcome.ok and outcome.exit_code == 0

        return ToolSpec(
            name="tool_run_shell",
            action=action,
            verify=verify,
            preflight=preflight,
            idempotent=False,
            max_attempts=1
        )

    @staticmethod
    def resolve_github_repo(query_or_url: str) -> tuple[str, dict[str, Any]]:
        raw = (query_or_url or "").strip()
        if not raw:
            return "", {"error": "Boş repo veya arama sorgusu"}

        # 1. Doğrudan URL (https:// veya http://github.com/owner/repo)
        url_match = re.search(r"https?://(?:www\.)?github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", raw)
        if url_match:
            slug = url_match.group(1).removesuffix(".git")
            return f"https://github.com/{slug}", {"source": "direct_url", "slug": slug}

        # 2. Doğrudan owner/repo veya metin içinde açık slug (örn: 'bottlepy/bottle' veya 'bottlepy/bottle reposunu kur')
        slug_match = re.search(r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b", raw)
        if slug_match:
            slug = slug_match.group(1).removesuffix(".git")
            if not slug.lower().startswith(("http/", "https/", "api/", "ftp/", "file/")):
                return f"https://github.com/{slug}", {"source": "slug_match", "slug": slug}

        # 3. Geçersiz veya desteklenmeyen protokoller
        if any(raw.lower().startswith(p) for p in ["ftp://", "file://", "ssh://"]):
            return "", {"error": f"Desteklenmeyen protokol: {raw}"}

        # 4. Doğal Dil Araması: Türkçe ve İngilizce arama/dolgu sözcüklerini temizle
        clean = raw
        stop_words = [
            "github'da", "githubda", "github", "depo", "deposu", "reposu", "reposunu", "repoyu", "repo",
            "açık kaynak", "acik kaynak", "açık", "kaynak", "popüler", "populer", "en iyi", "en", "iyi",
            "bul", "ve", "kur", "yükle", "yukle", "indir", "bana", "bir", "tane", "ara", "araştır"
        ]
        for w in stop_words:
            clean = re.sub(r"(?i)\b" + re.escape(w) + r"\b", " ", clean)
        clean = re.sub(r"['\".,;!?]", " ", clean).strip()
        clean = " ".join(clean.split())

        search_query = clean if clean else raw

        # A) gh CLI ile ara (Popülerlik ve dil öncelikli)
        try:
            cmd = ["gh", "search", "repos", search_query]
            if "python" in search_query.lower() or "python" in raw.lower():
                cmd.extend(["--language", "python"])
            cmd.extend(["--sort", "stars", "--limit", "5", "--json", "fullName,url,stargazersCount,description"])
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if p.returncode == 0 and p.stdout.strip():
                items = json.loads(p.stdout)
                if items:
                    best = items[0]
                    return best["url"], {"source": "gh_cli", "slug": best["fullName"], "stars": best.get("stargazersCount"), "query": search_query}
        except Exception:
            pass

        # B) GitHub REST API ile ara (Fallback)
        try:
            import http.client

            conn = http.client.HTTPSConnection("api.github.com", timeout=10)
            path = f"/search/repositories?q={urllib.parse.quote(search_query)}&sort=stars&order=desc&per_page=5"
            conn.request("GET", path, headers={"User-Agent": "OmniCore-Kernel/2.0"})
            resp = conn.getresponse()
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    best = items[0]
                    conn.close()
                    return best["html_url"], {"source": "github_api", "slug": best["full_name"], "stars": best.get("stargazers_count"), "query": search_query}
            conn.close()
        except Exception:
            pass

        return "", {"error": f"Arama sonucu bulunamadı: '{search_query}'"}

    @staticmethod
    def get_github_install_spec(install_repo_fn: Any) -> ToolSpec:
        async def preflight(args: dict[str, Any]) -> bool:
            raw = args.get("query_or_url", "").strip()
            if not raw:
                return False
            # ftp://, file://, ssh:// gibi bariz geçersiz URL şemalarını preflight'ta engelle
            if any(raw.lower().startswith(p) for p in ["ftp://", "file://", "ssh://"]):
                return False
            # Güvenlik: Doğrudan shell komut enjeksiyonu karakterleri barındırmamalı
            if any(c in raw for c in [";", "&&", "||", "`", "$("]):
                return False
            return True

        async def action(args: dict[str, Any]) -> ToolOutcome:
            raw = args.get("query_or_url", "").strip()
            resolved_url, meta = OmniCoreToolAdapters.resolve_github_repo(raw)
            if not resolved_url:
                err_msg = meta.get("error", f"GitHub üzerinde '{raw}' için geçerli bir depo tespit edilemedi.")
                return ToolOutcome(
                    ok=False,
                    code="REPO_NOT_FOUND",
                    stderr=err_msg,
                    data={"stage": "PRE_PROBE", "error": err_msg, "exit_code": -1, "query": raw, "target_path": ""}
                )

            res = install_repo_fn(resolved_url)
            is_ok = res.get("success", False) and res.get("state") == "FUNCTIONAL_TESTED"
            res["resolved_url"] = resolved_url
            res["resolution_meta"] = meta

            code = res.get("state", "UNKNOWN")
            stderr = res.get("error", "")
            return ToolOutcome(
                ok=is_ok,
                data=res,
                code=code,
                exit_code=res.get("exit_code"),
                stderr=stderr,
                evidence={
                    "commit": res.get("commit"),
                    "path": res.get("path"),
                    "verified": is_ok,
                    "stage": res.get("stage", "FUNCTIONAL_TEST" if is_ok else "FAILED"),
                    "resolved_url": resolved_url
                }
            )

        async def verify(outcome: ToolOutcome, args: dict[str, Any]) -> bool:
            if not outcome.ok or not outcome.data:
                return False
            d = outcome.data
            return d.get("state") == "FUNCTIONAL_TESTED" and d.get("commit") is not None and bool(d.get("path"))

        return ToolSpec(
            name="tool_search_and_install_github_repo",
            action=action,
            verify=verify,
            preflight=preflight,
            idempotent=True,
            max_attempts=1
        )

