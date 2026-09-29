"""
auth_db.py — Local-only SQLite storage for authentication state.

Ensures user credentials, password hashes, and lockout counters are stored
strictly on the local machine in the user's persistent app directory,
completely decoupled from any cloud database (Supabase/PostgreSQL).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from backend.local_config import CONFIG_DIR


class AuthDB:
    """
    Dedicated local SQLite store for auth_state.
    Provides get_auth_value / set_auth_value matching the interface expected by AuthManager.
    """

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        if db_path:
            self._path = Path(db_path)
        else:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self._path = CONFIG_DIR / "auth.db"

        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

    def get_auth_value(self, key: str) -> Optional[str]:
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT value FROM auth_state WHERE key = ?",
                    (key,),
                )
                row = cur.fetchone()
                return row["value"] if row else None

    def set_auth_value(self, key: str, value: str) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO auth_state (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
                conn.commit()
