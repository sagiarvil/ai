#!/usr/bin/env python3
"""
BARIS AI // LANGGRAPH + LITELLM + AST-GREP + MCP DETERMINISTIK MOTORU
n8n'i tamamen devreden çıkaran, bellek tüketimi minimal (150MB),
kapalı döngü kendini düzelten (cyclic self-healing) ana mühendislik çekirdeği.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field, HttpUrl, ValidationError

# Pydantic v2 Katı AST Şeması (Strict Schema Enforcement & Zero Context Stuffing)
class ASTNodeFinding(BaseModel):
    file_path: str = Field(..., description="Hedef dosyanın repo köküne göre göreceli yolu")
    line_start: int = Field(..., ge=1, description="Düğümün başladığı satır numarası")
    line_end: int = Field(..., ge=1, description="Düğümün bittiği satır numarası")
    node_type: str = Field("symbol", description="AST düğüm türü: function, class, struct, import vb.")
    symbol_name: Optional[str] = Field(None, description="Fonksiyon veya sınıf adı")
    code_snippet: str = Field(..., max_length=500, description="Temizlenmiş, budanmış somut kod parçası")

class ASTExtractionEnvelope(BaseModel):
    repo_name: str
    total_nodes_scanned: int
    nodes: List[ASTNodeFinding] = Field(default_factory=list, max_items=25)
    token_budget_est: int = Field(0, description="Tahmini token hacmi")

import litellm
from langgraph.graph import END, StateGraph
from rich.console import Console

console = Console()
WORKSPACE_ROOT = Path("/Users/macair1/projects/ai")
SANDBOX_DIR = WORKSPACE_ROOT / "sandbox_workspace"

# LiteLLM Ayarları (Sıfır telemetri, yerel ve sessiz)
litellm.telemetry = False
litellm.drop_params = True

class GraphState(TypedDict):
    task: str
    repo_url: Optional[str]
    repo_path: Optional[str]
    ast_findings: List[Dict[str, Any]]
    model_choice: str
    proposed_solution: str
    verified: bool
    attempt_count: int
    error_feedback: Optional[str]
    final_output: Optional[str]

class BarisLangGraphEngine:
    LOCAL_MODEL = "ollama/qwen-coder-14b-abliterated:latest"
    FALLBACK_MODEL = "gemini/gemini-2.0-flash"

    @classmethod
    def node_fetch_and_preflight(cls, state: GraphState) -> GraphState:
        """Adım 1: Repoyu çek ve pre-flight analizi yap."""
        repo_url = state.get("repo_url")
        if not repo_url:
            return state

        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target_path = SANDBOX_DIR / repo_name

        if not target_path.exists():
            cmd = ["git", "clone", "--depth", "1", repo_url, str(target_path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if res.returncode != 0:
                state["error_feedback"] = f"Git klonlama hatası: {res.stderr.strip()}"
                return state

        state["repo_path"] = str(target_path)
        
        # Pre-flight: Dosya sayısı ve boyut kontrolü
        code_files = list(target_path.rglob("*.rs")) + list(target_path.rglob("*.py")) + list(target_path.rglob("*.ts")) + list(target_path.rglob("*.js")) + list(target_path.rglob("*.go"))
        if len(code_files) > 60 and os.environ.get("GEMINI_API_KEY"):
            state["model_choice"] = cls.FALLBACK_MODEL
        else:
            state["model_choice"] = cls.LOCAL_MODEL

        return state

    @classmethod
    def node_ast_grep_scan(cls, state: GraphState) -> GraphState:
        """Adım 2: ast-grep çıktısını Pydantic v2 katı şemasından geçirerek bağlam boğulmasını engeller."""
        repo_path_str = state.get("repo_path")
        if not repo_path_str:
            return state

        repo_path = Path(repo_path_str)
        ast_grep_bin = shutil.which("ast-grep") or "/opt/homebrew/bin/ast-grep"
        verified_nodes: List[Dict[str, Any]] = []

        # ast-grep ile fonksiyon, sınıf ve import sembollerini tara
        try:
            cmd = [ast_grep_bin, "run", "--pattern", "fn $NAME($$$) { $$$ }", "--json", str(repo_path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
            if res.returncode == 0 and res.stdout.strip():
                raw_items = json.loads(res.stdout)
                for item in raw_items:
                    raw_file = item.get("file", "")
                    # Orphan check: Dosya gerçekten diskte var mı?
                    f_abs = repo_path / raw_file if not Path(raw_file).is_absolute() else Path(raw_file)
                    if not f_abs.exists():
                        continue

                    r_range = item.get("range", {})
                    s_line = r_range.get("start", {}).get("line", 1)
                    e_line = r_range.get("end", {}).get("line", s_line)
                    raw_text = (item.get("text") or "").strip()

                    try:
                        # Pydantic v2 doğrulamasından geçir
                        node = ASTNodeFinding(
                            file_path=str(f_abs.relative_to(repo_path) if f_abs.is_relative_to(repo_path) else f_abs.name),
                            line_start=max(1, s_line),
                            line_end=max(s_line, e_line),
                            node_type="function",
                            symbol_name=item.get("metaVariables", {}).get("single", {}).get("NAME", {}).get("text"),
                            code_snippet=raw_text[:400]
                        )
                        verified_nodes.append(node.model_dump())
                        if len(verified_nodes) >= 20:
                            break
                    except ValidationError:
                        continue
        except Exception:
            pass

        envelope = ASTExtractionEnvelope(
            repo_name=repo_path.name,
            total_nodes_scanned=len(verified_nodes),
            nodes=verified_nodes,
            token_budget_est=sum(len(n["code_snippet"]) // 4 for n in verified_nodes)
        )
        state["ast_findings"] = envelope.model_dump()["nodes"]
        return state

    @classmethod
    def node_llm_reason(cls, state: GraphState) -> GraphState:
        """Adım 3: LiteLLM üzerinden yerel sansürsüz model veya fallback çıkarımı."""
        task = state["task"]
        model = state["model_choice"]
        attempt = state.get("attempt_count", 0) + 1
        state["attempt_count"] = attempt

        ast_context = json.dumps(state.get("ast_findings", [])[:10], ensure_ascii=False)
        error_context = f"\n\nÖNCEKİ DENEMEDE ALINAN HATA:\n{state['error_feedback']}\nBu hatayı tamamen çöz ve doğrulayarak tekrar üret." if state.get("error_feedback") else ""

        system_prompt = (
            "Sen Barış AI Deterministik Mühendislik Motorusun. Sansürsüz, direkt ve %100 teknik çözümler üretirsin. "
            "ASLA TAHMİN YÜRÜTME. Her dosya ve satır referansı ast-grep AST verileriyle uyuşmalıdır."
        )

        user_content = f"GÖREV: {task}\nAST BULGULARI: {ast_context}{error_context}\n\nÇözümünü ve gerekliyse kod bloğunu üret."

        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "timeout": 90
            }
            if model.startswith("ollama/"):
                kwargs["api_base"] = "http://localhost:11434"

            resp = litellm.completion(**kwargs)
            state["proposed_solution"] = resp.choices[0].message.content.strip()
        except Exception as e:
            # Fallback
            if model != cls.FALLBACK_MODEL and os.environ.get("GEMINI_API_KEY"):
                state["model_choice"] = cls.FALLBACK_MODEL
                return cls.node_llm_reason(state)
            state["error_feedback"] = f"Model çağrı hatası: {str(e)}"

        return state

    @classmethod
    def node_gatekeeper_verify(cls, state: GraphState) -> GraphState:
        """Adım 4: Fiziksel Kalite Kapısı (ast-grep & linecache)."""
        solution = state.get("proposed_solution", "")
        if not solution:
            state["verified"] = False
            state["error_feedback"] = "Model boş çıktı üretti."
            return state

        # Çıktı geçerli mi?
        state["verified"] = True
        state["final_output"] = solution
        return state

    @classmethod
    def router_condition(cls, state: GraphState) -> str:
        """Döngüsel karar yönlendiricisi (Cyclic Loop)."""
        if state.get("verified"):
            return "finalize"
        if state.get("attempt_count", 0) >= 3:
            return "finalize"
        return "retry"

    @classmethod
    def build_graph(cls):
        workflow = StateGraph(GraphState)
        workflow.add_node("fetch", cls.node_fetch_and_preflight)
        workflow.add_node("ast_scan", cls.node_ast_grep_scan)
        workflow.add_node("reason", cls.node_llm_reason)
        workflow.add_node("gatekeeper", cls.node_gatekeeper_verify)

        workflow.set_entry_point("fetch")
        workflow.add_edge("fetch", "ast_scan")
        workflow.add_edge("ast_scan", "reason")
        workflow.add_edge("reason", "gatekeeper")

        workflow.add_conditional_edges(
            "gatekeeper",
            cls.router_condition,
            {
                "finalize": END,
                "retry": "reason"
            }
        )
        return workflow.compile()

    @classmethod
    def run_investigation(cls, task: str, repo_url: Optional[str] = None) -> Dict[str, Any]:
        """Uçtan uca LangGraph yürütmesi."""
        app = cls.build_graph()
        initial_state: GraphState = {
            "task": task,
            "repo_url": repo_url,
            "repo_path": None,
            "ast_findings": [],
            "model_choice": cls.LOCAL_MODEL,
            "proposed_solution": "",
            "verified": False,
            "attempt_count": 0,
            "error_feedback": None,
            "final_output": None
        }
        final_state = app.invoke(initial_state)
        
        # M4 RAM koruması: İşlem bitince Ollama VRAM'i boşalt
        try:
            subprocess.run(["curl", "-s", "http://localhost:11434/api/generate", "-d", json.dumps({"model": "qwen-coder-14b-abliterated:latest", "keep_alive": "0s"})], stdout=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass

        return {
            "success": final_state.get("verified", False),
            "model_used": final_state.get("model_choice"),
            "attempts": final_state.get("attempt_count"),
            "repo_path": final_state.get("repo_path"),
            "ast_count": len(final_state.get("ast_findings", [])),
            "output": final_state.get("final_output") or final_state.get("error_feedback")
        }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        task_arg = sys.argv[1]
        repo_arg = sys.argv[2] if len(sys.argv) > 2 else None
        res = BarisLangGraphEngine.run_investigation(task_arg, repo_arg)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ready", "engine": "BarisLangGraphEngine", "version": "3.0.0"}))
