# tools_inspect.py
import json
import subprocess
import shutil
import os
from typing import List, Optional
from pydantic import BaseModel, Field

class CodeEvidence(BaseModel):
    file_path: str = Field(description="Bulgunun yer aldığı göreceli dosya yolu")
    line_start: int = Field(description="Başlangıç satır numarası")
    line_end: int = Field(description="Bitiş satır numarası")
    matched_snippet: str = Field(description="ast-grep tarafından yakalanan tam kod bloğu")
    rule_or_pattern: str = Field(description="Eşleşen desen veya kural")

class InspectionResult(BaseModel):
    target_repo: str
    total_findings: int
    is_safe: bool
    evidence: List[CodeEvidence] = []
    error: Optional[str] = None

def tool_github_inspect(repo_path: str, pattern: str = None) -> str:
    """
    Belirtilen yerel git reposunda ast-grep ile AST düzeyinde derin tarama yapar.
    Regex yerine Tree-Sitter gramer ağaçlarını kullanır; değişken ve fonksiyon bağlamını korur.
    Pydantic ile doğrulanmış JSON çıktısı döner.
    """
    if not os.path.exists(repo_path):
        res = InspectionResult(
            target_repo=repo_path,
            total_findings=0,
            is_safe=False,
            error=f"Hedef yol mevcut değil: {repo_path}"
        )
        return res.model_dump_json(indent=2)

    ast_grep_bin = shutil.which("ast-grep") or "/opt/homebrew/bin/ast-grep"
    if not os.path.exists(ast_grep_bin):
        res = InspectionResult(
            target_repo=repo_path,
            total_findings=0,
            is_safe=False,
            error="ast-grep binary bulunamadı. Lütfen 'brew install ast-grep' veya 'cargo install ast-grep' çalıştırın."
        )
        return res.model_dump_json(indent=2)

    search_pattern = pattern if pattern else "eval($$$A)"
    cmd = [ast_grep_bin, "run", "-p", search_pattern, "--json", repo_path]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            encoding="utf-8"
        )
        raw_output = proc.stdout.strip()
        
        findings: List[CodeEvidence] = []
        if raw_output:
            try:
                data = json.loads(raw_output)
                if isinstance(data, list):
                    for item in data:
                        rng = item.get("range", {})
                        start_line = rng.get("start", {}).get("line", 1)
                        end_line = rng.get("end", {}).get("line", start_line)
                        fpath = item.get("file", "")
                        if fpath.startswith(repo_path):
                            fpath = os.path.relpath(fpath, repo_path)

                        findings.append(CodeEvidence(
                            file_path=fpath,
                            line_start=start_line,
                            line_end=end_line,
                            matched_snippet=item.get("text", "").strip()[:500],
                            rule_or_pattern=search_pattern
                        ))
            except Exception as pe:
                findings = []

        is_safe = (len(findings) == 0)
        res = InspectionResult(
            target_repo=repo_path,
            total_findings=len(findings),
            is_safe=is_safe,
            evidence=findings
        )
        return res.model_dump_json(indent=2)

    except subprocess.TimeoutExpired:
        res = InspectionResult(
            target_repo=repo_path,
            total_findings=0,
            is_safe=False,
            error="ast-grep analizi zaman aşımına uğradı (30s)."
        )
        return res.model_dump_json(indent=2)
    except Exception as e:
        res = InspectionResult(
            target_repo=repo_path,
            total_findings=0,
            is_safe=False,
            error=f"AST analizi sırasında hata: {str(e)}"
        )
        return res.model_dump_json(indent=2)
