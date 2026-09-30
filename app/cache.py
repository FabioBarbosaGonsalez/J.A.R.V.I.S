"""Cache em SQLite com prazo de validade (TTL).

Guarda respostas das APIs externas para respeitar os limites dos planos
gratuitos e para o painel continuar mostrando algo quando uma API cai:
`get` só devolve valores válidos; `get_stale` devolve mesmo os vencidos.

Cada operação abre a própria conexão. É simples, seguro entre as threads do
FastAPI e rápido o bastante para um painel pessoal.
"""

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Entry:
    value: Any
    stored_at: float  # epoch, em segundos
    expires_at: float

    @property
    def fresh(self) -> bool:
        return time.time() < self.expires_at


class Cache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL,"
                " stored_at REAL NOT NULL, expires_at REAL NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def get_stale(self, key: str) -> Entry | None:
        """Devolve o valor guardado, mesmo que já tenha vencido."""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT value, stored_at, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return Entry(value=json.loads(row[0]), stored_at=row[1], expires_at=row[2])

    def get(self, key: str) -> Entry | None:
        """Devolve o valor só se ainda estiver dentro da validade."""
        entry = self.get_stale(key)
        return entry if entry and entry.fresh else None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        now = time.time()
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO cache (key, value, stored_at, expires_at) VALUES (?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), now, now + ttl_seconds),
            )

    def delete(self, key: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM cache WHERE key = ?", (key,))

    def increment(self, key: str, ttl_seconds: float) -> int:
        """Soma 1 a um contador (ex.: requisições do mês) e devolve o novo valor."""
        entry = self.get(key)
        count = (entry.value if entry else 0) + 1
        self.set(key, count, ttl_seconds)
        return count
