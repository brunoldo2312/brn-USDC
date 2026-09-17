#!/usr/bin/env python3
"""
Servidor WebSocket + HTTP para a Carteira BRN P2P.
- Serve arquivos estaticos (index.html, app.js)
- Mural P2P sincronizado via WebSocket em /ws
- Tunel Ngrok OPCIONAL para acesso de qualquer lugar
Requer: pip install aiohttp pyngrok
"""

import asyncio
import json
import os
import sys
import time
import logging
from aiohttp import web, WSMsgType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("brn-p2p")

# ---------------------------------------------------------------------------
# Configuracoes
# ---------------------------------------------------------------------------
RATE_JANELA = 10
RATE_MAX = 60
EXPIRE_PADRAO = 86400
NGROK_TOKEN_FILE = "ngrok_token.txt"

# Detecta se esta rodando como .exe (PyInstaller) ou como .py
if getattr(sys, 'frozen', False):
    DIR = sys._MEIPASS
else:
    DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Estado em memoria
# ---------------------------------------------------------------------------
MURAL: dict = {}
CLIENTES_WS: set = set()
LOCK = asyncio.Lock()
RATE_LIMIT: dict = {}
TUNEL = None  # NgrokTunnel global


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
    agora = int(time.time())
    ativas = [o for o in MURAL.values() if o.get("expiracao", 0) > agora]
    return web.json_response({"ordens": ativas, "total": len(ativas)})


async def health_handler(request):
    public_url = TUNEL.public_url if TUNEL else None
    return web.json_response({
        "status": "ok",
        "clientes_ws": len(CLIENTES_WS),
        "ordens_ativas": len(MURAL),
        "public_url": public_url,
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
    if not isinstance(ordem, dict):
        return False, "Ordem nao e um objeto"
    for campo in CAMPOS_OBRIGATORIOS:
        if campo not in ordem or not ordem[campo]:
            return False, f"Campo obrigatorio ausente: {campo}"
    end = ordem.get("contratoAddress", "")
    if not (isinstance(end, str) and end.startswith("0x") and len(end) == 42):
        return False, "contratoAddress invalido"
    if ordem["expiracao"] <= int(time.time()):
        return False, "Ordem ja expirada"
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

            # PUBLICAR ORDEM
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

            # CANCELAR ORDEM
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

            # ORDEM EXECUTADA
            elif tipo == "ordem_executada":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                tx = dados.get("txHash", "")
                async with LOCK:
                    MURAL.pop(h, None)
                log.info(f"[MURAL] Ordem executada {h[:10]}...")
                await broadcast({"tipo": "ordem_executada", "hash": h, "txHash": tx})

            # PEDIR SNAPSHOT
            elif tipo == "pedir_snapshot":
                agora = int(time.time())
                snapshot = [o for o in MURAL.values() if o.get("expiracao", 0) > agora]
                await ws.send_json({"tipo": "snapshot", "ordens": snapshot})

            # PING
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
# Startup / Shutdown
# ---------------------------------------------------------------------------
async def iniciar_tasks(app):
    global TUNEL
    app["task_limpeza"] = asyncio.create_task(tarefa_limpeza(app))
    log.info("[STARTUP] Tasks iniciadas")

    # Inicia Ngrok se tiver token
    token_path = os.path.join(DIR, NGROK_TOKEN_FILE)
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if token:
                from ngrok_tunnel import NgrokTunnel
                port = int(os.environ.get("PORT", 8080))
                TUNEL = NgrokTunnel(token=token, target=f"http://localhost:{port}")
                public_url = TUNEL.start()
                print()
                print("=" * 70)
                print("  🌐 ACESSO PUBLICO ATIVO (NGROK)")
                print("=" * 70)
                print(f"  Compartilhe esta URL: {public_url}")
                print(f"  Qualquer pessoa no mundo pode acessar.")
                print("=" * 70)
                print()
        except Exception as e:
            log.error(f"[NGROK] Falha ao iniciar tunel: {e}")
            print()
            print(f"  ⚠️  NGROK falhou: {e}")
            print(f"  O servidor continua funcionando localmente.")
            print()


async def parar_tasks(app):
    global TUNEL
    task = app.get("task_limpeza")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    if TUNEL:
        TUNEL.close()
        TUNEL = None

    log.info("[SHUTDOWN] Tasks finalizadas")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
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
    import threading
    import webbrowser

    port = int(os.environ.get("PORT", 8080))

    print("=" * 70)
    print("  CARTEIRA BRN P2P - Servidor WebSocket/HTTP")
    print("=" * 70)
    print(f"  HTTP local:  http://localhost:{port}")
    print(f"  WebSocket:   ws://localhost:{port}/ws")
    print(f"  Health:      http://localhost:{port}/api/health")
    print("=" * 70)
    print()

    # Abre navegador apenas localmente
    def abrir_navegador():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=abrir_navegador, daemon=True).start()

    web.run_app(criar_app(), host="0.0.0.0", port=port)
