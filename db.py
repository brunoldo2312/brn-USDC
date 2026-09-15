"""Camada de persistência SQLite do nó BRN."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=30000;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS blocks (
    id_index      INTEGER PRIMARY KEY,
    timestamp     REAL    NOT NULL,
    previous_hash TEXT    NOT NULL,
    transactions  TEXT    NOT NULL,
    difficulty    INTEGER NOT NULL,
    nonce         INTEGER NOT NULL,
    hash          TEXT    NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_blocks_hash ON blocks(hash);

CREATE TABLE IF NOT EXISTS wallet (
    address       TEXT PRIMARY KEY,
    private_key   TEXT NOT NULL,
    kdf_salt      TEXT NOT NULL,
    balance       REAL NOT NULL DEFAULT 0.0,
    usdc_address  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mempool (
    txid          TEXT PRIMARY KEY,
    raw           TEXT NOT NULL,
    added_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_book (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    seller        TEXT NOT NULL,
    brn_amount    REAL NOT NULL,
    usdc_price    REAL NOT NULL,
    usdc_address  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN'
);
"""


class BlockchainDB:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.db_path,
            isolation_level=None,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version VALUES (?)",
                    (SCHEMA_VERSION,),
                )
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Schema incompatível: {row['version']} "
                    f"!= {SCHEMA_VERSION}"
                )

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

    # ---------------- blocos ----------------
    def insert_block(self, block: Any) -> None:
        if block.index is None or block.hash is None:
            raise ValueError("Bloco sem index/hash")
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO blocks VALUES (?,?,?,?,?,?,?)",
                (
                    block.index,
                    block.timestamp,
                    block.previous_hash,
                    json.dumps(block.transactions, separators=(",", ":")),
                    block.difficulty,
                    block.nonce,
                    block.hash,
                ),
            )

    def get_raw_chain(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blocks ORDER BY id_index ASC"
            ).fetchall()
        return [
            {
                "index":         r["id_index"],
                "timestamp":     r["timestamp"],
                "previous_hash": r["previous_hash"],
                "transactions":  json.loads(r["transactions"]),
                "difficulty":    r["difficulty"],
                "nonce":         r["nonce"],
                "hash":          r["hash"],
            }
            for r in rows
        ]

    def get_block_by_hash(self, h: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM blocks WHERE hash=?", (h,)
            ).fetchone()
        if r is None:
            return None
        return {
            "index":         r["id_index"],
            "timestamp":     r["timestamp"],
            "previous_hash": r["previous_hash"],
            "transactions":  json.loads(r["transactions"]),
            "difficulty":    r["difficulty"],
            "nonce":         r["nonce"],
            "hash":          r["hash"],
        }

    @property
    def height(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(id_index) AS h FROM blocks"
            ).fetchone()
        return int(row["h"]) if row["h"] is not None else -1

    @property
    def tip_hash(self) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT hash FROM blocks ORDER BY id_index DESC LIMIT 1"
            ).fetchone()
        return row["hash"] if row else "0" * 64

    @property
    def last_block(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM blocks ORDER BY id_index DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "index":         row["id_index"],
            "timestamp":     row["timestamp"],
            "previous_hash": row["previous_hash"],
            "transactions":  json.loads(row["transactions"]),
            "difficulty":    row["difficulty"],
            "nonce":         row["nonce"],
            "hash":          row["hash"],
        }

    # ---------------- carteira ----------------
    def wallet_save(self, address: str, priv_enc: str, salt: str,
                    balance: float = 0.0) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO wallet"
                "(address, private_key, kdf_salt, balance, usdc_address) "
                "VALUES (?,?,?,?, COALESCE("
                "(SELECT usdc_address FROM wallet WHERE address=?),''))",
                (address, priv_enc, salt, balance, address),
            )

    def wallet_get(self, address: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM wallet WHERE address=?", (address,)
            ).fetchone()
        return dict(r) if r else None

    def wallet_list(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT address, balance, usdc_address FROM wallet"
            ).fetchall()
        return [dict(r) for r in rows]

    def wallet_set_balance(self, address: str, balance: float) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE wallet SET balance=? WHERE address=?",
                (balance, address),
            )

    # ---------------- mempool ----------------
    def mempool_add(self, txid: str, raw: str) -> bool:
        try:
            with self.tx() as c:
                c.execute(
                    "INSERT INTO mempool(txid, raw, added_at) VALUES (?,?,?)",
                    (txid, raw, time.time()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def mempool_all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mempool ORDER BY added_at ASC"
            ).fetchall()
        return [json.loads(r["raw"]) for r in rows]

    def mempool_contains(self, txid: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM mempool WHERE txid=?", (txid,)
            ).fetchone() is not None

    def mempool_remove(self, txid: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM mempool WHERE txid=?", (txid,))

    def mempool_size(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) n FROM mempool"
            ).fetchone()["n"]


if __name__ == "__main__":
    import tempfile, os
    p = os.path.join(tempfile.gettempdir(), "brn_test.db")
    try:
        os.remove(p)
    except OSError:
        pass
    db = BlockchainDB(p)
    print("Banco criado:", p)
    print("Height inicial:", db.height)
    print("Tip hash:", db.tip_hash[:16], "...")
    print("Mempool size:", db.mempool_size())
    db.close()
    os.remove(p)
    print("OK — db.py funciona.")