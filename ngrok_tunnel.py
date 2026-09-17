"""
Modulo de tunel NGROK para expor o servidor local na internet.
Requer: pip install pyngrok

Compativel com pyngrok antigo (parametro hostname) e novo (parametro domain).
"""
from __future__ import annotations
import logging

log = logging.getLogger("brn.ngrok")


class NgrokTunnel:
    def __init__(self, token: str, target: str = "http://localhost:8080",
                 domain: str | None = None):
        if not token or not token.strip():
            raise ValueError("Token NGROK vazio")
        self._token = token.strip()
        self._target = target
        self._domain = domain
        self._tunnel = None
        self._public_url = None

    def start(self) -> str:
        try:
            from pyngrok import ngrok, conf
        except ImportError as e:
            raise RuntimeError(
                "pyngrok nao instalado. Rode: pip install pyngrok"
            ) from e

        # IMPORTANTE: limpa qualquer configuracao anterior do ngrok
        try:
            ngrok.kill()
        except Exception:
            pass

        conf.get_default().auth_token = self._token

        base_kwargs = {"schemes": ["https"]}

        # Monta a lista de tentativas: domain (novo), hostname (antigo), e
        # por fim sem dominio fixo como ultimo recurso.
        tentativas: list[dict] = []
        if self._domain:
            tentativas.append({**base_kwargs, "domain": self._domain})
            tentativas.append({**base_kwargs, "hostname": self._domain})
        tentativas.append(base_kwargs)

        ultimo_erro = None
        for kwargs in tentativas:
            try:
                log.info(f"[NGROK] Tentando conectar com {list(kwargs.keys())}...")
                self._tunnel = ngrok.connect(self._target, **kwargs)
                self._public_url = self._tunnel.public_url
                log.warning("ngrok.up | public_url=%s | local=%s",
                            self._public_url, self._target)
                return self._public_url
            except TypeError as e:
                # pyngrok nao aceita esse parametro -> tenta o proximo
                log.info(f"[NGROK] Parametro nao suportado, tentando outro: {e}")
                ultimo_erro = e
                continue
            except Exception as e:
                # Erro de rede / dominio ocupado / etc
                log.warning(f"[NGROK] Falha com {list(kwargs.keys())}: {e}")
                ultimo_erro = e
                continue

        raise RuntimeError(f"Falha ao iniciar ngrok: {ultimo_erro}")

    def close(self):
        if self._tunnel is not None:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(self._tunnel.public_url)
                ngrok.kill()
                log.info("ngrok.down")
            except Exception as e:
                log.warning("ngrok.close_failed | err=%s", str(e))
        self._tunnel = None
        self._public_url = None

    @property
    def public_url(self) -> str | None:
        return self._public_url
