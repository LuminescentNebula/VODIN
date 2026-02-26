import pytest

ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
Ed25519PrivateKey = ed25519.Ed25519PrivateKey

from vodin.crypto import sign_message, verify_signature


def test_sign_verify_roundtrip():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    message = b"hello"
    signature = sign_message(private_key, message)

    assert verify_signature(public_key, message, signature)
    assert not verify_signature(public_key, b"tampered", signature)
