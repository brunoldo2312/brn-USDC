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
NGROK_TOKEN_FILE = "ngrok_token.txt"
NGROK_DOMAIN_FILE = "ngrok_domain.txt"

# Quando empacotado (PyInstaller) -> sys._MEIPASS (bundle interno)
# Quando rodando como .py -> pasta do próprio arquivo
if getattr(sys, "frozen", False):
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
    return web.FileResponse(
        os.path.join(DIR, "app.js"),
        headers={"Content-Type": "application/javascript; charset=utf-8"},
    )


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
        "timestamp": int(time.time()),
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
    "valorOferecido", "valorDesejado", "expiracao",
]


def validar_ordem(ordem: dict):
    if not isinstance(ordem, dict):
        return False, "Ordem nao e um objecto"
    for campo in CAMPOS_OBRIGATORIOS:
        if campo not in ordem or not ordem[campo]:
            return False, f"Campo obrigatorio ausente: {campo}"
    end = ordem.get("contratoAddress", "")
    if not (isinstance(end, str) and end.startswith("0x") and len(end) == 42):
        return False, "contratoAddress invalido"
    try:
        if int(ordem["expiracao"]) <= int(time.time()):
            return False, "Ordem ja expirada"
    except (ValueError, TypeError):
        return False, "expiracao invalida"
    try:
        if float(ordem["valorOferecido"]) <= 0 or float(ordem["valorDesejado"]) <= 0:
            return False, "Valores devem ser positivos"
    except (ValueError, TypeError):
        return False, "Valores invalidos"
    return True, ""


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------
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

            elif tipo == "cancelar_ordem":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                async with LOCK:
                    removida = MURAL.pop(h, None)
                if removida:
                    log.info(f"[MURAL] Cancelada {h[:10]}...")
                    await broadcast({"tipo": "ordem_cancelada", "hash": h})

            elif tipo == "ordem_executada":
                h = dados.get("hash")
                if not h:
                    await ws.send_json({"tipo": "erro", "msg": "Hash ausente"})
                    continue
                tx = dados.get("txHash", "")
                async with LOCK:
                    MURAL.pop(h, None)
                log.info(f"[MURAL] Executada {h[:10]}...")
                await broadcast({"tipo": "ordem_executada", "hash": h, "txHash": tx})

            elif tipo == "pedir_snapshot":
                agora2 = int(time.time())
                snap = [o for o in MURAL.values() if o.get("expiracao", 0) > agora2]
                await ws.send_json({"tipo": "snapshot", "ordens": snap})

            elif tipo == "ping":
                await ws.send_json({"tipo": "pong", "ts": int(time.time())})

            else:
                # Ignora tipos desconhecidos (evita loop)
                pass

    finally:
        async with LOCK:
            CLIENTES_WS.discard(ws)
        log.info(f"[WS] Desconectado: {ip} (total={len(CLIENTES_WS)})")

    return ws


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
        log.info("[LIMPEZA] Cancelada")
        raise


# ---------------------------------------------------------------------------
# Localiza os arquivos .txt corretamente (.py ou .exe)
# ---------------------------------------------------------------------------
def _pasta_config():
    """
    - Rodando como .py    -> pasta do próprio server.py
    - Rodando como .exe   -> pasta onde está o .exe (não o bundle temporário)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
async def iniciar_tasks(app):
    global TUNEL
    app["task_limpeza"] = asyncio.create_task(tarefa_limpeza(app))
    log.info("[STARTUP] Tasks iniciadas")

    # 1) Variáveis de ambiente têm prioridade (útil para deploy)
    token  = os.environ.get("NGROK_TOKEN")
    domain = os.environ.get("NGROK_DOMAIN")

    # 2) Se não vieram do ambiente, procura os .txt ao lado do .exe / .py
    if not token:
        base = _pasta_config()
        token_path  = os.path.join(base, NGROK_TOKEN_FILE)
        domain_path = os.path.join(base, NGROK_DOMAIN_FILE)
        log.info(f"[NGROK] Procurando token em: {token_path}")

        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    token = f.read().strip()
            except Exception as e:
                log.error(f"[NGROK] Falha lendo token: {e}")

        if not domain and os.path.exists(domain_path):
            try:
                with open(domain_path, "r", encoding="utf-8") as f:
                    domain = f.read().strip() or None
            except Exception as e:
                log.error(f"[NGROK] Falha lendo domain: {e}")

    if not token:
        log.warning("[NGROK] Token nao encontrado - modo local apenas")
        return

    try:
        from ngrok_tunnel import NgrokTunnel
        port = int(os.environ.get("PORT", 8080))
        TUNEL = NgrokTunnel(
            token=token,
            target=f"http://localhost:{port}",
            domain=domain,
        )
        url = TUNEL.start()
        log.info(f"[NGROK] URL publica: {url}")
    except Exception as e:
        log.error(f"[NGROK] Falha ao iniciar tunel: {e}")
        TUNEL = None


async def parar_tasks(app):
    task = app.get("task_limpeza")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    global TUNEL
    if TUNEL:
        try:
            TUNEL.close()
        except Exception as e:
            log.warning(f"[SHUTDOWN] Falha fechando ngrok: {e}")
        TUNEL = None
    log.info("[SHUTDOWN] Encerrado")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
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
    port = int(os.environ.get("PORT", 8080))
    log.info(f"Servidor iniciando em http://localhost:{port}")
    web.run_app(criar_app(), host="0.0.0.0", port=port, print=None)
