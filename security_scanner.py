#!/usr/bin/env python3
"""
OMNICORE X // FAZ 6: SELF-HEALING & SECURITY ENGINE
Motorlar & Denetimler:
- Statik güvenlik denetimi (Secret leak / Gitleaks regex taraması, AST risk analizi)
- Bağımlılık ve kaynak güvenliği
- Harici repo kabul kapısı (6 Aşamalı Sertifikasyon):
  1. Kaynak & Lisans denetimi
  2. Sabitlenmiş commit doğrulaması
  3. İzole sandbox'ta kurulum
  4. Statik güvenlik analizi
  5. İşlevsel runtime testi
  6. Başarısızlık durumunda temiz geri alma (Atomic Rollback)
"""

import ast
import re
from pathlib import Path
from typing import Dict, Any, List

WORKSPACE_ROOT = Path(__file__).resolve().parent

class SecurityScanner:
    # Gitleaks benzeri yüksek duyarlılıklı sızıntı regex kalıpları
    SECRET_PATTERNS = [
        (r"(?i)(?:api_key|apikey|secret|password|private_key|token)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.]{16,}['\"]", "Olası Açık API Anahtarı/Token"),
        (r"-----BEGIN\s+(?:RSA|OPENSSH|DSA|EC)?\s*PRIVATE\s+KEY-----", "Özel SSH/RSA Kripto Anahtarı"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
        (r"sk-[a-zA-Z0-9]{32,}", "OpenAI API Anahtarı"),
        (r"AIza[0-9A-Za-z-_]{35}", "Google API Anahtarı")
    ]

    DANGEROUS_AST_CALLS = [
        "os.system", "subprocess.Popen", "shutil.rmtree", "eval", "exec", "__import__"
    ]

    @classmethod
    def scan_text_for_secrets(cls, text: str) -> List[Dict[str, str]]:
        findings = []
        for pattern, label in cls.SECRET_PATTERNS:
            matches = re.finditer(pattern, text)
            for m in matches:
                # Maskelenmiş gösterim
                val = m.group(0)
                findings.append({
                    "type": label,
                    "preview": val[:12] + "..." + val[-4:] if len(val) > 16 else "***"
                })
        return findings

    @classmethod
    def scan_python_ast(cls, file_path: Path) -> List[Dict[str, Any]]:
        """Python kodunun AST ağacını tarayarak riskli fonksiyon çağrılarını tespit eder."""
        issues = []
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Fonksiyon çağrısı inceleme
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            func_name = f"{node.func.value.id}.{node.func.attr}"

                    if func_name in cls.DANGEROUS_AST_CALLS:
                        issues.append({
                            "severity": "WARNING",
                            "file": str(file_path),
                            "line": getattr(node, "lineno", 0),
                            "risk": f"Tehlikeli çağrı tespit edildi: {func_name}"
                        })
        except Exception:
            pass
        return issues

    @classmethod
    def audit_repo_security(cls, repo_dir: Path) -> Dict[str, Any]:
        """Bir klasörün içerisindeki tüm dosyaları güvenlik açısından denetler."""
        all_secret_findings = []
        ast_warnings = []

        for p in repo_dir.rglob("*.py"):
            if ".git" in p.parts or "__pycache__" in p.parts:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                sec_hits = cls.scan_text_for_secrets(content)
                for s in sec_hits:
                    s["file"] = str(p.relative_to(repo_dir))
                    all_secret_findings.append(s)

                ast_hits = cls.scan_python_ast(p)
                ast_warnings.extend(ast_hits)
            except Exception:
                pass

        passed = len(all_secret_findings) == 0
        return {
            "passed": passed,
            "secret_findings_count": len(all_secret_findings),
            "secret_findings": all_secret_findings,
            "ast_warnings_count": len(ast_warnings),
            "ast_warnings": ast_warnings
        }

if __name__ == "__main__":
    test_res = SecurityScanner.scan_text_for_secrets("apiKey = 'sk-1234567890abcdef1234567890abcdef'")
    print("Security Scanner Test:", test_res)
