import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

# Runtime database path resolution
_RUNTIME_DIR = Path(__file__).resolve().parent / ".baris_runtime"
if _RUNTIME_DIR.exists():
    DB_PATH = _RUNTIME_DIR / "jobs.sqlite3"
else:
    DB_PATH = Path(__file__).resolve().parent / "jobs.db"

@contextmanager
def get_db_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_memory_schema():
    """Uygulama başlangıcında 1 kez çağrılır. Tablo yoksa oluşturur."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
                content TEXT NOT NULL,
                tool_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON conversation_sessions(session_id, created_at)")
        conn.commit()

def save_message(session_id: str, role: str, content: str, tool_used: Optional[str] = None):
    """Mesajı veritabanına yazar. (Tip güvenliği role CHECK ile sağlanır)"""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_sessions (session_id, role, content, tool_used) VALUES (?, ?, ?, ?)",
            (session_id, role, content, tool_used)
        )
        conn.commit()

def get_session_context(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """LLM için son 'limit' kadar mesajı kronolojik sırayla çeker."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT role, content, tool_used 
               FROM conversation_sessions 
               WHERE session_id = ? 
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (session_id, limit)
        )
        rows = cursor.fetchall()
        return [{"role": row["role"], "content": row["content"], "tool_used": row["tool_used"]} for row in reversed(rows)]
