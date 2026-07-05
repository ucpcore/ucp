import ucp


def test_healthz_and_readyz(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_generate_github_returns_valid_package(client):
    resp = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})
    assert resp.status_code == 200
    assert resp.headers["X-UCP-Cache"] == "miss"
    assert resp.headers["X-UCP-Package-Id"] == "github-acme-rocket-42"
    package = resp.json()
    ucp.validate(package)
    assert package["entity"]["ref"]["id"] == "acme/rocket#42"


def test_generate_jira_returns_valid_package(client):
    resp = client.post("/v1/generate", json={"source": "jira", "ref": "PAY-7"})
    assert resp.status_code == 200
    package = resp.json()
    ucp.validate(package)
    assert package["entity"]["ref"]["id"] == "PAY-7"


def test_generate_with_audience_lands_in_package(client):
    resp = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42", "audience": "team:payments"},
    )
    assert resp.status_code == 200
    assert resp.json()["audience"]["principal"]["id"] == "team:payments"


def test_invalid_ref_is_problem_json(client):
    resp = client.post("/v1/generate", json={"source": "github", "ref": "not-a-ref"})
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["title"] == "Invalid Reference"
    assert body["status"] == 400
    assert "owner/repo#number" in body["detail"]


def test_arbitrary_url_as_ref_is_rejected(client):
    resp = client.post(
        "/v1/generate", json={"source": "github", "ref": "https://evil.example/x#1"}
    )
    assert resp.status_code == 400


def test_unknown_source_rejected_by_schema(client):
    resp = client.post("/v1/generate", json={"source": "gitlab", "ref": "a/b#1"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_unknown_body_field_rejected(client):
    resp = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42", "url": "https://evil"},
    )
    assert resp.status_code == 422


def test_upstream_not_found_maps_to_404(client):
    resp = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#999"})
    assert resp.status_code == 404
    assert resp.json()["title"] == "Upstream Entity Not Found"


def test_body_size_limit(client):
    huge = "x" * (70 * 1024)
    resp = client.post(
        "/v1/generate",
        content='{"source": "github", "ref": "' + huge + '"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert resp.json()["title"] == "Payload Too Large"


def test_packages_listing_and_retrieval(client):
    client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})

    listing = client.get("/v1/packages").json()
    assert len(listing) == 1
    assert listing[0]["id"] == "github-acme-rocket-42"
    assert listing[0]["title"] == "Payment webhook drops events under load"

    package = client.get("/v1/packages/github-acme-rocket-42")
    assert package.status_code == 200
    ucp.validate(package.json())


def test_package_not_found_is_problem_json(client):
    resp = client.get("/v1/packages/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_markdown_rendering_with_budget(client):
    client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})

    full = client.get("/v1/packages/github-acme-rocket-42/markdown")
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("text/markdown")
    assert full.text.startswith("# Context: Payment webhook drops events under load")

    capped = client.get("/v1/packages/github-acme-rocket-42/markdown?token_budget=200")
    assert ucp.estimate_tokens(capped.text) <= 200


def test_openapi_docs_available(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/v1/generate" in spec.json()["paths"]


def test_mcp_endpoint_is_routed_without_redirect(client):
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}},
        },
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert '"serverInfo"' in resp.text
