#!/usr/bin/env python3
"""
Barış AI Installed Engines Bridge & Unified Execution Orchestrator
Sistemdeki tüm kurulu siber güvenlik, araştırma, kod denetimi ve GitHub motorlarını
tek bir standart arabirimde toplayıp doğrudan görev motoruna bağlayan köprü.
"""

import json
import os
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional


class InstalledEnginesBridge:
    """Kurulu motorlar yönetim ve çalıştırma köprüsü."""

    _phishing_cache: Optional[Dict[str, Any]] = None

    @classmethod
    def find_binary(cls, name: str, fallback_paths: Optional[List[str]] = None) -> Optional[str]:
        system_bin = shutil.which(name)
        if system_bin:
            return system_bin
        for p in (fallback_paths or []):
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p
        return None

    @classmethod
    def _resolve_target(cls, target_path: str, fallback: Optional[str] = None) -> Path:
        raw = (target_path or "").strip()
        if not raw or "your/project" in raw or raw in {".", "proje", "mevcut"}:
            return Path(fallback or os.getcwd()).resolve()
        p = Path(raw).resolve()
        if not p.exists() and fallback:
            return Path(fallback).resolve()
        return p

    @classmethod
    def scan_secrets(cls, target_path: str, max_findings: int = 15, fallback_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Gitleaks motorunu kullanarak hedef dosya veya dizinde gizli anahtar,
        token, şifre ve kimlik sızıntılarını tarar.
        """
        gitleaks_bin = cls.find_binary("gitleaks", ["/opt/homebrew/bin/gitleaks", "/usr/local/bin/gitleaks"])
        if not gitleaks_bin:
            return {"success": False, "error": "Gitleaks motoru sistemde bulunamadı."}

        target = cls._resolve_target(target_path, fallback_dir)
        if not target.exists():
            return {"success": False, "error": f"Hedef yol bulunamadı: {target_path}"}

        temp_report = f"/tmp/gitleaks_{os.getpid()}_{hash(str(target))}.json"
        try:
            cmd = [
                gitleaks_bin, "detect", "--no-git",
                "--source", str(target),
                "--report-format", "json",
                "--report-path", temp_report,
                "--exit-code", "0"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            
            findings = []
            if os.path.exists(temp_report):
                try:
                    with open(temp_report, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    for item in raw_data[:max_findings]:
                        findings.append({
                            "description": item.get("Description", "Gizli Veri"),
                            "file": os.path.relpath(item.get("File", ""), str(target)),
                            "start_line": item.get("StartLine", 0),
                            "match_masked": (item.get("Match", "")[:4] + "***" + item.get("Match", "")[-4:]) if len(item.get("Match", "")) > 8 else "***",
                            "rule_id": item.get("RuleID", "")
                        })
                finally:
                    try:
                        os.unlink(temp_report)
                    except Exception:
                        pass

            return {
                "success": True,
                "engine": "Gitleaks v8.30.1",
                "target": str(target),
                "leaks_count": len(findings),
                "findings": findings
            }
        except Exception as exc:
            return {"success": False, "error": f"Gitleaks tarama hatası: {str(exc)}"}

    @classmethod
    def scan_vulnerabilities(cls, target_path: str, max_findings: int = 15, fallback_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Google OSV-Scanner ve Aqua Trivy motorlarını kullanarak
        açık kaynak bağımlılık zafiyetlerini (CVE) tarar.
        """
        osv_bin = cls.find_binary("osv-scanner", [
            "/Users/macair1/projects/ai/installed_engines/google--osv-scanner/bin/osv-scanner",
            "/opt/homebrew/bin/osv-scanner"
        ])
        trivy_bin = cls.find_binary("trivy", [
            "/Users/macair1/projects/ai/installed_engines/aquasecurity--trivy/bin/trivy",
            "/opt/homebrew/bin/trivy"
        ])

        target = cls._resolve_target(target_path, fallback_dir)
        if not target.exists():
            return {"success": False, "error": f"Hedef yol bulunamadı: {target_path}"}

        findings = []
        engine_used = "Bilinmiyor"

        # 1. OSV-Scanner Denemesi
        if osv_bin:
            try:
                cmd = [osv_bin, "-r", str(target), "--format", "json"]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if res.stdout:
                    try:
                        data = json.loads(res.stdout)
                        results = data.get("results", [])
                        for r in results:
                            for pkg in r.get("packages", []):
                                for vuln in pkg.get("vulnerabilities", []):
                                    findings.append({
                                        "id": vuln.get("id"),
                                        "package": pkg.get("package", {}).get("name"),
                                        "version": pkg.get("package", {}).get("version"),
                                        "summary": vuln.get("summary", "Güvenlik zafiyeti tespit edildi.")
                                    })
                        engine_used = "Google OSV-Scanner v2.7.0"
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. Trivy Denemesi (Eğer OSV boşsa veya Trivy varsa)
        if not findings and trivy_bin:
            try:
                cmd = [trivy_bin, "fs", str(target), "--format", "json"]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if res.stdout:
                    try:
                        data = json.loads(res.stdout)
                        for r in data.get("Results", []):
                            for v in r.get("Vulnerabilities", []):
                                findings.append({
                                    "id": v.get("VulnerabilityID"),
                                    "package": v.get("PkgName"),
                                    "severity": v.get("Severity"),
                                    "summary": v.get("Title", "Zafiyet")
                                })
                        engine_used = "Aqua Trivy Engine"
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            "success": True,
            "engine": engine_used,
            "target": str(target),
            "vulnerabilities_count": len(findings),
            "findings": findings[:max_findings]
        }

    @classmethod
    def audit_smart_contract(cls, target_path: str, fallback_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Crytic Slither motorunu kullanarak Solidity akıllı sözleşmelerini
        güvenlik açıklarına ve reentrancy açıklarına karşı analiz eder.
        """
        slither_bin = cls.find_binary("slither", ["/opt/homebrew/bin/slither"])
        if not slither_bin:
            return {"success": False, "error": "Slither motoru sistemde bulunamadı."}

        target = cls._resolve_target(target_path, fallback_dir)
        if not target.exists():
            return {"success": False, "error": f"Hedef dosya bulunamadı: {target_path}"}

        if target.is_dir():
            has_sol = any(target.glob("*.sol")) or any(target.glob("**/*.sol"))
            if not has_sol:
                return {
                    "success": True,
                    "engine": "Crytic Slither v0.11.6",
                    "contract": str(target),
                    "issues_count": 0,
                    "findings": [],
                    "warning": f"Hedef dizinde ({target.name}) (.sol) uzantılı Solidity akıllı sözleşmesi bulunamadı."
                }

        try:
            cmd = [slither_bin, str(target), "--json", "-"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=35)
            findings = []
            if res.stdout:
                try:
                    data = json.loads(res.stdout)
                    detectors = data.get("results", {}).get("detectors", [])
                    for d in detectors[:10]:
                        findings.append({
                            "check": d.get("check"),
                            "impact": d.get("impact"),
                            "confidence": d.get("confidence"),
                            "description": d.get("description", "").split("\n")[0]
                        })
                except Exception:
                    pass
            return {
                "success": True,
                "engine": "Crytic Slither v0.11.6",
                "contract": str(target),
                "issues_count": len(findings),
                "findings": findings
            }
        except Exception as exc:
            return {"success": False, "error": f"Slither analizi başarısız: {str(exc)}"}

    @classmethod
    def scan_phishing_domain(cls, domain_or_url: str) -> Dict[str, Any]:
        """
        MetaMask eth-phishing-detect veri tabanını kullanarak belirtilen
        domain veya URL'nin bilinen bir phishing/sahte cüzdan olup olmadığını doğrular.
        """
        raw = domain_or_url.strip()
        if "://" not in raw:
            raw = "http://" + raw
        parsed = urllib.parse.urlparse(raw)
        domain = (parsed.netloc or parsed.path).split(":")[0].lower()

        # Veritabanını önbelleğe al
        if cls._phishing_cache is None:
            db_path = Path("/Users/macair1/projects/ai/installed_engines/MetaMask--eth-phishing-detect/src/config.json")
            if db_path.exists():
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    cls._phishing_cache = {
                        "blacklist": set(cfg.get("blacklist", [])),
                        "whitelist": set(cfg.get("whitelist", [])),
                        "fuzzylist": set(cfg.get("fuzzylist", []))
                    }
                except Exception:
                    cls._phishing_cache = {"blacklist": set(), "whitelist": set(), "fuzzylist": set()}
            else:
                cls._phishing_cache = {"blacklist": set(), "whitelist": set(), "fuzzylist": set()}

        cache = cls._phishing_cache
        is_whitelisted = domain in cache["whitelist"]
        is_blacklisted = domain in cache["blacklist"]
        
        # Subdomain kontrolü
        if not is_blacklisted:
            parts = domain.split(".")
            for i in range(1, len(parts) - 1):
                parent = ".".join(parts[i:])
                if parent in cache["blacklist"]:
                    is_blacklisted = True
                    break

        return {
            "success": True,
            "engine": "MetaMask Phishing Detection v2",
            "domain": domain,
            "is_phishing": is_blacklisted and not is_whitelisted,
            "status": "🚨 TEHLİKELİ (Zararlı / Phishing)" if (is_blacklisted and not is_whitelisted) else ("✅ GÜVENLİ (Beyaz Liste)" if is_whitelisted else "ℹ️ NÖTR (Bilinen Tehdit Kaydı Yok)"),
            "total_threat_signatures": len(cache["blacklist"])
        }

    @classmethod
    def scan_trufflehog(cls, target_path: str, max_findings: int = 15, fallback_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        TruffleHog motorunu kullanarak hedef dizinde doğrulanmış credential ve anahtar sızıntılarını tarar.
        """
        th_bin = cls.find_binary("trufflehog", ["/opt/homebrew/bin/trufflehog", "/usr/local/bin/trufflehog"])
        if not th_bin:
            return {"success": False, "error": "TruffleHog motoru sistemde bulunamadı."}

        target = cls._resolve_target(target_path, fallback_dir)
        if not target.exists():
            return {"success": False, "error": f"Hedef yol bulunamadı: {target_path}"}

        try:
            cmd = [th_bin, "filesystem", str(target), "--json", "--no-verification", "--no-update"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            
            findings = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    raw_src = data.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {})
                    findings.append({
                        "detector_name": data.get("DetectorName", "Credential"),
                        "file": raw_src.get("file", ""),
                        "line": raw_src.get("line", 0),
                        "verified": data.get("Verified", False),
                        "raw_masked": (data.get("Raw", "")[:4] + "***") if data.get("Raw") else "***"
                    })
                    if len(findings) >= max_findings:
                        break
                except Exception:
                    continue

            return {
                "success": True,
                "engine": "TruffleHog v3.99.6",
                "target": str(target),
                "leaks_count": len(findings),
                "findings": findings
            }
        except Exception as exc:
            return {"success": False, "error": f"TruffleHog tarama hatası: {str(exc)}"}

    @classmethod
    def scan_repo_scorecard(cls, repo_name: str) -> Dict[str, Any]:
        """
        OpenSSF Scorecard motorunu kullanarak belirtilen GitHub reposunun tedarik zinciri ve güvenlik sağlığını puanlar.
        """
        sc_bin = cls.find_binary("scorecard", ["/opt/homebrew/bin/scorecard", "/usr/local/bin/scorecard"])
        if not sc_bin:
            return {"success": False, "error": "OpenSSF Scorecard motoru sistemde bulunamadı."}

        repo = (repo_name or "").strip().replace("https://github.com/", "").strip("/")
        if not repo or "/" not in repo:
            return {"success": False, "error": f"Geçerli bir GitHub repo yolu (owner/repo) belirtilmelidir: {repo_name}"}

        try:
            cmd = [sc_bin, f"--repo=github.com/{repo}", "--format=json"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
            
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                score = data.get("score", 0.0)
                checks = []
                for c in data.get("checks", []):
                    checks.append({
                        "name": c.get("name"),
                        "score": c.get("score"),
                        "reason": c.get("reason")
                    })
                return {
                    "success": True,
                    "engine": "OpenSSF Scorecard v5.6.0",
                    "repo": repo,
                    "overall_score": score,
                    "checks_count": len(checks),
                    "checks": checks[:10]
                }
            return {
                "success": False,
                "engine": "OpenSSF Scorecard v5.6.0",
                "repo": repo,
                "error": res.stderr.strip() or "Scorecard raporu üretilemedi."
            }
        except Exception as exc:
            return {"success": False, "error": f"Scorecard çalıştırma hatası: {str(exc)}"}

    @classmethod
    def fuzz_smart_contract(cls, contract_path: str, fallback_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Crytic Echidna fuzzer motorunu kullanarak akıllı sözleşme güvenlik ve invariant denetimi yapar.
        """
        echidna_bin = cls.find_binary("echidna", ["/opt/homebrew/bin/echidna", "/usr/local/bin/echidna"])
        if not echidna_bin:
            return {"success": False, "error": "Crytic Echidna fuzzer sistemde bulunamadı."}

        target = cls._resolve_target(contract_path, fallback_dir)
        sol_files = []
        if target.is_file() and target.suffix == ".sol":
            sol_files = [target]
        elif target.is_dir():
            sol_files = list(target.glob("*.sol"))

        if not sol_files:
            return {
                "success": True,
                "engine": "Crytic Echidna v2.3.3",
                "contract": str(target),
                "fuzz_tests_count": 0,
                "warning": f"Hedef dizinde (.sol) uzantılı akıllı sözleşme bulunamadı: {target}",
                "failures": []
            }

        try:
            cmd = [echidna_bin, str(sol_files[0]), "--format", "json", "--test-limit", "1000"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=40)
            
            failures = []
            if res.stdout.strip():
                try:
                    data = json.loads(res.stdout)
                    for k, v in data.items():
                        if isinstance(v, dict) and v.get("status") == "failed":
                            failures.append({"property": k, "error": v.get("error")})
                except Exception:
                    pass

            return {
                "success": True,
                "engine": "Crytic Echidna v2.3.3",
                "contract": str(sol_files[0].name),
                "failures_count": len(failures),
                "failures": failures
            }
        except Exception as exc:
            return {"success": False, "error": f"Echidna fuzzing hatası: {str(exc)}"}

    @classmethod
    def get_all_engines_health(cls) -> Dict[str, Any]:
        """
        Sistemdeki tüm canlı motorların durumunu, dosya yollarını ve yanıt hızlarını döndürür.
        """
        engines = {}
        
        # Gitleaks
        t0 = time.perf_counter()
        gl = cls.find_binary("gitleaks", ["/opt/homebrew/bin/gitleaks"])
        engines["Gitleaks (Secret Scanner)"] = {
            "available": bool(gl),
            "binary": gl or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # TruffleHog
        t0 = time.perf_counter()
        th = cls.find_binary("trufflehog", ["/opt/homebrew/bin/trufflehog"])
        engines["TruffleHog (Credential Hunter)"] = {
            "available": bool(th),
            "binary": th or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # Google OSV-Scanner
        t0 = time.perf_counter()
        osv = cls.find_binary("osv-scanner", [
            "/Users/macair1/projects/ai/installed_engines/google--osv-scanner/bin/osv-scanner",
            "/opt/homebrew/bin/osv-scanner"
        ])
        engines["Google OSV-Scanner (CVE)"] = {
            "available": bool(osv),
            "binary": osv or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # Aqua Trivy
        t0 = time.perf_counter()
        trivy = cls.find_binary("trivy", [
            "/Users/macair1/projects/ai/installed_engines/aquasecurity--trivy/bin/trivy",
            "/opt/homebrew/bin/trivy"
        ])
        engines["Aqua Trivy (Vulnerabilities)"] = {
            "available": bool(trivy),
            "binary": trivy or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # OpenSSF Scorecard
        t0 = time.perf_counter()
        sc = cls.find_binary("scorecard", ["/opt/homebrew/bin/scorecard"])
        engines["OpenSSF Scorecard (Supply Chain)"] = {
            "available": bool(sc),
            "binary": sc or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # Crytic Slither
        t0 = time.perf_counter()
        slither = cls.find_binary("slither", ["/opt/homebrew/bin/slither"])
        engines["Crytic Slither (Smart Contracts)"] = {
            "available": bool(slither),
            "binary": slither or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # Crytic Echidna
        t0 = time.perf_counter()
        echidna = cls.find_binary("echidna", ["/opt/homebrew/bin/echidna"])
        engines["Crytic Echidna (Contract Fuzzer)"] = {
            "available": bool(echidna),
            "binary": echidna or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # GitHub CLI (gh)
        t0 = time.perf_counter()
        gh = cls.find_binary("gh", ["/opt/homebrew/bin/gh"])
        engines["GitHub Hunter (gh CLI)"] = {
            "available": bool(gh),
            "binary": gh or "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        # MetaMask Phishing DB
        t0 = time.perf_counter()
        db_p = Path("/Users/macair1/projects/ai/installed_engines/MetaMask--eth-phishing-detect/src/config.json")
        engines["MetaMask Eth Phishing Intel"] = {
            "available": db_p.exists(),
            "path": str(db_p) if db_p.exists() else "Bulunamadı",
            "ping_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

        return {
            "success": True,
            "total_engines": len(engines),
            "active_engines": sum(1 for e in engines.values() if e.get("available")),
            "engines": engines
        }
