"""Block, mineração e validação da blockchain BRN."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Callable

from db import BlockchainDB


DIFFICULTY = 4
DIFFICULTY_ADJUST_EVERY = 10
TARGET_BLOCK_TIME = 10.0
REWARD = 50.0


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def txid_of(tx: dict) -> str:
    body = {k: v for k, v in tx.items() if k != "txid"}
    return _sha256(json.dumps(body, sort_keys=True, separators=(",", ":")))


def make_transaction(sender: str, recipient: str, amount: float) -> dict:
    tx = {
        "sender":    sender,
        "recipient": recipient,
        "amount":    float(amount),
        "timestamp": time.time(),
    }
    tx["txid"] = txid_of(tx)
    return tx


def validate_transaction(tx: dict, db: BlockchainDB) -> tuple[bool, str]:
    if not isinstance(tx, dict):
        return False, "tx não é dict"
    for k in ("sender", "recipient", "amount", "timestamp", "txid"):
        if k not in tx:
            return False, f"campo faltando: {k}"
    try:
        amount = float(tx["amount"])
    except (TypeError, ValueError):
        return False, "amount inválido"
    if amount <= 0:
        return False, "amount <= 0"
    if tx["sender"] == "":
        return True, "coinbase"
    w = db.wallet_get(tx["sender"])
    if w is None:
        return False, "remetente desconhecido"
    if w["balance"] < amount:
        return False, "saldo insuficiente"
    return True, "ok"


def expected_difficulty(chain_so_far: list[dict]) -> int:
    d = DIFFICULTY
    if len(chain_so_far) < DIFFICULTY_ADJUST_EVERY:
        return d
    window = chain_so_far[-DIFFICULTY_ADJUST_EVERY:]
    elapsed = window[-1]["timestamp"] - window[0]["timestamp"]
    if elapsed <= 0:
        return min(d + 1, 12)
    avg = elapsed / (len(window) - 1)
    if avg < TARGET_BLOCK_TIME / 2:
        return min(d + 1, 12)
    if avg > TARGET_BLOCK_TIME * 2:
        return max(d - 1, 1)
    return d


class Block:
    def __init__(self, index: int, previous_hash: str, transactions: list,
                 difficulty: int, nonce: int = 0,
                 timestamp: float | None = None,
                 block_hash: str | None = None):
        self.index = index
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.previous_hash = previous_hash
        self.transactions = transactions
        self.difficulty = difficulty
        self.nonce = nonce
        self.hash = (block_hash if block_hash is not None
                     else self.compute_hash())

    def compute_hash(self) -> str:
        s = json.dumps({
            "index":         self.index,
            "timestamp":     self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions":  self.transactions,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
        }, sort_keys=True, separators=(",", ":"))
        return _sha256(s)

    def mine(self, status_callback: Callable[[str], None] | None = None,
             stop_event: threading.Event | None = None) -> str:
        target = "0" * self.difficulty
        self.nonce = 0
        self.hash = self.compute_hash()
        attempts = 0
        while not self.hash.startswith(target):
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("mineração cancelada")
            self.nonce += 1
            self.hash = self.compute_hash()
            attempts += 1
            if status_callback and attempts % 5000 == 0:
                status_callback(
                    f"Minerando... nonce={self.nonce} "
                    f"({attempts} tentativas)"
                )
        return self.hash

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        return cls(
            index=data["index"],
            previous_hash=data["previous_hash"],
            transactions=data["transactions"],
            difficulty=data["difficulty"],
            nonce=data["nonce"],
            timestamp=data["timestamp"],
            block_hash=data["hash"],
        )

    def to_dict(self) -> dict:
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions":  self.transactions,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
            "hash":          self.hash,
        }


def check_blockchain_validity(db: BlockchainDB) -> bool:
    chain = db.get_raw_chain()
    if not chain:
        return True
    for i, raw in enumerate(chain):
        blk = Block.from_dict(raw)
        if blk.hash != blk.compute_hash():
            return False
        if not blk.hash.startswith("0" * blk.difficulty):
            return False
        if i > 0 and blk.previous_hash != chain[i - 1]["hash"]:
            return False
        for j, tx in enumerate(blk.transactions):
            if tx.get("sender") == "" and j != 0:
                return False
    return True


def build_next_block(db: BlockchainDB, miner_address: str) -> Block:
    chain = db.get_raw_chain()
    index = len(chain)
    prev = chain[-1]["hash"] if chain else "0" * 64
    difficulty = expected_difficulty(chain)

    txs: list[dict] = []
    coinbase = {
        "sender":    "",
        "recipient": miner_address,
        "amount":    REWARD,
        "timestamp": time.time(),
    }
    coinbase["txid"] = txid_of(coinbase)
    txs.append(coinbase)

    for tx in db.mempool_all():
        ok, _ = validate_transaction(tx, db)
        if ok:
            txs.append(tx)

    return Block(index=index, previous_hash=prev,
                 transactions=txs, difficulty=difficulty)


def apply_block(db: BlockchainDB, block: Block) -> None:
    """Grava o bloco e atualiza saldos (débito/crédito)."""
    with db.tx() as c:
        for tx in block.transactions:
            sender = tx.get("sender", "")
            recipient = tx.get("recipient", "")
            amt = float(tx.get("amount", 0))
            if sender:
                c.execute(
                    "UPDATE wallet SET balance = balance - ? "
                    "WHERE address=?",
                    (amt, sender),
                )
            if recipient:
                c.execute(
                    "UPDATE wallet SET balance = balance + ? "
                    "WHERE address=?",
                    (amt, recipient),
                )
        c.execute(
            "INSERT OR REPLACE INTO blocks VALUES (?,?,?,?,?,?,?)",
            (
                block.index, block.timestamp, block.previous_hash,
                json.dumps(block.transactions, separators=(",", ":")),
                block.difficulty, block.nonce, block.hash,
            ),
        )
        for tx in block.transactions:
            if tx.get("sender"):
                c.execute("DELETE FROM mempool WHERE txid=?",
                          (tx.get("txid"),))


if __name__ == "__main__":
    import os
    import tempfile
    from carteira import generate_keypair

    p = os.path.join(tempfile.gettempdir(), "brn_bc_test.db")
    try:
        os.remove(p)
    except OSError:
        pass

    db = BlockchainDB(p)
    priv, addr = generate_keypair()
    db.wallet_save(addr, "x", "y", balance=100.0)

    print("Minerando bloco genesis (dificuldade 4)...")
    blk = build_next_block(db, addr)
    blk.mine(status_callback=lambda m: print("  ", m))
    apply_block(db, blk)
    print("Genesis:", blk.hash[:16], "...")
    print("Height:", db.height)
    print("Validação:", check_blockchain_validity(db))

    db.close()
    os.remove(p)
    print("OK — blockchain.py funciona.")