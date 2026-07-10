import json

import ucp


def test_healthz_and_readyz(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_cors_for_chrome_extension(client):
    origin = "chrome-extension://egicgklglmnocmeagceoejjniimjbjk"
    preflight = client.options(
        "/v1/generate",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["access-control-allow-private-network"] == "true"

    health = client.get("/healthz", headers={"Origin": origin})
    assert health.status_code == 200
    assert health.headers["access-control-allow-origin"] == origin


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


def test_generate_confluence_index_hit(doc_client):
    resp = doc_client.post(
        "/v1/generate", json={"source": "confluence", "ref": "DOCS:123456"}
    )
    assert resp.status_code == 200
    package = resp.json()
    ucp.validate(package)
    assert package["entity"]["ref"]["system"] == "confluence"
    assert package["entity"]["ref"]["id"] == "DOCS:123456"


def test_generate_document_not_indexed_is_404(doc_client):
    resp = doc_client.post(
        "/v1/generate", json={"source": "gdrive", "ref": "missing-file-id-12345"}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


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


def test_admin_sources_requires_engine(doc_client, monkeypatch):
    monkeypatch.setattr(
        "contextos_engine.admin.health.IndexStore",
        lambda _s: type(
            "S",
            (),
            {
                "ensure_schema": lambda self: None,
                "count_entities_by_source": lambda self: {"github": 1},
                "list_sync_cursors": lambda self: [],
                "recent_audit_entries": lambda self, limit=15: [],
            },
        )(),
    )
    resp = doc_client.get("/v1/admin/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert "sources" in body
    assert len(body["sources"]) == 5


def test_admin_dashboard_html(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Rangor Admin" in resp.text
    assert "UCP_SERVER_API_KEY" in resp.text
    assert "sessionStorage" in resp.text
    assert "sync-btn" in resp.text


def test_admin_audit_pagination(doc_client, monkeypatch):
    monkeypatch.setattr(
        "contextos_engine.index_store.IndexStore.list_audit_entries",
        lambda self, limit=50, offset=0: (
            [{"created_at": "t", "principal": "p", "source_system": "jira", "verdict": "allow"}],
            42,
        ),
    )
    resp = doc_client.get("/v1/admin/audit?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 42
    assert len(body["entries"]) == 1


def test_admin_sync_queues_task(doc_client, monkeypatch):
    monkeypatch.setattr(
        "contextos_engine.admin.trigger_source_sync",
        lambda source, redis_url: "task-xyz",
    )
    resp = doc_client.post("/v1/admin/sync/github")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-xyz"


def test_admin_eval_missing_report(client, tmp_path, monkeypatch):
    monkeypatch.setenv("UCP_EVAL_REPORT_PATH", str(tmp_path / "missing.json"))
    resp = client.get("/v1/admin/eval")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "missing"


def test_admin_eval_reads_report(client, tmp_path, monkeypatch):
    report_path = tmp_path / "latest.json"
    report_path.write_text(
        json.dumps(
            {
                "run_at": "2026-07-07T00:00:00Z",
                "aggregate": {"cases_passed": 2, "cases_ok": 2, "must_know_precision_mean": 0.8},
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("UCP_EVAL_REPORT_PATH", str(report_path))
    resp = client.get("/v1/admin/eval")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["aggregate"]["must_know_precision_mean"] == 0.8


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
