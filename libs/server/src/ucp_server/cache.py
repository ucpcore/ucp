"""Disk cache for generated packages, keyed by (source, ref, options).

Each entry is a single JSON file named by the SHA-256 of its key, so the
cache survives restarts and needs no external service. Entries older than
the TTL are treated as missing and are overwritten on the next generation;
a TTL of 0 disables the cache entirely.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_ID_SAFE = re.compile(r"[^a-z0-9._-]+")


def package_id(source: str, ref: str) -> str:
    """Stable, URL-safe id for a generated package (e.g. ``github-owner-repo-123``)."""
    return _ID_SAFE.sub("-", f"{source}-{ref}".lower()).strip("-")


@dataclass
class CachedPackage:
    id: str
    package: dict[str, Any]
    stored_at: float


class PackageCache:
    def __init__(self, directory: Path, ttl: int):
        self.directory = directory
        self.ttl = ttl
        if ttl > 0:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str) -> Optional[CachedPackage]:
        if self.ttl <= 0:
            return None
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - entry["stored_at"] > self.ttl:
            return None
        return CachedPackage(entry["id"], entry["package"], entry["stored_at"])

    def put(self, key: str, entry_id: str, package: dict[str, Any]) -> None:
        if self.ttl <= 0:
            return
        payload = {"id": entry_id, "package": package, "stored_at": time.time()}
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def entries(self) -> list[CachedPackage]:
        """All live (non-expired) entries, newest first."""
        if self.ttl <= 0:
            return []
        found: list[CachedPackage] = []
        now = time.time()
        for path in self.directory.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if now - entry["stored_at"] > self.ttl:
                continue
            found.append(CachedPackage(entry["id"], entry["package"], entry["stored_at"]))
        found.sort(key=lambda item: item.stored_at, reverse=True)
        return found

    def find(self, entry_id: str) -> Optional[CachedPackage]:
        for entry in self.entries():
            if entry.id == entry_id:
                return entry
        return None
