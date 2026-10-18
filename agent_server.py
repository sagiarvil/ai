#!/usr/bin/env python3
# ==============================================================================
# BARIŞ AI // INDUSTRIAL AGENTIC SERVER (FASTAPI + GIT + MULTIMODAL + LOCAL LLM)
# ==============================================================================
import os
import io
import json
import base64
from pathlib import Path
from typing import List, Dict, Optional
import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import git
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
try:
    import docx
except ImportError:
    docx = None


# ÇALIŞMA ALANI GÜVENLİK KİLİDİ (Mac Proje Klasörü)
WORKSPACE_DIR = Path(os.getenv("BARIS_AI_WORKSPACE", str(Path.home() / "projects"))).resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/v1/chat/completions")
DEFAULT_MODEL = os.getenv("BARIS_AI_MODEL", "mistral-small-24b-abliterated:latest")

app = FastAPI(title="Baris AI Industrial Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# TÜRK İNSANI & MÜHENDİSLİK PSİKOLOJİSİ SİSTEM PROMPTU
# ------------------------------------------------------------------------------
SYSTEM_PROMPT = """Sen 'Baris AI'sın. Kıdemli bir Türk yapay zekâ ve sistem mühendisi zihniyetiyle çalışırsın.
DİL VE DAVRANIŞ KURALI:
1. Çeviri kokan, robotik veya aşırı yapay kibar ifadeleri ("Harika bir soru!", "Size yardımcı olmaktan mutluluk duyarım") ASLA kullanma.
2. Doğrudan meseleye gir. Lafı dolandırma, net, akılcı, pragmatik ve gerektiğinde tatlı sert/dobra bir usta mühendis gibi konuş.
3. Türkçe imla ve yazım hatalarını bağlamdan otomatik anla, zihninde düzelt ve göreve takılmadan devam et.
4. Teknik jargon serbesttir (refactor, AST, latency, edge case, boilerplate vb.).
5. Çözümleri her zaman endüstriyel kalitede, üretime hazır (production-ready) kod bloklarıyla ver. Eksik veya yarım kod bırakma.
6. Dosya oluşturma ve kaydetme işlemlerini doğrudan operasyonel çıktılarla yönet.
"""

class Message(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    messages: List[Message]
    workspace_path: Optional[str] = None
    stream: bool = False

# ------------------------------------------------------------------------------
# YEREL DOSYA SİSTEMİ & GİT YÖNETİM MODÜLÜ
# ------------------------------------------------------------------------------
class SystemWorkspace:
    @staticmethod
    def write_file(rel_path: str, content: str) -> str:
        raw = Path(rel_path)
        target_path = raw.resolve() if raw.is_absolute() else (WORKSPACE_DIR / raw).resolve()
        # İzinli klasör kontrolü
        if not (str(target_path).startswith(str(WORKSPACE_DIR)) or str(target_path).startswith(str(Path.home() / ".omnicore"))):
            raise HTTPException(status_code=403, detail="Dizin dışına çıkış engellendi.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return f"Dosya başarıyla yazıldı: {rel_path} ({len(content)} karakter)"

    @staticmethod
    def read_file(rel_path: str) -> str:
        raw = Path(rel_path)
        target_path = raw.resolve() if raw.is_absolute() else (WORKSPACE_DIR / raw).resolve()
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Dosya bulunamadı.")
        return target_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def git_commit(repo_rel_path: str, commit_message: str) -> str:
        raw = Path(repo_rel_path)
        repo_path = raw.resolve() if raw.is_absolute() else (WORKSPACE_DIR / raw).resolve()
        if not repo_path.exists():
            raise HTTPException(status_code=404, detail=f"Git deposu bulunamadı: {repo_rel_path}")
        repo = git.Repo(repo_path)
        repo.git.add(A=True)
        commit = repo.index.commit(commit_message)
        return f"Commit tamam: {commit.hexsha[:7]} - {commit_message}"

# ------------------------------------------------------------------------------
# ÇOK MODLU DÖKÜMAN VE GÖRSEL AYRIŞTIRICI
# ------------------------------------------------------------------------------
def extract_file_content(file_bytes: bytes, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext == "pdf":
        if fitz:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            return "\n".join([page.get_text() for page in doc])
        else:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            return "\n".join([page.extract_text() or "" for page in reader.pages])
    elif ext in ["doc", "docx"]:
        if docx:
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join([p.text for p in doc.paragraphs if p.text])
        return "[python-docx kütüphanesi eksik]"
    elif ext in ["png", "jpg", "jpeg", "webp", "bmp", "gif"]:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        return f"[Görsel Dosyası: {filename} | Data: image/{ext};base64,{b64[:64]}...]"
    else:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return f"[{filename} uzantılı ikili dosya ayrıştırılamadı]"

# ------------------------------------------------------------------------------
# UÇ NOKTALAR (ENDPOINTS)
# ------------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ONLINE", "engine": "Baris AI Industrial Engine", "workspace": str(WORKSPACE_DIR)}

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    extracted_text = extract_file_content(content, file.filename or "belge")
    return {"filename": file.filename, "extracted_text": extracted_text}

@app.post("/api/fs/write")
async def fs_write(data: Dict[str, str]):
    res = SystemWorkspace.write_file(data["path"], data["content"])
    return {"status": "success", "message": res}

@app.post("/api/fs/read")
async def fs_read(data: Dict[str, str]):
    content = SystemWorkspace.read_file(data["path"])
    return {"content": content}

@app.post("/api/git/commit")
async def git_commit_endpoint(data: Dict[str, str]):
    res = SystemWorkspace.git_commit(data["repo_path"], data["message"])
    return {"status": "success", "message": res}

@app.post("/api/chat/stream")
async def chat_stream(payload: ChatPayload):
    """Kayan pencereli (sliding window son 10 tur / 20 mesaj) streaming chat."""
    raw_msgs = [{"role": m.role, "content": m.content} for m in payload.messages[-20:]]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + raw_msgs

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    OLLAMA_API_URL,
                    json={
                        "model": DEFAULT_MODEL,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.1,
                        "options": {
                            "num_thread": 8,
                            "num_ctx": 8192,
                            "temperature": 0.1
                        }
                    }
                ) as response:
                    async for chunk in response.aiter_lines():
                        if not chunk or not chunk.startswith("data: "):
                            continue
                        data_str = chunk[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            j = json.loads(data_str)
                            delta = j.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
        except Exception as e:
            yield f"\n[Hata: {str(e)}]"

    return StreamingResponse(event_generator(), media_type="text/plain")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
