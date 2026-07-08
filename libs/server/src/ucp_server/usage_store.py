"""Per-principal package quota (Free tier: 50 packages / month)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .billing_store import PLANS, PlanId
from .config import Settings
from .platform_db import PrincipalUsageRow, get_session_factory, postgres_available, utcnow


def current_period_key(when: Optional[datetime] = None) -> str:
    dt = when or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


FREE_PACKAGES_LIMIT = int(PLANS["free"].get("packages_limit") or 50)


class UsageStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._json_path = settings.cache_dir / "usage" / "by_principal.json"
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        self._pg = (
            get_session_factory(settings.database_url)
            if postgres_available(settings.database_url)
            else None
        )

    def get_packages_used(self, principal: str, *, period: Optional[str] = None) -> int:
        period = period or current_period_key()
        if self._pg:
            with self._pg() as session:
                row = (
                    session.query(PrincipalUsageRow)
                    .filter_by(principal=principal, period_key=period)
                    .one_or_none()
                )
                return int(row.packages_used) if row else 0
        data = self._load_json()
        return int(data.get(period, {}).get(principal, 0))

    def get_limit(self, plan: PlanId = "free") -> Optional[int]:
        return PLANS.get(plan, PLANS["free"]).get("packages_limit")

    def check_quota(self, principal: str, *, plan: PlanId = "free") -> Optional[str]:
        if principal == "service":
            return None
        limit = self.get_limit(plan)
        if limit is None:
            return None
        used = self.get_packages_used(principal)
        if used >= limit:
            return (
                f"monthly package limit reached ({limit}) for {principal}. "
                "Upgrade to Pro at /dashboard/plans or wait for the next period."
            )
        return None

    def record_package_generated(self, principal: str) -> int:
        period = current_period_key()
        if self._pg:
            with self._pg() as session:
                row = (
                    session.query(PrincipalUsageRow)
                    .filter_by(principal=principal, period_key=period)
                    .one_or_none()
                )
                if row is None:
                    row = PrincipalUsageRow(
                        principal=principal,
                        period_key=period,
                        packages_used=1,
                    )
                    session.add(row)
                else:
                    row.packages_used += 1
                session.commit()
                return row.packages_used
        data = self._load_json()
        period_map = data.setdefault(period, {})
        period_map[principal] = int(period_map.get(principal, 0)) + 1
        self._write_json(data)
        return int(period_map[principal])

    def summary(self, principal: str, *, plan: PlanId = "free") -> dict[str, Any]:
        period = current_period_key()
        used = self.get_packages_used(principal, period=period)
        limit = self.get_limit(plan)
        return {
            "principal": principal,
            "period": period,
            "packages_used": used,
            "packages_limit": limit,
            "plan": plan,
        }

    def _load_json(self) -> dict[str, Any]:
        import json

        if not self._json_path.is_file():
            return {}
        try:
            return json.loads(self._json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json(self, data: dict[str, Any]) -> None:
        import json

        self._json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_usage_store(settings: Settings) -> UsageStore:
    return UsageStore(settings)
