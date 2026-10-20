#!/usr/bin/env python3
"""
OMNICORE X // FAZ 5: PERSISTENT MEMORY STORE
Motor: SQLite WAL Modu + FTS5 Tam Metin Arama Indeksi
Yetkinlikler:
- Görev geçmişi, araç yürütme kayıtları, kaynak referansları ve commit hash'leri
- Başarılı çözüm ve hata kalıpları (Solution & Failure Patterns)
- Kullanıcı onaylı tercihler
- Uzun geçmişi modele yığmak yerine FTS5 tabanlı cerrahi arama/getirme (Retrieval)
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent
DB_DIR = WORKSPACE_ROOT / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "omnicore_memory.db"

class PersistentMemoryStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL modu ve performans ayarlari
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # 1. Görev Geçmişi Tablosu
            conn.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                task_id TEXT PRIMARY KEY,
                requested_goal TEXT NOT NULL,
                execution_state TEXT NOT NULL,
                model_id TEXT NOT NULL,
                commit_sha TEXT,
                final_decision TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                metadata JSON
            );
            """)

            # 2. Araç Yürütme Logları
            conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_payload TEXT,
                output_payload TEXT,
                exit_code INTEGER DEFAULT 0,
                duration_sec REAL DEFAULT 0.0,
                timestamp REAL NOT NULL,
                FOREIGN KEY(task_id) REFERENCES task_history(task_id) ON DELETE CASCADE
            );
            """)

            # 3. Yapılandırılmış Kanıtlar ve Kaynak Referansları
            conn.execute("""
            CREATE TABLE IF NOT EXISTS research_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT,
                content_snippet TEXT,
                content_hash TEXT,
                verified_date TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY(task_id) REFERENCES task_history(task_id) ON DELETE CASCADE
            );
            """)

            # 4. FTS5 Çözüm ve Hata Kalıpları Tablosu
            conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS pattern_vault USING fts5(
                pattern_id,
                pattern_type, -- 'SUCCESS' veya 'FAILURE'
                goal,
                solution_summary,
                code_snippet,
                error_trace,
                tags
            );
            """)

            # 5. Kullanıcı Tercihleri Tablosu
            conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                pref_key TEXT PRIMARY KEY,
                pref_value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            # 6. Sürekli Diyalog ve Semantik Hafıza Tablosu (Episodic Memory)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model_used TEXT,
                created_at REAL NOT NULL
            );
            """)
            conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
                content,
                role,
                content='conversation_memory',
                content_rowid='id'
            );
            """)
            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_conversation_ai AFTER INSERT ON conversation_memory BEGIN
                INSERT INTO conversation_fts(rowid, content, role) VALUES (new.id, new.content, new.role);
            END;
            """)
            conn.commit()

    # --------------------------------------------------------------------------
    # Görev Yönetimi
    # --------------------------------------------------------------------------
    def record_task_start(self, task_id: str, goal: str, model_id: str, metadata: Optional[Dict[str, Any]] = None):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO task_history (
                task_id, requested_goal, execution_state, model_id, created_at, updated_at, metadata
            ) VALUES (?, ?, 'STARTED', ?, ?, ?, ?);
            """, (task_id, goal, model_id, now, now, json.dumps(metadata or {}, ensure_ascii=False)))
            conn.commit()

    def update_task_state(self, task_id: str, state: str, final_decision: Optional[str] = None, commit_sha: Optional[str] = None):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
            UPDATE task_history
            SET execution_state = ?, final_decision = ?, commit_sha = ?, updated_at = ?
            WHERE task_id = ?;
            """, (state, final_decision, commit_sha, now, task_id))
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM task_history WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                if d.get("metadata"):
                    try:
                        d["metadata"] = json.loads(d["metadata"])
                    except Exception:
                        pass
                return d
        return None

    # --------------------------------------------------------------------------
    # Araç Kayıtları
    # --------------------------------------------------------------------------
    def record_tool_execution(
        self,
        task_id: str,
        tool_name: str,
        input_payload: Any,
        output_payload: Any,
        exit_code: int = 0,
        duration_sec: float = 0.0
    ):
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO tool_executions (
                task_id, tool_name, input_payload, output_payload, exit_code, duration_sec, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (
                task_id,
                tool_name,
                json.dumps(input_payload, ensure_ascii=False) if not isinstance(input_payload, str) else input_payload,
                json.dumps(output_payload, ensure_ascii=False) if not isinstance(output_payload, str) else output_payload,
                exit_code,
                duration_sec,
                time.time()
            ))
            conn.commit()

    # --------------------------------------------------------------------------
    # Araştırma ve Kanıt Kayıtları
    # --------------------------------------------------------------------------
    def record_evidence(self, task_id: str, source_url: str, title: str, snippet: str, content_hash: str):
        with self._get_connection() as conn:
            # Task kaydının varlığını güvenceye al
            cur = conn.execute("SELECT 1 FROM task_history WHERE task_id = ?", (task_id,))
            if not cur.fetchone():
                conn.execute("""
                INSERT OR IGNORE INTO task_history (task_id, requested_goal, execution_state, model_id, created_at, updated_at)
                VALUES (?, 'Otomatik Araştırma Görevi', 'STARTED', 'system', ?, ?);
                """, (task_id, time.time(), time.time()))

            conn.execute("""
            INSERT INTO research_evidence (
                task_id, source_url, title, content_snippet, content_hash, verified_date, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'), ?);
            """, (task_id, source_url, title, snippet[:1000], content_hash, time.time()))
            conn.commit()

    # --------------------------------------------------------------------------
    # Kalıp ve Çözüm Hafızası (FTS5 Retrieval)
    # --------------------------------------------------------------------------
    def save_pattern(
        self,
        pattern_id: str,
        pattern_type: str,
        goal: str,
        summary: str,
        code_snippet: str = "",
        error_trace: str = "",
        tags: str = ""
    ):
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO pattern_vault (pattern_id, pattern_type, goal, solution_summary, code_snippet, error_trace, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (pattern_id, pattern_type.upper(), goal, summary, code_snippet, error_trace, tags))
            conn.commit()

    def search_patterns(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """FTS5 kullanarak geçmişteki benzer başarılı çözüm veya hata kalıplarını çeker."""
        clean_q = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if not clean_q:
            return []
        tokens = clean_q.split()
        match_expr = " OR ".join(f'"{t}"*' for t in tokens)

        with self._get_connection() as conn:
            try:
                cur = conn.execute("""
                SELECT pattern_id, pattern_type, goal, solution_summary, code_snippet, error_trace, tags
                FROM pattern_vault
                WHERE pattern_vault MATCH ?
                ORDER BY rank
                LIMIT ?;
                """, (match_expr, limit))
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                # FTS match hatası durumunda LIKE ile fallback
                cur = conn.execute("""
                SELECT pattern_id, pattern_type, goal, solution_summary, code_snippet, error_trace, tags
                FROM pattern_vault
                WHERE goal LIKE ? OR solution_summary LIKE ?
                LIMIT ?;
                """, (f"%{clean_q}%", f"%{clean_q}%", limit))
                return [dict(r) for r in cur.fetchall()]

    # --------------------------------------------------------------------------
    # Sürekli Semantik ve Bölümsel Diyalog Hafızası (Episodic & Semantic Memory)
    # --------------------------------------------------------------------------
    def record_turn(self, user_msg: str, assistant_msg: str, model_used: str = "", session_id: str = "default"):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO conversation_memory (session_id, role, content, model_used, created_at)
            VALUES (?, 'user', ?, ?, ?);
            """, (session_id, user_msg, model_used, now))
            conn.execute("""
            INSERT INTO conversation_memory (session_id, role, content, model_used, created_at)
            VALUES (?, 'assistant', ?, ?, ?);
            """, (session_id, assistant_msg, model_used, now))
            conn.commit()

    def search_memory(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """FTS5 ve tam metin aramasıyla geçmiş diyalog ve çözüm hafızasını çeker."""
        clean_q = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if not clean_q or len(clean_q) < 3:
            return []
        tokens = [t for t in clean_q.split() if len(t) >= 3]
        if not tokens:
            return []
        match_expr = " OR ".join(f'"{t}"*' for t in tokens[:6])

        with self._get_connection() as conn:
            try:
                cur = conn.execute("""
                SELECT session_id, role, content, model_used, created_at
                FROM conversation_memory
                WHERE id IN (
                    SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?
                )
                ORDER BY created_at DESC
                LIMIT ?;
                """, (match_expr, limit))
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                cur = conn.execute("""
                SELECT session_id, role, content, model_used, created_at
                FROM conversation_memory
                WHERE content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?;
                """, (f"%{clean_q[:30]}%", limit))
                return [dict(r) for r in cur.fetchall()]

# Küresel tekil örnek
memory_store = PersistentMemoryStore()
