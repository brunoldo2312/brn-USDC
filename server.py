"""
server.py — BRN P2P com mural HÍBRIDO (off-chain + on-chain)

- Mural off-chain: memória + SQLite (persistente entre reinícios)
- Mural on-chain: indexador de eventos via eth_getLogs
- WebSocket: broadcast unificado dos dois murais
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
import logging
from pathlib import Path
from aiohttp import web, WSMsgType, ClientSession
from eth_hash.auto import keccak

# ============================================================
# Paths & Config
# ============================================================
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


BASE_DIR = _base_dir()
DB_PATH = BASE_DIR / "mural.db"
NGROK_TOKEN_FILE = BASE_DIR / "ngrok_token.txt"
NGROK_DOMAIN_FILE = BASE_DIR / "ngrok_domain.txt"

CONFIG = {
    "RPC_URL": os.environ.get("POLYGON_RPC", "https://polygon-rpc.com"),
    "CONTRACT_ADDRESS": os.environ.get("CONTRACT_ADDRESS", "").strip().lower(),
    "BLOCO_INICIAL": int(os.environ.get("BLOCO_INICIAL", "0")),
    "INTERVALO_INDEX": int(os.environ.get("INTERVALO_INDEX", "15")),
    "BLOCO_POR_VEZ": int(os.environ.get("BLOCO_POR_VEZ", "3500")),
    "PORT": int(os.environ.get("PORT", "8080")),
    "RATE_JANELA": 10,
    "RATE_MAX": 60,
}


def _topic(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()


TOPIC_ORDEM_PUBLICADA = _topic(
    "OrdemPublicada(bytes32,address,uint256,uint256,uint256,uint256,bytes)"
)
TOPIC_ORDEM_EXECUTADA = _topic(
    "OrdemExecutada(bytes32,address,address,uint256,uint256)"
)
TOPIC_ORDEM_CANCELADA = _topic("OrdemCancelada(address,uint256)")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("brn-p2p")

# ============================================================
# Estado global
# ============================================================
MURAL_OFFCHAIN: dict[str, dict] = {}
MURAL_ONCHAIN: dict[str, dict] = {}
CLIENTES_WS: set = set()
LOCK = asyncio.Lock()
RATE_LIMIT: dict[str, list[float]] = {}
TUNEL = None
ULTIMO_BLOCO = 0
HTTP_SESSION: ClientSession | None = None

# ============================================================
# Persistência SQLite
# ============================================================
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    conn = db_connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ordens_offchain (
            hash TEXT PRIMARY KEY,
            criador TEXT NOT NULL,
            contrato_address TEXT NOT NULL,
            valor_oferecido TEXT NOT NULL,
            valor_desejado TEXT NOT NULL,
            valor_usdc TEXT NOT NULL,
            cotacao TEXT NOT NULL,
            nonce TEXT NOT NULL,
            expiracao INTEGER NOT NULL,
            assinatura TEXT NOT NULL,
            chain_id INTEGER NOT NULL,
            criado_em INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_expiracao ON ordens_offchain(expiracao);
        CREATE TABLE IF NOT EXISTS estado (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def db_salvar_ordem_offchain(o: dict):
    conn = db_connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO ordens_offchain
            (hash, criador, contrato_address, valor_oferecido, valor_desejado,
             valor_usdc, cotacao, nonce, expiracao, assinatura, chain_id, criado_em)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                o["hash"],
                o["criador"].lower(),
                o["contratoAddress"].lower(),
                o["valorOferecido"],
                o["valorDesejado"],
                o["valorUSDC"],
                o["cotacao"],
                o["nonce"],
                int(o["expiracao"]),
                o["assinatura"],
                int(o.get("chainId", 137)),
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def db_remover_ordem_offchain(h: str):
    conn = db_connect()
    try:
        conn.execute("DELETE FROM ordens_offchain WHERE hash = ?", (h,))
        conn.commit()
    finally:
        conn.close()


def db_carregar_ordens_offchain() -> list[dict]:
    conn = db_connect()
    try:
        rows = conn.execute("SELECT * FROM ordens_offchain").fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "hash": r["hash"],
                    "criador": r["criador"],
                    "contratoAddress": r["contrato_address"],
                    "valorOferecido": r["valor_oferecido"],
                    "valorDesejado": r["valor_desejado"],
                    "valorUSDC": r["valor_usdc"],
                    "cotacao": r["cotacao"],
                    "nonce": r["nonce"],
                    "expiracao": r["expiracao"],
                    "assinatura": r["assinatura"],
                    "chainId": r["chain_id"],
                }
            )
        return out
    finally:
        conn.close()


def db_limpar_expiradas():
    agora = int(time.time())
    conn = db_connect()
    try:
        cur = conn.execute("DELETE FROM ordens_offchain WHERE expiracao <= ?", (agora,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def db_estado_get(chave: str, default=None):
    conn = db_connect()
    try:
        row = conn.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
        return row["valor"] if row else default
    finally:
        conn.close()


def db_estado_set(chave: str, valor: str):
    conn = db_connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO estado (chave, valor) VALUES (?, ?)",
            (chave, str(valor)),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# CORS
# ============================================================
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ============================================================
# HTTP handlers
# ============================================================
async def index_handler(request):
    return web.FileResponse(BASE_DIR / "index.html")


async def app_js_handler(request):
    return web.FileResponse(
        BASE_DIR / "app.js",
        headers={"Content-Type": "application/javascript; charset=utf-8"},
    )


def _merge_murais() -> list[dict]:
    agora = int(time.time())
    merged: dict[str, dict] = {}

    for h, o in MURAL_OFFCHAIN.items():
        if o.get("expiracao", 0) > agora:
            merged[h] = {**o, "fontes": ["off-chain"]}

    for h, o in MURAL_ONCHAIN.items():
        if o.get("expiracao", 0) > agora:
            if h in merged:
                merged[h]["fontes"].append("on-chain")
            else:
                merged[h] = {**o, "fontes": ["on-chain"]}

    return sorted(merged.values(), key=lambda x: int(x.get("expiracao", 0)))


async def mural_rest_handler(request):
    ordens = _merge_murais()
    return web.json_response(
        {
            "ordens": ordens,
            "total": len(ordens),
            "offchain": sum(1 for o in ordens if "off-chain" in o["fontes"]),
            "onchain": sum(1 for o in ordens if "on-chain" in o["fontes"]),
        }
    )


async def health_handler(request):
    return web.json_response(
        {
            "status": "ok",
            "clientes_ws": len(CLIENTES_WS),
            "offchain_total": len(MURAL_OFFCHAIN),
            "onchain_total": len(MURAL_ONCHAIN),
            "ultimo_bloco_indexado": ULTIMO_BLOCO,
            "contrato": CONFIG["CONTRACT_ADDRESS"],
            "public_url": TUNEL.public_url if TUNEL else None,
            "timestamp": int(time.time()),
        }
    )


# ============================================================
# Rate limit
# ============================================================
def checar_rate_limit(ip: str) -> bool:
    agora = time.time()
    hist = RATE_LIMIT.setdefault(ip, [])
    hist[:] = [t for t in hist if agora - t < CONFIG["RATE_JANELA"]]
    if len(hist) >= CONFIG["RATE_MAX"]:
        return False
    hist.append(agora)
    return True


# ============================================================
# Validação
# ============================================================
CAMPOS_OBRIGATORIOS = [
    "hash", "criador", "contratoAddress",
    "valorOferecido", "valorDesejado",
    "valorUSDC", "cotacao", "nonce", "expiracao", "assinatura",
]


def validar_ordem(ordem: dict) -> tuple[bool, str]:
    if not isinstance(ordem, dict):
        return False, "Ordem nao e um objecto"
    for campo in CAMPOS_OBRIGATORIOS:
        if campo not in ordem or ordem[campo] in (None, ""):
            return False, f"Campo ausente: {campo}"

    contrato = str(ordem["contratoAddress"]).lower()
    if CONFIG["CONTRACT_ADDRESS"] and contrato != CONFIG["CONTRACT_ADDRESS"]:
        return False, "contratoAddress nao corresponde ao contrato configurado"
    if not (contrato.startswith("0x") and len(contrato) == 42):
        return False, "contratoAddress invalido"

    criador = str(ordem["criador"]).lower()
    if not (criador.startswith("0x") and len(criador) == 42):
        return False, "criador invalido"

    sig = str(ordem["assinatura"])
    if not (sig.startswith("0x") and len(sig) == 132):
        return False, "assinatura deve ter 65 bytes (132 hex)"

    try:
        if int(ordem["expiracao"]) <= int(time.time()):
            return False, "Ordem ja expirada"
    except (ValueError, TypeError):
        return False, "expiracao invalida"

    for c in ("valorUSDC", "cotacao", "nonce"):
        try:
            if int(ordem[c]) <= 0:
                return False, f"{c} deve ser positivo"
        except (ValueError, TypeError):
            return False, f"{c} invalido"

    return True, ""


# ============================================================
# Broadcast
# ============================================================
async def broadcast(mensagem: dict):
    if not CLIENTES_WS:
        return
    payload = json.dumps(mensagem)
    async with LOCK:
        clientes = list(CLIENTES_WS)
    mortos = []
    for ws in clientes:
        try:
            await ws.send_str(payload)
        except Exception:
            mortos.append(ws)
    if mortos:
        async with LOCK:
            for ws in mortos:
                CLIENTES_WS.discard(ws)


# ============================================================
# WebSocket
# ============================================================
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1024 * 256)
    await ws.prepare(request)
    ip = request.remote or "unknown"

    async with LOCK:
        CLIENTES_WS.add(ws)
    log.info(f"[WS] conectado {ip} (total={len(CLIENTES_WS)})")

    await ws.send_json({"tipo": "snapshot", "ordens": _merge_murais()})

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                if msg.type == WSMsgType.ERROR:
                    log.error(f"[WS] erro: {ws.exception()}")
                continue

            try:
                dados = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"tipo": "erro", "msg": "JSON invalido"})
                continue

            tipo = dados.get("tipo")

            if tipo == "publicar_ordem":
                if not checar_rate_limit(ip):
                    await ws.send_json({"tipo": "erro", "msg": "Rate limit"})
                    continue
                ordem = dados.get("ordem")
                valida, msg_erro = validar_ordem(ordem)
                if not valida:
                    await ws.send_json({"tipo": "erro", "msg": msg_erro})
                    continue
                ordem["criador"] = ordem["criador"].lower()
                ordem["contratoAddress"] = ordem["contratoAddress"].lower()
                async with LOCK:
                    MURAL_OFFCHAIN[ordem["hash"]] = ordem
                db_salvar_ordem_offchain(ordem)
                log.info(f"[MURAL-OC] +{ordem['hash'][:12]}...")
                await broadcast({"tipo": "nova_ordem", "ordem": {**ordem, "fontes": ["off-chain"]}})

            elif tipo == "cancelar_ordem":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                async with LOCK:
                    removida = MURAL_OFFCHAIN.pop(h, None)
                if removida:
                    db_remover_ordem_offchain(h)
                    await broadcast({"tipo": "ordem_cancelada", "hash": h})

            elif tipo == "ordem_executada":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                tx = dados.get("txHash", "")
                async with LOCK:
                    MURAL_OFFCHAIN.pop(h, None)
                db_remover_ordem_offchain(h)
                await broadcast({"tipo": "ordem_executada", "hash": h, "txHash": tx})

            elif tipo == "pedir_snapshot":
                await ws.send_json({"tipo": "snapshot", "ordens": _merge_murais()})

            elif tipo == "ping":
                await ws.send_json({"tipo": "pong", "ts": int(time.time())})

    finally:
        async with LOCK:
            CLIENTES_WS.discard(ws)
        log.info(f"[WS] desconectado {ip} (total={len(CLIENTES_WS)})")

    return ws


# ============================================================
# JSON-RPC helpers (eth_getLogs, eth_blockNumber)
# ============================================================
async def rpc_call(method: str, params: list):
    if HTTP_SESSION is None:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with HTTP_SESSION.post(CONFIG["RPC_URL"], json=payload, timeout=20) as r:
            data = await r.json()
            if "error" in data:
                log.warning(f"[RPC] {method}: {data['error']}")
                return None
            return data.get("result")
    except Exception as e:
        log.warning(f"[RPC] {method} falhou: {e}")
        return None


async def rpc_block_number() -> int:
    res = await rpc_call("eth_blockNumber", [])
    return int(res, 16) if res else 0


async def rpc_get_logs(from_block: int, to_block: int, topics: list) -> list:
    params = [
        {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "address": CONFIG["CONTRACT_ADDRESS"],
            "topics": topics,
        }
    ]
    res = await rpc_call("eth_getLogs", params)
    return res if isinstance(res, list) else []


# ============================================================
# Decoder ABI (evento OrdemPublicada)
# ============================================================
def _decode_ordem_publicada(log_entry: dict) -> dict | None:
    try:
        topics = log_entry["topics"]
        data = log_entry["data"]
        if data.startswith("0x"):
            data = data[2:]

        hash_ordem = topics[1]
        criador = "0x" + topics[2][-40:]

        # 4 uint256 + 1 bytes dinâmico
        valor_usdc = int(data[0:64], 16)
        cotacao = int(data[64:128], 16)
        nonce = int(data[128:192], 16)
        expiracao = int(data[192:256], 16)
        # offset (bytes) para o campo bytes — sempre 160 aqui
        offset_bytes = int(data[256:320], 16)
        length_bytes = int(data[320:384], 16)
        sig_hex = data[384 : 384 + length_bytes * 2]
        assinatura = "0x" + sig_hex

        # sanity
        if offset_bytes != 160 or length_bytes != 65:
            log.warning(f"[DECODE] layout inesperado offset={offset_bytes} len={length_bytes}")

        return {
            "hash": hash_ordem,
            "criador": criador.lower(),
            "contratoAddress": CONFIG["CONTRACT_ADDRESS"],
            "valorOferecido": str(valor_usdc),
            "valorDesejado": str(cotacao),
            "valorUSDC": str(valor_usdc),
            "cotacao": str(cotacao),
            "nonce": str(nonce),
            "expiracao": expiracao,
            "assinatura": assinatura,
            "chainId": 137,
            "bloco": int(log_entry.get("blockNumber", "0x0"), 16),
        }
    except Exception as e:
        log.warning(f"[DECODE] falhou: {e}")
        return None


# ============================================================
# Indexador on-chain
# ============================================================
async def indexar_eventos():
    global ULTIMO_BLOCO
    if not CONFIG["CONTRACT_ADDRESS"]:
        log.warning("[INDEX] CONTRACT_ADDRESS nao configurado — on-chain desabilitado")
        return

    ultimo_salvo = db_estado_get("ultimo_bloco")
    ULTIMO_BLOCO = int(ultimo_salvo) if ultimo_salvo else CONFIG["BLOCO_INICIAL"]
    if ULTIMO_BLOCO == 0:
        # primeira vez: começa do bloco atual para não indexar a chain toda
        ULTIMO_BLOCO = await rpc_block_number()
        db_estado_set("ultimo_bloco", ULTIMO_BLOCO)
        log.info(f"[INDEX] primeira execucao, comecando do bloco {ULTIMO_BLOCO}")

    while True:
        try:
            atual = await rpc_block_number()
            if atual == 0:
                await asyncio.sleep(CONFIG["INTERVALO_INDEX"])
                continue

            if ULTIMO_BLOCO >= atual:
                await asyncio.sleep(CONFIG["INTERVALO_INDEX"])
                continue

            de = ULTIMO_BLOCO + 1
            ate = min(atual, de + CONFIG["BLOCO_POR_VEZ"] - 1)

            # Buscar os 3 tipos de evento de uma vez
            logs = await rpc_get_logs(
                de, ate,
                [[TOPIC_ORDEM_PUBLICADA, TOPIC_ORDEM_EXECUTADA, TOPIC_ORDEM_CANCELADA]],
            )

            novos = 0
            removidos = 0
            for lg in logs:
                topico0 = lg["topics"][0]
                if topico0 == TOPIC_ORDEM_PUBLICADA:
                    ordem = _decode_ordem_publicada(lg)
                    if ordem and ordem["expiracao"] > int(time.time()):
                        MURAL_ONCHAIN[ordem["hash"]] = ordem
                        novos += 1
                        await broadcast(
                            {"tipo": "nova_ordem", "ordem": {**ordem, "fontes": ["on-chain"]}}
                        )
                elif topico0 == TOPIC_ORDEM_EXECUTADA:
                    h = lg["topics"][1]
                    if h in MURAL_ONCHAIN:
                        MURAL_ONCHAIN.pop(h, None)
                        removidos += 1
                    async with LOCK:
                        MURAL_OFFCHAIN.pop(h, None)
                    db_remover_ordem_offchain(h)
                    await broadcast({"tipo": "ordem_executada", "hash": h, "txHash": lg.get("transactionHash", "")})

                elif topico0 == TOPIC_ORDEM_CANCELADA:
                    # evento: OrdemCancelada(address indexed criador, uint256 nonce)
                    criador = "0x" + lg["topics"][1][-40:]
                    nonce = int(lg["data"], 16)
                    # precisamos achar a ordem por (criador, nonce)
                    for h, o in list(MURAL_ONCHAIN.items()):
                        if o["criador"] == criador and int(o["nonce"]) == nonce:
                            MURAL_ONCHAIN.pop(h, None)
                            removidos += 1
                            await broadcast({"tipo": "ordem_cancelada", "hash": h})
                            break

            ULTIMO_BLOCO = ate
            db_estado_set("ultimo_bloco", ULTIMO_BLOCO)

            if novos or removidos:
                log.info(
                    f"[INDEX] blocos {de}-{ate}: +{novos} ordens, -{removidos} removidas"
                )

        except Exception as e:
            log.exception(f"[INDEX] erro: {e}")

        await asyncio.sleep(CONFIG["INTERVALO_INDEX"])


# ============================================================
# Task de limpeza (off-chain expiradas)
# ============================================================
async def tarefa_limpeza(app):
    while True:
        try:
            await asyncio.sleep(60)
            agora = int(time.time())

            async with LOCK:
                expiradas = [h for h, o in MURAL_OFFCHAIN.items() if o.get("expiracao", 0) <= agora]
                for h in expiradas:
                    MURAL_OFFCHAIN.pop(h, None)

            # on-chain também remove (mas mantém os eventos históricos)
            exp_onchain = [h for h, o in MURAL_ONCHAIN.items() if o.get("expiracao", 0) <= agora]
            for h in exp_onchain:
                MURAL_ONCHAIN.pop(h, None)

            removidas_db = db_limpar_expiradas()

            for h in expiradas:
                await broadcast({"tipo": "ordem_expirada", "hash": h})

            if expiradas or removidas_db:
                log.info(f"[LIMPEZA] off={len(expiradas)} on={len(exp_onchain)} db={removidas_db}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"[LIMPEZA] erro: {e}")


# ============================================================
# Startup / Shutdown
# ============================================================
async def iniciar_tasks(app):
    global TUNEL, HTTP_SESSION, ULTIMO_BLOCO

    # 1) HTTP session para JSON-RPC
    HTTP_SESSION = ClientSession()

    # 2) Carrega off-chain do SQLite
    db_init()
    for o in db_carregar_ordens_offchain():
        MURAL_OFFCHAIN[o["hash"]] = o
    log.info(f"[BOOT] {len(MURAL_OFFCHAIN)} ordens off-chain carregadas do SQLite")

    # 3) Limpeza inicial
    db_limpar_expiradas()

    # 4) Indexer on-chain
    app["task_index"] = asyncio.create_task(indexar_eventos())

    # 5) Limpeza periódica
    app["task_limpeza"] = asyncio.create_task(tarefa_limpeza(app))

    # 6) ngrok
    token = os.environ.get("NGROK_TOKEN")
    domain = os.environ.get("NGROK_DOMAIN")
    if not token and NGROK_TOKEN_FILE.exists():
        token = NGROK_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not domain and NGROK_DOMAIN_FILE.exists():
        domain = NGROK_DOMAIN_FILE.read_text(encoding="utf-8").strip() or None

    if not token or token.startswith("COLE_"):
        log.warning("[NGROK] token ausente — modo local apenas")
        return

    try:
        from ngrok_tunnel import NgrokTunnel
        TUNEL = NgrokTunnel(
            token=token,
            target=f"http://localhost:{CONFIG['PORT']}",
            domain=domain,
        )
        url = TUNEL.start()
        log.info(f"[NGROK] URL publica: {url}")
    except Exception as e:
        log.error(f"[NGROK] falha: {e}")
        TUNEL = None


async def parar_tasks(app):
    global TUNEL, HTTP_SESSION
    for k in ("task_index", "task_limpeza"):
        t = app.get(k)
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()

    if TUNEL:
        try:
            TUNEL.close()
        except Exception as e:
            log.warning(f"[SHUTDOWN] ngrok close: {e}")
        TUNEL = None

    log.info("[SHUTDOWN] concluido")


# ============================================================
# App factory
# ============================================================
def criar_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/index.html", index_handler)
    app.router.add_get("/app.js", app_js_handler)
    app.router.add_get("/api/mural", mural_rest_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(iniciar_tasks)
    app.on_cleanup.append(parar_tasks)
    return app


if __name__ == "__main__":
    log.info(f"Servidor em http://localhost:{CONFIG['PORT']}")
    log.info(f"Contrato configurado: {CONFIG['CONTRACT_ADDRESS'] or '(nenhum)'}")
    web.run_app(criar_app(), host="0.0.0.0", port=CONFIG["PORT"], print=None)
