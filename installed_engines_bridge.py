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
from pathlib import Path
from typing import Any, Dict, List, Optional


class InstalledEnginesBridge:
    """Kurulu motorlar yönetim ve çalıştırma köprüsü."""

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
    def scan_secrets(cls, target_path: str, max_findings: int = 15) -> Dict[str, Any]:
        """
        Gitleaks motorunu kullanarak hedef dosya veya dizinde gizli anahtar,
        token, şifre ve kimlik sızıntılarını tarar.
        """
        gitleaks_bin = cls.find_binary("gitleaks", ["/opt/homebrew/bin/gitleaks", "/usr/local/bin/gitleaks"])
        if not gitleaks_bin:
            return {"success": False, "error": "Gitleaks motoru sistemde bulunamadı."}

        target = Path(target_path).resolve()
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
    def scan_vulnerabilities(cls, target_path: str, max_findings: int = 15) -> Dict[str, Any]:
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

        target = Path(target_path).resolve()
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
    def audit_smart_contract(cls, target_path: str) -> Dict[str, Any]:
        """
        Crytic Slither motorunu kullanarak Solidity akıllı sözleşmelerini
        güvenlik açıklarına ve reentrancy açıklarına karşı analiz eder.
        """
        slither_bin = cls.find_binary("slither", ["/opt/homebrew/bin/slither"])
        if not slither_bin:
            return {"success": False, "error": "Slither motoru sistemde bulunamadı."}

        target = Path(target_path).resolve()
        if not target.exists():
            return {"success": False, "error": f"Hedef dosya bulunamadı: {target_path}"}

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
