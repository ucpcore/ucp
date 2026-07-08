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
    assert tools == {
        "generate_context",
        "list_contexts",
        "get_context",
        "get_context_markdown",
        "submit_usage_receipt",
    }


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


async def _render_prompt(mcp, name, arguments):
    async with Client(mcp) as client:
        result = await client.get_prompt(name, arguments)
    return result.messages[0].content.text


async def test_prompt_inventory(mcp):
    async with Client(mcp) as client:
        prompts = {prompt.name for prompt in await client.list_prompts()}
    assert prompts == {"ucp_context", "ucp_catchup"}


async def test_ucp_context_prompt_detects_github(mcp):
    text = await _render_prompt(mcp, "ucp_context", {"ref": "acme/rocket#42"})
    assert 'source="github"' in text
    assert 'ref="acme/rocket#42"' in text
    assert "generate_context" in text
    assert "authoritative task context" in text
    assert "submit_usage_receipt" in text


async def test_submit_usage_receipt_after_generate(mcp):
    gen = json.loads(
        await _call(mcp, "generate_context", {"source": "github", "ref": "acme/rocket#42"})
    )
    package_id = gen["id"]
    answer = json.loads(
        await _call(
            mcp,
            "submit_usage_receipt",
            {
                "package_id": package_id,
                "outcome": "task_completed",
                "claims_cited": ["summary"],
                "claims_ignored": [],
            },
        )
    )
    assert answer["status"] == "ok"
    assert answer["package_id"] == package_id


async def test_ucp_context_prompt_detects_jira_and_llm(mcp):
    text = await _render_prompt(mcp, "ucp_context", {"ref": "PROJ-123", "llm": True})
    assert 'source="jira"' in text
    assert 'ref="PROJ-123"' in text
    assert "llm=true" in text


async def test_ucp_catchup_prompt(mcp):
    text = await _render_prompt(mcp, "ucp_catchup", {"ref": "PROJ-7"})
    assert 'source="jira"' in text
    assert "decided" in text
    assert "conflicts" in text
    assert "open or unresolved" in text


async def test_prompt_with_unrecognized_ref_asks_to_restate(mcp):
    text = await _render_prompt(mcp, "ucp_context", {"ref": "not a ref"})
    assert "neither a GitHub issue" in text
    assert "owner/repo#123" in text
