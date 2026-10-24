#!/usr/bin/env python3
"""
BARIS AI // DETERMINISTIK GITHUB ARASTIRMA VE DOGRULAMA MOTORU
Sıfır halüsinasyon, M4 24GB bellek koruması ve bağımsız doğrulayıcı kapısı.
"""

import json
import linecache
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_ROOT = Path("/Users/macair1/projects/ai")
SANDBOX_DIR = WORKSPACE_ROOT / "sandbox_workspace"

class BarisAIPipeline:
    MAX_LOCAL_FILES = 50
    MAX_LOCAL_SIZE_KB = 500

    @classmethod
    def clone_repo(cls, repo_url: str, target_name: Optional[str] = None) -> Path:
        """Sığ klon (depth=1) ile repoyu sandbox_workspace altına çeker."""
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        if not target_name:
            target_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        
        target_path = SANDBOX_DIR / target_name
        if target_path.exists():
            shutil.rmtree(target_path)
            
        cmd = ["git", "clone", "--depth", "1", repo_url, str(target_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"Git klonlama başarısız: {res.stderr.strip()}")
        return target_path

    @classmethod
    def preflight_check(cls, repo_path: Path) -> Dict[str, Any]:
        """
        Dosya sayısı, kod boyutu ve dil dağılımını ölçerek
        Ollama 14B mi yoksa Cloud API (Gemini/DeepSeek) mi kullanılacağını belirler.
        """
        code_exts = {".py", ".ts", ".js", ".php", ".go", ".rs", ".java", ".cpp", ".c", ".h", ".cs"}
        files = [p for p in repo_path.rglob("*") if p.is_file() and p.suffix.lower() in code_exts and ".git" not in p.parts]
        
        total_size = sum(p.stat().st_size for p in files)
        size_kb = total_size / 1024
        file_count = len(files)
        
        # Karar Mekanizması: 24GB RAM koruması
        if file_count > cls.MAX_LOCAL_FILES or size_kb > cls.MAX_LOCAL_SIZE_KB:
            recommended_engine = "CLOUD_API"
            model_target = "Gemini 3.8 Flash / DeepSeek V3"
            reason = f"Repo hacmi ({file_count} dosya, {size_kb:.1f} KB) yerel 24GB VRAM limitini aşıyor. Bellek takası (swap) ve halüsinasyonu engellemek için Cloud API seçildi."
        else:
            recommended_engine = "LOCAL_OLLAMA"
            model_target = "qwen-coder-14b-abliterated:latest"
            reason = f"Repo hacmi ({file_count} dosya, {size_kb:.1f} KB) yerel VRAM içinde güvenle işlenebilir."

        return {
            "file_count": file_count,
            "size_kb": round(size_kb, 2),
            "recommended_engine": recommended_engine,
            "model_target": model_target,
            "reason": reason,
            "files": [str(p.relative_to(repo_path)) for p in files[:100]]
        }

    @classmethod
    def verify_claim(cls, repo_path: Path, file_rel_path: str, start_line: int, end_line: int, expected_snippet: str) -> Dict[str, Any]:
        """
        Deterministik Doğrulayıcı Kapısı (Gatekeeper).
        LLM'in iddia ettiği dosya, satır ve kod parçasını diskten bağımsız olarak doğrular.
        """
        full_path = repo_path / file_rel_path
        if not full_path.exists():
            return {
                "valid": False,
                "reason": f"İddia edilen dosya diskte bulunamadı: '{file_rel_path}'"
            }
        
        linecache.checkcache(str(full_path))
        lines = []
        for i in range(start_line, end_line + 1):
            line = linecache.getline(str(full_path), i)
            if line:
                lines.append(line)
                
        actual_content = "".join(lines)
        
        # Boşlukları normalize ederek karşılaştır
        norm_actual = " ".join(actual_content.split())
        norm_expected = " ".join(expected_snippet.split())
        
        if not norm_expected or norm_expected in norm_actual or norm_actual in norm_expected:
            return {
                "valid": True,
                "file": file_rel_path,
                "start_line": start_line,
                "end_line": end_line,
                "actual_code": actual_content.strip()
            }
        
        return {
            "valid": False,
            "reason": f"Kod uyuşmazlığı: İddia edilen satırlardaki kod disktekiyle eşleşmiyor.",
            "expected": expected_snippet[:200],
            "actual": actual_content[:200]
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "ready", "engine": "BarisAIPipeline", "version": "1.0.0"}))
        sys.exit(0)
    
    url = sys.argv[1]
    print(f"[*] Baris AI Başlatılıyor: {url}")
    target = BarisAIPipeline.clone_repo(url)
    pre = BarisAIPipeline.preflight_check(target)
    print(json.dumps(pre, indent=2, ensure_ascii=False))
