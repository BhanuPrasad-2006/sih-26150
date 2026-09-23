"""
audit.py — Hash-chained audit log.

Formula (PRD §5.6.3):
  Hash_n = SHA-256( Time_n | Action_n | Params_n | Hash_(n-1) )

Changing any past entry breaks all subsequent hashes, making tampering visible.
Every action the tool takes (load, detect, scan, export, verify, report) is logged here.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from backend.models import AuditEntry


class AuditLog:
    """
    In-memory hash-chained audit log.
    Call export_entries() to get the full chain for report embedding or DB storage.
    Thread-safe (a scan may append from a worker thread).
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._last_hash: str = ""
        self._lock = threading.Lock()

    @classmethod
    def from_entries(cls, entries: list[AuditEntry]) -> "AuditLog":
        """
        Rebuild an AuditLog from entries already persisted to the database
        (chain order), so history survives a server restart instead of
        starting empty.
        """
        log = cls()
        log._entries = list(entries)
        log._last_hash = entries[-1].entry_hash if entries else ""
        return log

    # ── Public API ────────────────────────────────────────────────────────────

    def append(self, action: str, details: str = "") -> AuditEntry:
        """
        Add a new entry and compute its hash.
        Returns the completed AuditEntry.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            entry = AuditEntry(
                action=action,
                details=details,
                previous_hash=self._last_hash,
            )
            entry.created_at = now
            entry.entry_hash = self._compute_hash(entry)
            self._last_hash = entry.entry_hash
            self._entries.append(entry)
            return entry

    def verify_chain(self) -> tuple[bool, Optional[str]]:
        """
        Walk the chain and recompute every hash.
        Returns (True, None) if intact, or (False, error_message).
        """
        previous_hash = ""
        for entry in self._entries:
            expected = self._compute_hash_from_fields(
                entry.created_at, entry.action, entry.details, previous_hash
            )
            if expected != entry.entry_hash:
                return False, (
                    f"Hash mismatch at entry {entry.entry_id!r} "
                    f"(action={entry.action!r}): "
                    f"expected {expected[:16]}… got {entry.entry_hash[:16]}…"
                )
            previous_hash = entry.entry_hash
        return True, None

    def export_entries(self) -> list[dict]:
        """Return all entries as a list of dicts (for JSON / PDF embedding)."""
        with self._lock:
            return [e.model_dump() for e in self._entries]

    def last_hash(self) -> str:
        """Return the hash of the most recent entry (for report anchoring)."""
        with self._lock:
            return self._last_hash

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(entry: AuditEntry) -> str:
        return AuditLog._compute_hash_from_fields(
            entry.created_at, entry.action, entry.details, entry.previous_hash
        )

    @staticmethod
    def _compute_hash_from_fields(
        created_at: str, action: str, details: str, previous_hash: str
    ) -> str:
        payload = "\n".join([created_at, action, details, previous_hash])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
