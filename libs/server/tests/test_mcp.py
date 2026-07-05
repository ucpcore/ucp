import json

import pytest
from fastmcp import Client

import ucp
from ucp_server.cache import PackageCache
from ucp_server.mcp_tools import build_mcp
from ucp_server.service import GenerationService


@pytest.fixture()
def mcp(settings, offline):
    cache = PackageCache(settings.cache_dir, settings.cache_ttl)
    return build_mcp(GenerationService(settings, cache))


async def _call(mcp, tool, arguments=None):
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments or {})
    return result.content[0].text


async def test_tool_inventory(mcp):
    async with Client(mcp) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert tools == {"generate_context", "list_contexts", "get_context", "get_context_markdown"}


async def test_generate_context_returns_valid_package(mcp):
    answer = json.loads(await _call(
        mcp, "generate_context", {"source": "github", "ref": "acme/rocket#42"}
    ))
    assert answer["id"] == "github-acme-rocket-42"
    assert answer["cached"] is False
    ucp.validate(answer["package"])


async def test_generate_then_list_get_markdown(mcp):
    await _call(mcp, "generate_context", {"source": "github", "ref": "acme/rocket#42"})

    items = json.loads(await _call(mcp, "list_contexts"))
    assert [item["id"] for item in items] == ["github-acme-rocket-42"]

    package = json.loads(await _call(mcp, "get_context", {"id": "github-acme-rocket-42"}))
    ucp.validate(package)

    text = await _call(
        mcp, "get_context_markdown",
        {"id": "github-acme-rocket-42", "token_budget": 200},
    )
    assert text.startswith("# Context: Payment webhook drops events under load")
    assert ucp.estimate_tokens(text) <= 200


async def test_invalid_ref_is_reported_not_raised(mcp):
    answer = await _call(mcp, "generate_context", {"source": "github", "ref": "nope"})
    assert answer.startswith("Error:")
    assert "owner/repo#number" in answer


async def test_unknown_id_lists_available(mcp):
    await _call(mcp, "generate_context", {"source": "github", "ref": "acme/rocket#42"})
    answer = await _call(mcp, "get_context", {"id": "missing"})
    assert "No context package found" in answer
    assert "github-acme-rocket-42" in answer


async def test_empty_cache_message(mcp):
    answer = await _call(mcp, "list_contexts")
    assert "No context packages cached" in answer
