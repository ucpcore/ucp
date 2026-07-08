"""Persist Usage Receipts (RFC-0007) for eval and ranking calibration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Settings


@dataclass
class StoredReceipt:
    receipt: dict[str, Any]
    stored_at: str


class ReceiptStore:
    """Append-only JSONL under cache_dir/receipts/."""

    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "receipts" / "receipts.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, receipt: dict[str, Any]) -> StoredReceipt:
        stored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = {"stored_at": stored_at, "receipt": receipt}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return StoredReceipt(receipt=receipt, stored_at=stored_at)

    def list_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        limit = max(1, min(limit, 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        rows: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(rows) >= limit:
                break
        return list(reversed(rows))

    def aggregate(self) -> dict[str, Any]:
        return self.analytics(limit=200)

    def aggregate_claim_signals(
        self,
        *,
        package_id: str | None = None,
        limit: int = 500,
    ) -> tuple[set[str], set[str]]:
        """Team-wide cited/ignored claim ids for warm ranking (cited wins over ignored)."""
        cited: set[str] = set()
        ignored: set[str] = set()
        for row in self.list_recent(limit=limit):
            rec = row.get("receipt") or {}
            if package_id is not None and rec.get("package_id") != package_id:
                continue
            for cid in rec.get("claims_cited") or []:
                if cid:
                    cited.add(str(cid))
            for cid in rec.get("claims_ignored") or []:
                if cid and cid not in cited:
                    ignored.add(str(cid))
        return cited, ignored

    def analytics(self, *, limit: int = 200, principal: str | None = None) -> dict[str, Any]:
        rows = self.list_recent(limit=limit)
        if principal is not None:
            rows = [
                r
                for r in rows
                if (r.get("receipt") or {}).get("audience") == principal
                or (r.get("receipt") or {}).get("principal") == principal
            ]

        outcomes: dict[str, int] = {}
        claim_cited: dict[str, int] = {}
        claim_ignored: dict[str, int] = {}
        by_package: dict[str, int] = {}
        cited_total = 0
        ignored_total = 0

        for row in rows:
            rec = row.get("receipt") or {}
            outcome = rec.get("outcome") or "unknown"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            pid = rec.get("package_id") or "unknown"
            by_package[pid] = by_package.get(pid, 0) + 1
            for cid in rec.get("claims_cited") or []:
                key = str(cid)
                claim_cited[key] = claim_cited.get(key, 0) + 1
                cited_total += 1
            for cid in rec.get("claims_ignored") or []:
                key = str(cid)
                claim_ignored[key] = claim_ignored.get(key, 0) + 1
                ignored_total += 1

        claims: list[dict[str, Any]] = []
        all_ids = set(claim_cited) | set(claim_ignored)
        for cid in sorted(all_ids):
            c = claim_cited.get(cid, 0)
            i = claim_ignored.get(cid, 0)
            claims.append({"id": cid, "cited": c, "ignored": i, "net": c - i})
        claims.sort(key=lambda x: (-x["net"], -x["cited"], x["id"]))

        packages = [
            {"package_id": pid, "receipts": count}
            for pid, count in sorted(by_package.items(), key=lambda x: -x[1])
        ]

        return {
            "total": len(rows),
            "outcomes": outcomes,
            "claims_cited_total": cited_total,
            "claims_ignored_total": ignored_total,
            "claims": claims[:50],
            "by_package": packages[:20],
            "recent": rows[-10:],
        }


def get_receipt_store(settings: Settings) -> ReceiptStore:
    return ReceiptStore(settings)
