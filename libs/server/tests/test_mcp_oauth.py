"""Tests for MCP OAuth (Cursor Authenticate flow)."""
from __future__ import annotations

import base64
import hashlib
import re
import secrets

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX

from .conftest import make_settings


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


@pytest.fixture()
def client(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_API_KEY="admin-secret",
        UCP_SESSION_SECRET="test-session-secret",
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="http://localhost:8080",
        UCP_HOSTED_MODE="1",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_mcp_401_includes_resource_metadata(client):
    resp = client.get("/v1/pilot/mcp")
    assert resp.status_code == 401
    www = resp.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www
    assert "oauth-protected-resource" in www


def test_protected_resource_metadata(client):
    resp = client.get("/.well-known/oauth-protected-resource/v1/pilot/mcp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"] == "http://localhost:8080/v1/pilot/mcp"
    assert "http://localhost:8080/v1/oauth/mcp" in body["authorization_servers"]


def test_authorization_server_metadata(client):
    resp = client.get("/.well-known/oauth-authorization-server/v1/oauth/mcp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorization_endpoint"].endswith("/v1/oauth/mcp/authorize")
    assert body["registration_endpoint"].endswith("/v1/oauth/mcp/register")
    assert "S256" in body["code_challenge_methods_supported"]


def test_mcp_oauth_full_flow(client):
    reg = client.post(
        "/v1/oauth/mcp/register",
        json={
            "client_name": "Cursor",
            "redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    client.post(
        "/v1/auth/bootstrap",
        json={"email": "admin@example.com", "password": "adminpass1"},
    )

    verifier, challenge = _pkce_pair()
    redirect_uri = "cursor://anysphere.cursor-mcp/oauth/callback"
    auth = client.get(
        "/v1/oauth/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "test-state",
        },
    )
    assert auth.status_code == 200
    assert "Approve Client Authorization" in auth.text
    assert "Client Details" in auth.text
    match = re.search(r'name="consent_id" value="([^"]+)"', auth.text)
    assert match is not None
    consent_id = match.group(1)

    approve = client.post(
        "/v1/oauth/mcp/authorize/approve",
        data={"consent_id": consent_id},
        follow_redirects=False,
    )
    assert approve.status_code == 303
    location = approve.headers["location"]
    assert location.startswith("cursor://")
    assert "code=" in location

    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(location)
    code = parse_qs(parsed.query)["code"][0]

    token_resp = client.post(
        "/v1/oauth/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token_resp.status_code == 200
    access_token = token_resp.json()["access_token"]
    assert access_token.startswith(TOKEN_PREFIX)

    mcp = client.get(
        "/v1/pilot/mcp",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert mcp.status_code != 401


def test_mcp_oauth_consent_cancel(client):
    reg = client.post(
        "/v1/oauth/mcp/register",
        json={
            "client_name": "Cursor",
            "redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"],
        },
    ).json()
    client_id = reg["client_id"]
    client.post(
        "/v1/auth/bootstrap",
        json={"email": "admin@example.com", "password": "adminpass1"},
    )
    verifier, challenge = _pkce_pair()
    redirect_uri = "cursor://anysphere.cursor-mcp/oauth/callback"
    auth = client.get(
        "/v1/oauth/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    consent_id = re.search(r'name="consent_id" value="([^"]+)"', auth.text).group(1)
    cancelled = client.get(
        f"/v1/oauth/mcp/authorize/cancel?consent_id={consent_id}",
        headers={"Accept": "text/html"},
    )
    assert cancelled.status_code == 200
    assert "Authorization cancelled" in cancelled.text
