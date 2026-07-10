"""Track estimated raw vs UCP token usage per principal."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import ucp

from .config import Settings

BENCHMARK_EXAMPLE = {
    "ref": "microsoft/vscode#519",
    "source": "github",
    "raw_tokens": 18500,
    "ucp_tokens": 1200,
    "tokens_saved": 17300,
    "reduction_pct": 94,
}


def _estimate_raw_tokens_github(bundle: dict[str, Any]) -> int:
    issue = bundle.get("issue") or {}
    parts = [str(issue.get("title") or ""), str(issue.get("body") or "")]
    parts += [str(c.get("body") or "") for c in bundle.get("comments") or []]
    parts += [str(p.get("body") or "") for p in bundle.get("linked_pulls") or []]
    return ucp.estimate_tokens("\n\n".join(parts))


def _estimate_raw_tokens_jira(bundle: dict[str, Any]) -> int:
    issue = bundle.get("issue") or {}
    fields = issue.get("fields") or {}
    parts = [
        str(fields.get("summary") or ""),
        str(fields.get("description") or ""),
    ]
    parts += [str(c.get("body") or "") for c in bundle.get("comments") or []]
    return ucp.estimate_tokens("\n\n".join(parts))


def estimate_raw_tokens(source: str, bundle: dict[str, Any]) -> int:
    if source == "github":
        return _estimate_raw_tokens_github(bundle)
    if source == "jira":
        return _estimate_raw_tokens_jira(bundle)
    title = str((bundle.get("document") or {}).get("title") or "")
    body = str((bundle.get("document") or {}).get("body") or bundle.get("body") or "")
    return ucp.estimate_tokens("\n\n".join([title, body]))


class TokenSavingsStore:
    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "analytics" / "token_savings.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        principal: str,
        source: str,
        ref: str,
        package_id: str,
        ucp_tokens: int,
        raw_tokens: int,
    ) -> None:
        saved = max(0, raw_tokens - ucp_tokens)
        if saved <= 0 and ucp_tokens <= 0:
            return
        row = {
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "principal": principal,
            "source": source,
            "ref": ref,
            "package_id": package_id,
            "ucp_tokens": ucp_tokens,
            "raw_tokens": raw_tokens,
            "tokens_saved": saved,
            "reduction_pct": round((saved / raw_tokens) * 100) if raw_tokens else 0,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def last_for_principal(self, principal: str) -> Optional[dict[str, Any]]:
        if not self.path.is_file():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("principal") == principal:
                return row
        return None

    def summary(self, principal: str, *, limit: int = 500) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "packages": 0,
                "ucp_tokens": 0,
                "raw_tokens": 0,
                "tokens_saved": 0,
                "avg_reduction_pct": 0,
            }
        packages = 0
        ucp_total = 0
        raw_total = 0
        saved_total = 0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("principal") != principal:
                continue
            packages += 1
            ucp_total += int(row.get("ucp_tokens") or 0)
            raw_total += int(row.get("raw_tokens") or 0)
            saved_total += int(row.get("tokens_saved") or 0)
            if packages >= limit:
                break
        avg_pct = round((saved_total / raw_total) * 100) if raw_total else 0
        return {
            "packages": packages,
            "ucp_tokens": ucp_total,
            "raw_tokens": raw_total,
            "tokens_saved": saved_total,
            "avg_reduction_pct": avg_pct,
        }


def get_token_savings_store(settings: Settings) -> TokenSavingsStore:
    return TokenSavingsStore(settings)
