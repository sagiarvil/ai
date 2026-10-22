# ==============================================================================
# DOSYA: agent_server.py (FastAPI Arka Uç Motoru - Yerel Git/FS & Çok Modlu Ajan)
# ==============================================================================
import os
import io
import json
import base64
import urllib.request
from pathlib import Path
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import git
import fitz  # PyMuPDF
import docx

# ÇALIŞMA ALANI GÜVENLİK KİLİDİ (Mac Proje Klasörü)
WORKSPACE_DIR = Path(os.getenv("BARIS_AI_WORKSPACE", str(Path.home() / "projects")))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral-small-24b-abliterated:latest")

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
1. Çeviri kokan, robotik veya aşırı yapay kibar ifadeleri ("Harika bir soru!", "Size yardımcı olmaktan mutluluk duyarım", "Bir yapay zeka olarak...") KESİNLİKLE KULLANMA.
2. Doğrudan meseleye gir. Lafı dolandırma; net, akılcı, pragmatik ve gerektiğinde tatlı sert/dobra bir usta mühendis gibi konuş.
3. Teknik jargon serbesttir (refactor, AST, latency, edge case, boilerplate, fail-safe vb.).
4. Çözümleri her zaman endüstriyel kalitede, üretime hazır (production-ready) kod bloklarıyla ver. Eksik veya yarım kod bırakma.
5. Kullanıcı hızlı yazarken imla ve harf hataları yaparsa (örneğin "kurukum", "taımat", "kabılıyert", "anayabılmelı") bağlamdan hemen anla, zihninde düzelt ve takılmadan işi bitir.
6. Dosya oluşturma ve kaydetme işlemlerini doğrudan operasyonel çıktılarla yönet.
"""

class Message(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    messages: List[Message]
    workspace_path: Optional[str] = None

# ------------------------------------------------------------------------------
# YEREL DOSYA SİSTEMİ & GİT YÖNETİM MODÜLÜ
# ------------------------------------------------------------------------------
class SystemWorkspace:
    @staticmethod
    def write_file(rel_path: str, content: str) -> str:
        target_path = (WORKSPACE_DIR / rel_path).resolve()
        if not str(target_path).startswith(str(WORKSPACE_DIR)):
            raise HTTPException(status_code=403, detail="Dizin dışına çıkış engellendi.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return f"Dosya başarıyla yazıldı: {rel_path}"

    @staticmethod
    def read_file(rel_path: str) -> str:
        target_path = (WORKSPACE_DIR / rel_path).resolve()
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Dosya bulunamadı.")
        return target_path.read_text(encoding="utf-8")

    @staticmethod
    def git_commit(repo_rel_path: str, commit_message: str) -> str:
        repo_path = (WORKSPACE_DIR / repo_rel_path).resolve()
        repo = git.Repo(repo_path)
        repo.git.add(A=True)
        commit = repo.index.commit(commit_message)
        return f"Commit tamam: {commit.hexsha[:7]} - {commit_message}"

# ------------------------------------------------------------------------------
# ÇOK MODLU DÖKÜMAN VE GÖRSEL AYRIŞTIRICI
# ------------------------------------------------------------------------------
def extract_file_content(file_bytes: bytes, filename: str) -> str:
    ext = filename.split(".")[-1].lower()
    if ext == "pdf":
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join([page.get_text() for page in doc])
    elif ext in ["doc", "docx"]:
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join([p.text for p in doc.paragraphs if p.text])
    elif ext in ["png", "jpg", "jpeg", "webp"]:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        return f"[Görsel Dosyası: {filename} | Data: image/{ext};base64,{b64[:64]}... (Base64 İncitildi)]"
    else:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return f"[{filename} uzantılı ikili dosya ayrıştırılamadı]"

# ------------------------------------------------------------------------------
# UÇ NOKTALAR (ENDPOINTS)
# ------------------------------------------------------------------------------
@app.post("/api/upload")
async def upload_document(request: Request):
    filename = "uploaded_file"
    content_bytes = b""
    try:
        form = await request.form()
        file_obj = form.get("file")
        if file_obj and hasattr(file_obj, "read"):
            filename = getattr(file_obj, "filename", "uploaded_file") or "uploaded_file"
            content_bytes = await file_obj.read()
        elif file_obj and isinstance(file_obj, str):
            content_bytes = file_obj.encode("utf-8")
        else:
            content_bytes = await request.body()
    except Exception:
        content_bytes = await request.body()

    extracted_text = extract_file_content(content_bytes, filename)
    return {"filename": filename, "extracted_text": extracted_text}

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

@app.post("/api/chat")
async def chat_endpoint(payload: ChatPayload):
    # En az son 10 diyalog turu (20 mesaj) tamponu
    history_window = payload.messages[-20:] if len(payload.messages) > 20 else payload.messages
    ollama_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history_window:
        ollama_messages.append({"role": m.role, "content": m.content})

    data = {
        "model": OLLAMA_MODEL,
        "messages": ollama_messages,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.3}
    }

    try:
        req = urllib.request.Request(
            OLLAMA_API_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as response:  # nosec B310
            res_json = json.loads(response.read().decode("utf-8"))
            reply_text = res_json.get("message", {}).get("content", "")
            return {"reply": reply_text, "status": "COMPLETED"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Yanıt Hatası: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5055)

# --- OPUS SONNET GATEWAY HOOK ---
from opus_sonnet_kernel import mount_opus_sonnet_gateway
try:
    mount_opus_sonnet_gateway(app)
except Exception:
    pass
