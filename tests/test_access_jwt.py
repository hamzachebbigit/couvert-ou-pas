import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security


def _app(verifier: security.AccessVerifier) -> TestClient:
    app = FastAPI()
    security.verifier = verifier
    app.middleware("http")(security.access_middleware)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/contracts")
    def contracts():
        return []

    return TestClient(app)


def test_disabled_verifier_lets_everything_through():
    client = _app(security.AccessVerifier("", ""))
    assert client.get("/api/contracts").status_code == 200


def test_enabled_verifier_refuses_without_token_and_accepts_valid_token():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    verifier = security.AccessVerifier("equipe.cloudflareaccess.com", "aud-de-test")
    verifier._keys = {"kid1": jwt.algorithms.RSAAlgorithm.from_jwk(jwt.algorithms.RSAAlgorithm.to_jwk(serialization.load_pem_public_key(public_pem), as_dict=True) | {"kid": "kid1"})}
    verifier._fetched_at = time.time()
    client = _app(verifier)

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/contracts").status_code == 401

    token = jwt.encode(
        {"aud": "aud-de-test", "email": "test@foyer.lu", "iss": "https://equipe.cloudflareaccess.com", "exp": int(time.time()) + 60},
        key, algorithm="RS256", headers={"kid": "kid1"},
    )
    assert client.get("/api/contracts", headers={"cf-access-jwt-assertion": token}).status_code == 200

    wrong = jwt.encode({"aud": "autre", "iss": "https://equipe.cloudflareaccess.com", "exp": int(time.time()) + 60}, key, algorithm="RS256", headers={"kid": "kid1"})
    assert client.get("/api/contracts", headers={"cf-access-jwt-assertion": wrong}).status_code == 401
