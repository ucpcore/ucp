import time

from ucp_server.cache import PackageCache, package_id


PACKAGE = {"entity": {"title": "x"}}


def test_package_id_is_url_safe():
    assert package_id("github", "acme/rocket#42") == "github-acme-rocket-42"
    assert package_id("jira", "PAY-7") == "jira-pay-7"


def test_put_get_roundtrip(tmp_path):
    cache = PackageCache(tmp_path, ttl=60)
    cache.put("key", "id-1", PACKAGE)
    entry = cache.get("key")
    assert entry is not None
    assert entry.id == "id-1"
    assert entry.package == PACKAGE


def test_expired_entry_is_a_miss(tmp_path, monkeypatch):
    cache = PackageCache(tmp_path, ttl=10)
    cache.put("key", "id-1", PACKAGE)

    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + 11)
    assert cache.get("key") is None
    assert cache.entries() == []


def test_ttl_zero_disables_cache(tmp_path):
    cache = PackageCache(tmp_path / "never-created", ttl=0)
    cache.put("key", "id-1", PACKAGE)
    assert cache.get("key") is None
    assert cache.entries() == []
    assert not (tmp_path / "never-created").exists()


def test_find_by_id_and_corrupt_file_ignored(tmp_path):
    cache = PackageCache(tmp_path, ttl=60)
    cache.put("key", "id-1", PACKAGE)
    (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")

    assert cache.find("id-1") is not None
    assert cache.find("missing") is None
    assert len(cache.entries()) == 1


def test_repeated_generate_hits_cache(client):
    first = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})
    second = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})
    assert first.headers["X-UCP-Cache"] == "miss"
    assert second.headers["X-UCP-Cache"] == "hit"
    # Same cached document, byte for byte.
    assert first.json() == second.json()


def test_different_options_are_different_cache_entries(client):
    plain = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})
    with_audience = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42", "audience": "team:x"},
    )
    assert plain.headers["X-UCP-Cache"] == "miss"
    assert with_audience.headers["X-UCP-Cache"] == "miss"
