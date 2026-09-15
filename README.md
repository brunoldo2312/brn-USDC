1) contracts/BRNToken.sol — Token BRN (ERC-20)
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title BRNToken
 * @notice Token ERC-20 nativo da rede BRN.
 *         Supply inicial cunhado para o operador.
 *         Mint adicional só pelo owner (para recompensas de mineração).
 */
contract BRNToken {
    string public constant name = "BRN Token";
    string public constant symbol = "BRN";
    uint8  public constant decimals = 18;

    uint256 public totalSupply;
    address public owner;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event OwnershipTransferred(address indexed prev, address indexed next);

    modifier onlyOwner() {
        require(msg.sender == owner, "BRN: not owner");
        _;
    }

    constructor(uint256 initialSupply) {
        owner = msg.sender;
        _mint(msg.sender, initialSupply);
    }

    // ---------------- ERC-20 ----------------
    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value)
        external returns (bool)
    {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "BRN: allowance");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    // ---------------- Owner ----------------
    function mint(address to, uint256 value) external onlyOwner {
        _mint(to, value);
    }

    function transferOwnership(address next) external onlyOwner {
        require(next != address(0), "BRN: zero");
        emit OwnershipTransferred(owner, next);
        owner = next;
    }

    // ---------------- Internos ----------------
    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "BRN: to zero");
        uint256 bal = balanceOf[from];
        require(bal >= value, "BRN: balance");
        unchecked { balanceOf[from] = bal - value; }
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        require(to != address(0), "BRN: mint zero");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }
}
2) contracts/BRNExchange.sol — Contrato de troca
Este é o coração. Segue exatamente a dinâmica que você descreveu:

Vendedor deposita BRN no contrato + informa endereço USDC
Comprador paga USDC direto ao operador (hot wallet)
Operador chama fillOrder → contrato libera BRN pro comprador
Operador envia USDC ao vendedor (off-chain, via hot wallet)
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value)
        external returns (bool);
    function balanceOf(address who) external view returns (uint256);
}

/**
 * @title BRNExchange
 * @notice Exchange centralizada BRN/USDC.
 *
 * Fluxo:
 *   1. Vendedor: approve(BRN) + createSellOrder(brnAmount, priceUSDC, usdcAddr)
 *      → BRN fica em escrow no contrato.
 *   2. Comprador: paga USDC direto ao `operator` (hot wallet off-chain).
 *   3. Operador: fillOrder(orderId, buyer) → BRN vai pro comprador.
 *   4. Operador: envia USDC ao vendedor via hot wallet (fora do contrato).
 *
 * O contrato NÃO movimenta USDC — apenas BRN. USDC é tratado
 * off-chain pelo operador, o que simplifica e reduz gás.
 */
contract BRNExchange {
    struct Order {
        address seller;         // quem depositou BRN
        address usdcReceiver;   // endereço Polygon que recebe USDC
        uint256 brnAmount;      // BRN em escrow (wei)
        uint256 pricePerBRN;    // USDC por BRN (6 decimais)
        uint256 totalUSDC;      // brnAmount * pricePerBRN / 1e18
        uint8   status;         // 0=OPEN 1=FILLED 2=CANCELLED
        address buyer;          // preenchido ao fill
        uint64  createdAt;
        uint64  filledAt;
    }

    IERC20  public immutable brn;
    address public operator;    // hot wallet que libera ordens
    address public owner;       // admin (pode trocar operator)

    uint256 public nextOrderId = 1;
    mapping(uint256 => Order) public orders;
    uint256[] public openOrderIds;

    // ---------------- Eventos ----------------
    event OrderCreated(
        uint256 indexed id, address indexed seller,
        address usdcReceiver, uint256 brnAmount,
        uint256 pricePerBRN, uint256 totalUSDC
    );
    event OrderFilled(
        uint256 indexed id, address indexed buyer, address operator
    );
    event OrderCancelled(uint256 indexed id, address indexed seller);
    event OperatorChanged(address indexed prev, address indexed next);

    modifier onlyOperator() {
        require(msg.sender == operator, "EX: not operator");
        _;
    }
    modifier onlyOwner() {
        require(msg.sender == owner, "EX: not owner");
        _;
    }

    constructor(address brnToken, address operator_) {
        require(brnToken != address(0), "EX: brn zero");
        require(operator_ != address(0), "EX: op zero");
        brn = IERC20(brnToken);
        operator = operator_;
        owner = msg.sender;
    }

    // ---------------- Vendedor ----------------
    /**
     * @param brnAmount     quantidade de BRN (wei, 18 decimais)
     * @param pricePerBRN   preço em USDC por 1 BRN (6 decimais)
     * @param usdcReceiver  endereço Polygon que receberá USDC
     *
     * Requer approve(BRN, brnAmount) antes.
     */
    function createSellOrder(
        uint256 brnAmount,
        uint256 pricePerBRN,
        address usdcReceiver
    ) external returns (uint256 id) {
        require(brnAmount > 0, "EX: amount 0");
        require(pricePerBRN > 0, "EX: price 0");
        require(usdcReceiver != address(0), "EX: usdc zero");

        // puxa BRN pro contrato (escrow)
        require(
            brn.transferFrom(msg.sender, address(this), brnAmount),
            "EX: transferFrom failed"
        );

        uint256 totalUSDC = (brnAmount * pricePerBRN) / 1e18;

        id = nextOrderId++;
        orders[id] = Order({
            seller: msg.sender,
            usdcReceiver: usdcReceiver,
            brnAmount: brnAmount,
            pricePerBRN: pricePerBRN,
            totalUSDC: totalUSDC,
            status: 0,
            buyer: address(0),
            createdAt: uint64(block.timestamp),
            filledAt: 0
        });
        openOrderIds.push(id);

        emit OrderCreated(
            id, msg.sender, usdcReceiver,
            brnAmount, pricePerBRN, totalUSDC
        );
    }

    function cancelOrder(uint256 id) external {
        Order storage o = orders[id];
        require(o.status == 0, "EX: not open");
        require(o.seller == msg.sender, "EX: not seller");
        o.status = 2;
        require(brn.transfer(o.seller, o.brnAmount), "EX: refund failed");
        emit OrderCancelled(id, msg.sender);
    }

    // ---------------- Operador ----------------
    /**
     * Libera BRN ao comprador. Só o operador pode chamar.
     * O operador já confirmou o pagamento USDC off-chain.
     */
    function fillOrder(uint256 id, address buyer) external onlyOperator {
        Order storage o = orders[id];
        require(o.status == 0, "EX: not open");
        require(buyer != address(0), "EX: buyer zero");

        o.status = 1;
        o.buyer = buyer;
        o.filledAt = uint64(block.timestamp);

        require(brn.transfer(buyer, o.brnAmount), "EX: send failed");
        emit OrderFilled(id, buyer, msg.sender);
    }

    // ---------------- Admin ----------------
    function setOperator(address next) external onlyOwner {
        require(next != address(0), "EX: zero");
        emit OperatorChanged(operator, next);
        operator = next;
    }

    function transferOwnership(address next) external onlyOwner {
        require(next != address(0), "EX: zero");
        owner = next;
    }

    // ---------------- Views ----------------
    function getOrder(uint256 id) external view returns (Order memory) {
        return orders[id];
    }

    function openOrdersCount() external view returns (uint256) {
        return openOrderIds.length;
    }

    function getOpenOrders(uint256 offset, uint256 limit)
        external view returns (Order[] memory result, uint256[] memory ids)
    {
        uint256 n = openOrderIds.length;
        if (offset >= n) {
            return (new Order[](0), new uint256[](0));
        }
        uint256 end = offset + limit;
        if (end > n) end = n;

        uint256 count = 0;
        for (uint256 i = offset; i < end; i++) {
            if (orders[openOrderIds[i]].status == 0) count++;
        }

        result = new Order[](count);
        ids    = new uint256[](count);
        uint256 j = 0;
        for (uint256 i = offset; i < end; i++) {
            uint256 oid = openOrderIds[i];
            if (orders[oid].status == 0) {
                result[j] = orders[oid];
                ids[j]    = oid;
                j++;
            }
        }
    }
}
3) backend/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.32.0
web3==6.20.0
eth-account==0.11.3
python-dotenv==1.0.1
pydantic==2.9.2
4) backend/config.py
"""Configuração via variáveis de ambiente."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ---- Rede ----
    RPC_URL: str = os.getenv(
        "BRN_RPC_URL", "https://rpc-amoy.polygon.technology")
    CHAIN_ID: int = int(os.getenv("BRN_CHAIN_ID", "80002"))
    GAS_PRICE_GWEI: float = float(os.getenv("BRN_GAS_PRICE_GWEI", "30"))

    # ---- Contratos ----
    BRN_TOKEN_ADDRESS: str = os.getenv("BRN_TOKEN_ADDRESS", "")
    BRN_EXCHANGE_ADDRESS: str = os.getenv("BRN_EXCHANGE_ADDRESS", "")
    USDC_ADDRESS: str = os.getenv("BRN_USDC_ADDRESS", "")

    # ---- Operador (hot wallet) ----
    OPERATOR_PRIVATE_KEY: str = os.getenv("BRN_OPERATOR_PRIVATE_KEY", "")
    OPERATOR_USDC_ADDRESS: str = os.getenv("BRN_OPERATOR_USDC_ADDRESS", "")

    # ---- Watcher ----
    WATCHER_POLL_SECONDS: float = float(
        os.getenv("BRN_WATCHER_POLL", "5"))
    MIN_CONFIRMATIONS: int = int(
        os.getenv("BRN_MIN_CONFIRMATIONS", "1"))

    # ---- Servidor ----
    HOST: str = os.getenv("BRN_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("BRN_PORT", "8000"))
    DB_PATH: str = os.getenv("BRN_DB_PATH", "brn_exchange.db")

    @classmethod
    def validate(cls) -> list[str]:
        missing = []
        for name in (
            "BRN_TOKEN_ADDRESS", "BRN_EXCHANGE_ADDRESS", "USDC_ADDRESS",
            "OPERATOR_PRIVATE_KEY", "OPERATOR_USDC_ADDRESS",
        ):
            if not getattr(cls, name):
                missing.append(name)
        return missing


cfg = Config()
5) backend/db.py
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
Tokens:
Input 30251
·
Output 4096
·
Cache Read 23040
·
Cost $0.007064369999
[Vendedor]                              [Comprador]
   │                                        │
   │ 1. Coloca ordem: VENDO 100 BRN        │
   │    por 0.50 USDC/BRN                   │
   │    + endereço USDC de recebimento      │
   │                                        │
   │ → 100 BRN são TRAVADOS (escrow)        │
   │   no banco local                       │
   │                                        │
   │                         2. Vê a ordem │
   │                         3. Envia USDC │
   │                            (50 USDC)  │
   │                            no MetaMask│
   │                            para o      │
   │                            endereço do │
   │                            vendedor    │
   │                                        │
   │                         4. Cola o hash │
   │                            da tx no GUI│
   │                                        │
   │        5. Nó consulta o RPC da Polygon │
   │           confere se o Transfer USDC   │
   │           foi pago corretamente        │
   │                                        │
   │        6. Libera os 100 BRN travados   │
   │           → crédita no comprador       │
   │                                        │
   │        7. Ordem marcada como FILLED    │




[Vendedor]                          [VOCÊ - OPERADOR]              [Comprador]
    │                                      │                            │
    │ 1. Coloca ordem: 100 BRN a 0.5      │                            │
    │    + endereço USDC dele             │                            │
    │                                      │                            │
    │ ── BRN vai pro SEU wallet ─────────►│                            │
    │                                      │                            │
    │                                      │◄── 2. Comprador envia ────│
    │                                      │    USDC pro SEU wallet    │
    │                                      │                            │
    │                                      │ 3. Você confirma e:      │
    │◄── 4. USDC vai pro vendedor ────────│                            │
    │                                      │──── 5. BRN vai pro ──────►│
    │                                      │       comprador            │
