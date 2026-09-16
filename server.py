#!/usr/bin/env python3
"""
Servidor WebSocket + HTTP para a Carteira BRN P2P.
Requer: pip install aiohttp
Execucao: python server.py
Acesse: http://localhost:8080
"""

import asyncio
import json
import os
import time
import logging
from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("brn-p2p")

# ---------------------------------------------------------------------------
# Configuracoes
# ---------------------------------------------------------------------------
RATE_JANELA = 10     # segundos
RATE_MAX = 60        # requisicoes por janela (mais permissivo)
EXPIRE_PADRAO = 86400  # 24h

# ---------------------------------------------------------------------------
# Estado em memoria
# ---------------------------------------------------------------------------
MURAL: dict = {}
CLIENTES_WS: set = set()
LOCK = asyncio.Lock()
RATE_LIMIT: dict = {}

DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Handlers HTTP
# ---------------------------------------------------------------------------
async def index_handler(request):
    return web.FileResponse(os.path.join(DIR, "index.html"))


async def app_js_handler(request):
    return web.FileResponse(os.path.join(DIR, "app.js"))


async def mural_rest_handler(request):
    """Fallback REST: retorna as ordens ativas."""
    agora = int(time.time())
    ativas = [o for o in MURAL.values() if o.get("expiracao", 0) > agora]
    return web.json_response({"ordens": ativas, "total": len(ativas)})


async def health_handler(request):
    """Health check."""
    return web.json_response({
        "status": "ok",
        "clientes_ws": len(CLIENTES_WS),
        "ordens_ativas": len(MURAL),
        "timestamp": int(time.time())
    })


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------
def checar_rate_limit(ip: str) -> bool:
    agora = time.time()
    hist = RATE_LIMIT.setdefault(ip, [])
    hist[:] = [t for t in hist if agora - t < RATE_JANELA]
    if len(hist) >= RATE_MAX:
        return False
    hist.append(agora)
    return True


# ---------------------------------------------------------------------------
# Validacao de ordem
# ---------------------------------------------------------------------------
CAMPOS_OBRIGATORIOS = [
    "hash", "criador", "contratoAddress",
    "valorOferecido", "valorDesejado", "expiracao"
]

def validar_ordem(ordem: dict) -> tuple:
    """Retorna (valida, mensagem_erro)."""
    if not isinstance(ordem, dict):
        return False, "Ordem nao e um objeto"

    for campo in CAMPOS_OBRIGATORIOS:
        if campo not in ordem or not ordem[campo]:
            return False, f"Campo obrigatorio ausente: {campo}"

    # Validacao de endereco Ethereum (0x + 40 hex)
    end = ordem.get("contratoAddress", "")
    if not (isinstance(end, str) and end.startswith("0x") and len(end) == 42):
        return False, "contratoAddress invalido"

    # Expiracao no futuro
    if ordem["expiracao"] <= int(time.time()):
        return False, "Ordem ja expirada"

    # Valores positivos
    try:
        if float(ordem["valorOferecido"]) <= 0 or float(ordem["valorDesejado"]) <= 0:
            return False, "Valores devem ser positivos"
    except (ValueError, TypeError):
        return False, "Valores invalidos"

    return True, ""


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    ip = request.remote or "unknown"

    async with LOCK:
        CLIENTES_WS.add(ws)
    log.info(f"[WS] Conectado: {ip} (total={len(CLIENTES_WS)})")

    # Envia snapshot inicial
    agora = int(time.time())
    snapshot = [o for o in MURAL.values() if o.get("expiracao", 0) > agora]
    await ws.send_json({"tipo": "snapshot", "ordens": snapshot})

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                if msg.type == WSMsgType.ERROR:
                    log.error(f"[WS] Erro: {ws.exception()}")
                continue

            try:
                dados = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"tipo": "erro", "msg": "JSON invalido"})
                continue

            tipo = dados.get("tipo")

            # --------- PUBLICAR ORDEM ---------
            if tipo == "publicar_ordem":
                if not checar_rate_limit(ip):
                    await ws.send_json({"tipo": "erro", "msg": "Rate limit excedido"})
                    continue

                ordem = dados.get("ordem")
                valida, msg_erro = validar_ordem(ordem)
                if not valida:
                    await ws.send_json({"tipo": "erro", "msg": msg_erro})
                    continue

                async with LOCK:
                    MURAL[ordem["hash"]] = ordem
                log.info(f"[MURAL] Nova ordem {ordem['hash'][:10]}...")
                await broadcast({"tipo": "nova_ordem", "ordem": ordem})

            # --------- CANCELAR ORDEM ---------
            elif tipo == "cancelar_ordem":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                async with LOCK:
                    removida = MURAL.pop(h, None)
                if removida:
                    log.info(f"[MURAL] Ordem cancelada {h[:10]}...")
                    await broadcast({"tipo": "ordem_cancelada", "hash": h})
                else:
                    await ws.send_json({"tipo": "erro", "msg": "Ordem nao encontrada"})

            # --------- ORDEM EXECUTADA ---------
            elif tipo == "ordem_executada":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                tx = dados.get("txHash", "")
                async with LOCK:
                    removida = MURAL.pop(h, None)
                if removida:
                    log.info(f"[MURAL] Ordem executada {h[:10]}...")
                    await broadcast({"tipo": "ordem_executada", "hash": h, "txHash": tx})

            # --------- PEDIR SNAPSHOT (CORRIGIDO) ---------
            elif tipo == "pedir_snapshot":
                agora = int(time.time())
                snapshot = [o for o in MURAL.values() if o.get("expiracao", 0) > agora]
                await ws.send_json({"tipo": "snapshot", "ordens": snapshot})

            # --------- PING ---------
            elif tipo == "ping":
                await ws.send_json({"tipo": "pong", "ts": int(time.time())})

            else:
                await ws.send_json({"tipo": "erro", "msg": f"Tipo desconhecido: {tipo}"})

    finally:
        async with LOCK:
            CLIENTES_WS.discard(ws)
        log.info(f"[WS] Desconectado: {ip} (total={len(CLIENTES_WS)})")

    return ws


async def broadcast(mensagem: dict):
    if not CLIENTES_WS:
        return
    payload = json.dumps(mensagem)
    async with LOCK:
        clientes = list(CLIENTES_WS)
    for ws in clientes:
        try:
            await ws.send_str(payload)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Limpeza periodica
# ---------------------------------------------------------------------------
async def tarefa_limpeza(app):
    log.info("[LIMPEZA] Task iniciada")
    try:
        while True:
            await asyncio.sleep(60)
            agora = int(time.time())
            async with LOCK:
                expiradas = [h for h, o in MURAL.items() if o.get("expiracao", 0) <= agora]
                for h in expiradas:
                    MURAL.pop(h, None)
            for h in expiradas:
                await broadcast({"tipo": "ordem_expirada", "hash": h})
            if expiradas:
                log.info(f"[LIMPEZA] Removidas {len(expiradas)} ordens expiradas")
    except asyncio.CancelledError:
        log.info("[LIMPEZA] Task cancelada")
        raise


# ---------------------------------------------------------------------------
# Bootstrap (ESTAVA FALTANDO!)
# ---------------------------------------------------------------------------
async def iniciar_tasks(app):
    app["task_limpeza"] = asyncio.create_task(tarefa_limpeza(app))
    log.info("[STARTUP] Tasks iniciadas")


async def parar_tasks(app):
    task = app.get("task_limpeza")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("[SHUTDOWN] Tasks finalizadas")


def criar_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", index_handler)
    app.router.add_get("/app.js", app_js_handler)
    app.router.add_get("/api/mural", mural_rest_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(iniciar_tasks)
    app.on_cleanup.append(parar_tasks)
    return app


if __name__ == "__main__":
    print("=" * 60)
    print("  CARTEIRA BRN P2P - Servidor WebSocket/HTTP")
    print("  HTTP:      http://localhost:8080")
    print("  WebSocket: ws://localhost:8080/ws")
    print("  Health:    http://localhost:8080/api/health")
    print("=" * 60)
    web.run_app(criar_app(), host="0.0.0.0", port=8080)
