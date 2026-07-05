"""Package store: a directory of ``*.ucp.json`` files indexed for lookup.

The store re-scans lazily: files are reloaded when their mtime changes, so a
producer can drop or update packages while the server is running.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import ucp


@dataclass
class StoredPackage:
    path: Path
    mtime: float
    package: ucp.Package


class PackageStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self._cache: dict[Path, StoredPackage] = {}

    def _scan(self) -> list[StoredPackage]:
        found: list[StoredPackage] = []
        for path in sorted(self.directory.glob("*.ucp.json")):
            mtime = path.stat().st_mtime
            cached = self._cache.get(path)
            if cached is None or cached.mtime != mtime:
                try:
                    cached = StoredPackage(path, mtime, ucp.load(path))
                except (ucp.UCPValidationError, ValueError) as exc:
                    # An invalid package must not take the whole server down;
                    # it is skipped and will be retried on next change.
                    print(f"ucp-mcp: skipping invalid package {path.name}: {exc}")
                    continue
                self._cache[path] = cached
            found.append(cached)
        # Drop cache entries for deleted files.
        alive = {item.path for item in found}
        for path in list(self._cache):
            if path not in alive:
                del self._cache[path]
        return found

    def all(self) -> list[ucp.Package]:
        return [item.package for item in self._scan()]

    def find(self, entity: str) -> Optional[ucp.Package]:
        """Resolve by entity id, source URL, or title fragment (in that order)."""
        packages = self.all()
        needle = entity.strip()
        lowered = needle.lower()

        for pkg in packages:
            if pkg.entity.ref.id == needle:
                return pkg
        for pkg in packages:
            if pkg.entity.ref.url and pkg.entity.ref.url == needle:
                return pkg
        for pkg in packages:
            if lowered in pkg.entity.title.lower():
                return pkg
        return None
