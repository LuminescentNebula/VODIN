from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def load_private_key(path: str | Path) -> Ed25519PrivateKey:
    key_bytes = Path(path).read_bytes()
    return serialization.load_pem_private_key(key_bytes, password=None)


def load_public_key(path: str | Path) -> Ed25519PublicKey:
    key_bytes = Path(path).read_bytes()
    return serialization.load_pem_public_key(key_bytes)


def sign_message(private_key: Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message)).decode("ascii")


def verify_signature(public_key: Ed25519PublicKey, message: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def export_public_key(public_key: Ed25519PublicKey) -> str:
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem.decode("utf-8")
