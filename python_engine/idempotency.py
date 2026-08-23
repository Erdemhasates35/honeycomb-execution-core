# python_engine/idempotency.py
import sqlite3
import json
from typing import Optional, Any

class IdempotencySQLite:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency (
                client_id TEXT PRIMARY KEY,
                result_json TEXT,
                created_ts INTEGER
            )
            """)
            conn.commit()

    def get(self, client_id: str) -> Optional[Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT result_json FROM idempotency WHERE client_id=?", (client_id,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return None

    def put(self, client_id: str, result: Any):
        rj = json.dumps(result)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("REPLACE INTO idempotency (client_id, result_json, created_ts) VALUES (?, ?, strftime('%s','now'))", (client_id, rj))
            conn.commit()
