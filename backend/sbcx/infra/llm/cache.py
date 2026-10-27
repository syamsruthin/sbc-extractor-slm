"""Response cache keyed by the full request (model, prompts, schema, temperature). Temperature-0
calls are reproducible, so repeated summaries/explanations cost nothing."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class ResponseCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("create table if not exists llm_cache (key text primary key, value text)")
        self._lock = threading.Lock()

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("select value from llm_cache where key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._conn.execute("insert or replace into llm_cache values (?, ?)", (key, json.dumps(value)))
            self._conn.commit()
