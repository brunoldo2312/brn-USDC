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
