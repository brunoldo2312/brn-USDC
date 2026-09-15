"""Criptografia e carteira BRN."""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def _derive_key(password: str, salt: bytes,
                iterations: int = 200_000) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, iterations, dklen=32
    )


def encrypt_private_key(priv_hex: str, password: str) -> tuple[str, str]:
    """Retorna (ciphertext_b64, salt_b64)."""
    if not _HAS_CRYPTO:
        raise RuntimeError(
            "Instale 'cryptography': pip install cryptography"
        )
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_key(password, salt)
    ct = AESGCM(key).encrypt(nonce, priv_hex.encode(), None)
    blob = nonce + ct
    return base64.b64encode(blob).decode(), base64.b64encode(salt).decode()


def decrypt_private_key(cipher_b64: str, salt_b64: str,
                        password: str) -> str:
    if not _HAS_CRYPTO:
        raise RuntimeError("Instale 'cryptography'.")
    blob = base64.b64decode(cipher_b64)
    salt = base64.b64decode(salt_b64)
    nonce, ct = blob[:12], blob[12:]
    key = _derive_key(password, salt)
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def generate_keypair() -> tuple[str, str]:
    """Retorna (private_hex, address). Endereço = hash(curta) da priv."""
    priv = secrets.token_bytes(32)
    addr = "brn1" + hashlib.sha256(priv).hexdigest()[:40]
    return priv.hex(), addr


@dataclass
class Wallet:
    address: str
    private_key: str
    balance: float = 0.0


if __name__ == "__main__":
    if not _HAS_CRYPTO:
        print("AVISO: cryptography não instalado. "
              "Rode: pip install cryptography")
    priv, addr = generate_keypair()
    print("Endereço gerado:", addr)
    print("Priv (hex):", priv[:16], "...")
    if _HAS_CRYPTO:
        ct, salt = encrypt_private_key(priv, "senha-teste-123")
        back = decrypt_private_key(ct, salt, "senha-teste-123")
        assert back == priv, "roundtrip falhou"
        print("Cifra/decifra: OK")
    print("OK — carteira.py funciona.")