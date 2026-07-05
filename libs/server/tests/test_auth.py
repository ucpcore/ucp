import inspect

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import _AuthMiddleware, create_app

from .conftest import make_settings


@pytest.fixture()
def secured(tmp_path, offline):
    settings = make_settings(tmp_path, UCP_SERVER_API_KEY="s3cret")
    with TestClient(create_app(settings)) as client:
        yield client


def test_health_probes_stay_open(secured):
    assert secured.get("/healthz").status_code == 200
    assert secured.get("/readyz").status_code == 200


def test_missing_key_is_401_problem_json(secured):
    resp = secured.get("/v1/packages")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Unauthorized"


def test_wrong_key_is_401(secured):
    resp = secured.get("/v1/packages", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_wrong_scheme_is_401(secured):
    resp = secured.get("/v1/packages", headers={"Authorization": "Basic s3cret"})
    assert resp.status_code == 401


def test_correct_key_is_200(secured):
    resp = secured.get("/v1/packages", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200

    generated = secured.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert generated.status_code == 200


def test_docs_are_protected_too(secured):
    assert secured.get("/docs").status_code == 401
    assert secured.get("/openapi.json").status_code == 401


def test_comparison_is_constant_time():
    # The guarantee lives in secrets.compare_digest; assert we use it rather
    # than a timing-leaky `==` on the supplied credential.
    source = inspect.getsource(_AuthMiddleware.dispatch)
    assert "secrets.compare_digest" in source


def test_no_key_configured_means_open_server(client):
    assert client.get("/v1/packages").status_code == 200
