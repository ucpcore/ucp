"""Optional LLM enhancement for generated packages (``--llm``).

Adds what structure alone cannot see: a real summary of the whole thread,
semantic salience for key comments, and decisions/conflicts extracted from
prose. Works against any OpenAI-compatible endpoint (OpenAI, kie.ai,
OpenRouter, Ollama, LiteLLM proxy, …).

Design constraints:
- provenance survives: the model may only cite the source keys we give it;
  anything else is dropped, so every enhanced claim still points at a real,
  hashed source;
- graceful degradation: any failure (network, bad JSON, refusal) raises
  ``LLMError`` and the caller keeps the structure-only package.

Environment:
    UCP_LLM_BASE_URL  default https://api.openai.com/v1
    UCP_LLM_API_KEY   falls back to OPENAI_API_KEY
    UCP_LLM_MODEL     default gpt-4o-mini
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

_MAX_DOC_CHARS = 2_000
_MAX_TOTAL_CHARS = 60_000
_SALIENCE_BOOST = 0.3

_PROMPT = """\
You are a context analyst. Below are documents from one work item
(an issue/ticket), each with a stable source key.

Return ONLY a JSON object with this shape:
{
  "summary": "3-5 sentences: what is going on, what was decided, what is open",
  "key_sources": ["source keys of the few documents that matter most"],
  "decisions": [
    {"decision": "one sentence", "status": "accepted" | "proposed" | "rejected",
     "source": "source key where this is stated"}
  ],
  "conflicts": [
    {"description": "what is contradicted",
     "positions": [{"claim": "position A", "source": "key"},
                   {"claim": "position B", "source": "key"}]}
  ]
}

Rules: cite only the provided source keys; empty lists are fine; report
decisions and conflicts only when the text clearly supports them.
"""


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    base_url: str
    api_key: Optional[str]
    model: str

    @classmethod
    def from_env(
        cls,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> "LLMConfig":
        return cls(
            base_url=(base_url or os.environ.get("UCP_LLM_BASE_URL")
                      or "https://api.openai.com/v1").rstrip("/"),
            api_key=api_key or os.environ.get("UCP_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            model=model or os.environ.get("UCP_LLM_MODEL") or "gpt-4o-mini",
        )


def _chat(config: LLMConfig, prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    try:
        resp = httpx.post(
            f"{config.base_url}/chat/completions",
            headers=headers,
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise LLMError(f"LLM call failed: {exc}") from exc


def _parse_json(text: str) -> dict:
    # Models love to wrap JSON in markdown fences; strip them.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError(f"LLM returned no JSON object: {text[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM returned invalid JSON: {exc}") from exc


def _build_prompt(docs: list[dict]) -> str:
    parts = [_PROMPT, "\n--- DOCUMENTS ---"]
    used = 0
    for doc in docs:
        text = doc["text"][:_MAX_DOC_CHARS]
        block = f"\n[{doc['key']}] {doc['label']}\n{text}\n"
        if used + len(block) > _MAX_TOTAL_CHARS:
            parts.append(f"\n(… remaining documents omitted for length …)")
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def enhance(package: dict[str, Any], docs: list[dict], config: LLMConfig) -> dict[str, Any]:
    """Enrich a structure-only package with LLM understanding, in place.

    Raises :class:`LLMError` on any failure; the caller decides whether to
    degrade to the structure-only package.
    """
    known_docs = {doc["key"]: doc for doc in docs}
    result = _parse_json(_chat(config, _build_prompt(docs)))

    def usable(keys: Any) -> list[str]:
        if not isinstance(keys, list):
            keys = [keys]
        return [k for k in keys if isinstance(k, str) and k in known_docs]

    def ensure_source(key: str) -> None:
        # LLM may cite a comment the structural pass filtered out; restore it
        # so referential integrity holds.
        if key not in package["sources"]:
            package["sources"][key] = known_docs[key]["source"]

    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        cited = usable(result.get("key_sources") or []) or ["issue"]
        for key in cited:
            ensure_source(key)
        package["summary"] = {"text": summary.strip()[:1200], "sources": cited, "confidence": 0.7}

    for key in usable(result.get("key_sources") or []):
        ensure_source(key)
        for claim in package.get("must_know", []):
            if key in claim.get("sources", []):
                claim["salience"] = round(
                    min(0.9, (claim.get("salience") or 0.5) + _SALIENCE_BOOST), 2
                )

    existing = {d["decision"].lower() for d in package.get("decisions", [])}
    for i, item in enumerate(result.get("decisions") or []):
        if not isinstance(item, dict):
            continue
        text = item.get("decision")
        srcs = usable(item.get("source"))
        status = item.get("status")
        if not (isinstance(text, str) and text.strip() and srcs):
            continue
        if status not in ("accepted", "proposed", "rejected"):
            status = "proposed"
        if text.lower() in existing:
            continue
        for key in srcs:
            ensure_source(key)
        package.setdefault("decisions", []).append({
            "id": f"decision-llm-{i}",
            "decision": text.strip()[:500],
            "status": status,
            "sources": srcs,
        })

    for i, item in enumerate(result.get("conflicts") or []):
        if not isinstance(item, dict):
            continue
        description = item.get("description")
        positions = []
        for pos in item.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            srcs = usable(pos.get("source"))
            if isinstance(pos.get("claim"), str) and pos["claim"].strip() and srcs:
                for key in srcs:
                    ensure_source(key)
                positions.append({"claim": pos["claim"].strip()[:500], "sources": srcs})
        if isinstance(description, str) and description.strip() and len(positions) >= 2:
            package.setdefault("conflicts", []).append({
                "id": f"conflict-llm-{i}",
                "description": description.strip()[:500],
                "positions": positions,
            })

    package["generator"] = dict(package["generator"], llm_model=config.model)
    return package
