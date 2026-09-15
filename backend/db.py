"""SQLite — ordens, mapeamento Polygon→BRN, depósitos vistos."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY,   -- mesmo id do contrato
    seller_brn    TEXT NOT NULL,         -- endereço BRN (0x) do vendedor
    seller_usdc   TEXT NOT NULL,
    brn_amount    TEXT NOT NULL,         -- string para preservar wei
    price_per_brn TEXT NOT NULL,
    total_usdc    TEXT NOT NULL,
    buyer_brn     TEXT NOT NULL DEFAULT '',
    usdc_tx_in    TEXT NOT NULL DEFAULT '',
    brn_tx_out    TEXT NOT NULL DEFAULT '',
    usdc_tx_out   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'OPEN',
    error_msg     TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS buyer_map (
    polygon_addr TEXT PRIMARY KEY,
    brn_addr     TEXT NOT NULL,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deposits (
    tx_hash       TEXT PRIMARY KEY,
    from_addr     TEXT NOT NULL,
    amount_usdc   TEXT NOT NULL,
    block_number  INTEGER NOT NULL,
    matched_order INTEGER,
    seen_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deposits_matched ON deposits(matched_order);
"""


class DB:
    def __init__(self, path: str | Path):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path), isolation_level=None,
            check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------- orders ----------------
    def order_upsert(self, oid: int, seller_brn: str, seller_usdc: str,
                     brn_amount: str, price_per_brn: str,
                     total_usdc: str) -> None:
        now = time.time()
        with self.tx() as c:
            c.execute(
                "INSERT INTO orders(id, seller_brn, seller_usdc, "
                "brn_amount, price_per_brn, total_usdc, status, "
                "created_at, updated_at) "
                "VALUES (?,?,?,?,?,?, 'OPEN', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "seller_brn=excluded.seller_brn, "
                "seller_usdc=excluded.seller_usdc, "
                "
