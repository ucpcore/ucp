"""Append-only access audit + usage statistics for principals."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .platform_db import HttpAccessLogRow, get_session_factory, postgres_available, utcnow


@dataclass
class AccessAuditEntry:
    created_at: str
    principal: str
    method: str
    path: str
    status: int
    token_id: Optional[str] = None
    channel: str = "rest"


def _channel_for_path(path: str) -> str:
    return "mcp" if path.startswith("/mcp") else "rest"


def _is_generate_hit(method: str, path: str, status: int) -> bool:
    if status >= 400:
        return False
    if method == "POST" and path.startswith("/v1/generate"):
        return True
    if path.startswith("/mcp") and method in {"POST", "GET"}:
        return True
    return False


class AccessAuditStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.cache_dir.expanduser() / "audit" / "access.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pg = (
            get_session_factory(settings.database_url)
            if postgres_available(settings.database_url)
            else None
        )

    def append(
        self,
        *,
        principal: str,
        method: str,
        path: str,
        status: int,
        token_id: Optional[str] = None,
    ) -> AccessAuditEntry:
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        channel = _channel_for_path(path)
        row = {
            "created_at": created_at,
            "principal": principal,
            "method": method,
            "path": path,
            "status": status,
            "token_id": token_id,
            "channel": channel,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self._pg:
            with self._pg() as session:
                session.add(
                    HttpAccessLogRow(
                        created_at=utcnow(),
                        principal=principal,
                        method=method,
                        path=path,
                        status=status,
                        token_id=token_id,
                        channel=channel,
                    )
                )
                session.commit()
        return AccessAuditEntry(**row)

    def list_recent(self, *, limit: int = 50, principal: Optional[str] = None) -> list[dict[str, Any]]:
        if self._pg:
            return self._list_recent_pg(limit=limit, principal=principal)
        return self._list_recent_json(limit=limit, principal=principal)

    def principal_stats(self, principal: str, *, days: int = 365) -> dict[str, Any]:
        if self._pg:
            return self._stats_pg(principal, days=days)
        return self._stats_json(principal, days=days)

    def _list_recent_json(
        self, *, limit: int, principal: Optional[str]
    ) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        limit = max(1, min(limit, 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        rows: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if principal and item.get("principal") != principal:
                continue
            rows.append(item)
            if len(rows) >= limit:
                break
        return list(reversed(rows))

    def _list_recent_pg(self, *, limit: int, principal: Optional[str]) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._pg() as session:
            q = session.query(HttpAccessLogRow).order_by(HttpAccessLogRow.id.desc())
            if principal:
                q = q.filter(HttpAccessLogRow.principal == principal)
            rows = q.limit(limit).all()
        rows.reverse()
        return [
            {
                "created_at": r.created_at.isoformat().replace("+00:00", "Z"),
                "principal": r.principal,
                "method": r.method,
                "path": r.path,
                "status": r.status,
                "token_id": r.token_id,
                "channel": r.channel,
            }
            for r in rows
        ]

    def _stats_json(self, principal: str, *, days: int) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        daily: dict[str, int] = {}
        by_channel = {"rest": 0, "mcp": 0}
        generates = 0
        if not self.path.is_file():
            return {"daily": [], "by_channel": by_channel, "generates": generates}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("principal") != principal:
                continue
            created = item.get("created_at", "")
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt < cutoff:
                continue
            day = dt.date().isoformat()
            daily[day] = daily.get(day, 0) + 1
            ch = item.get("channel") or _channel_for_path(str(item.get("path", "")))
            by_channel[ch] = by_channel.get(ch, 0) + 1
            if _is_generate_hit(
                str(item.get("method", "")),
                str(item.get("path", "")),
                int(item.get("status", 0)),
            ):
                generates += 1
        daily_list = [{"date": d, "count": c} for d, c in sorted(daily.items())]
        return {"daily": daily_list, "by_channel": by_channel, "generates": generates}

    def _stats_pg(self, principal: str, *, days: int) -> dict[str, Any]:
        cutoff = utcnow() - timedelta(days=days)
        daily: dict[str, int] = {}
        by_channel = {"rest": 0, "mcp": 0}
        generates = 0
        with self._pg() as session:
            rows = (
                session.query(HttpAccessLogRow)
                .filter(
                    HttpAccessLogRow.principal == principal,
                    HttpAccessLogRow.created_at >= cutoff,
                )
                .all()
            )
        for row in rows:
            day = row.created_at.date().isoformat()
            daily[day] = daily.get(day, 0) + 1
            by_channel[row.channel] = by_channel.get(row.channel, 0) + 1
            if _is_generate_hit(row.method, row.path, row.status):
                generates += 1
        daily_list = [{"date": d, "count": c} for d, c in sorted(daily.items())]
        return {"daily": daily_list, "by_channel": by_channel, "generates": generates}


def get_access_audit_store(settings: Settings) -> AccessAuditStore:
    return AccessAuditStore(settings)
