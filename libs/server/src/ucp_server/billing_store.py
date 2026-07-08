"""Stripe billing stub for hosted pilot (RFC-0009 §4). No real Stripe API calls."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .config import Settings

PlanId = Literal["free", "pro"]
SubscriptionStatus = Literal["active", "trialing", "past_due", "canceled", "pending_checkout"]

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": "Free",
        "price_usd": 0,
        "interval": "month",
        "description": "GitHub public или один Jira-проект, polling sync",
        "features": [
            "1 источник данных",
            "50 пакетов / месяц",
            "Polling sync (15 min)",
            "Usage Receipt API",
        ],
        "sources_limit": 1,
        "packages_limit": 50,
        "stripe_price_id": None,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_usd": 20,
        "interval": "month",
        "description": "Все MVP-источники, webhooks, warm ranking",
        "features": [
            "GitHub + Jira + Confluence + Drive",
            "Unlimited packages",
            "Webhook + incremental sync",
            "Receipt analytics (soon)",
        ],
        "sources_limit": None,
        "packages_limit": None,
        "stripe_price_id": "price_stub_pro_monthly",
    },
}


@dataclass
class BillingState:
    plan: PlanId
    status: SubscriptionStatus
    seats: int
    packages_used: int
    stripe_customer_id: str
    stripe_subscription_id: Optional[str]
    current_period_end: str
    pending_checkout_session: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        plan = PLANS[self.plan]
        return {
            "plan": self.plan,
            "plan_name": plan["name"],
            "status": self.status,
            "seats": self.seats,
            "packages_used": self.packages_used,
            "packages_limit": plan.get("packages_limit"),
            "sources_limit": plan.get("sources_limit"),
            "price_usd": plan["price_usd"],
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "current_period_end": self.current_period_end,
            "pending_checkout_session": self.pending_checkout_session,
            "stub_mode": True,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _period_end(days: int = 30) -> str:
    end = datetime.now(timezone.utc) + timedelta(days=days)
    return end.isoformat().replace("+00:00", "Z")


class BillingStore:
    """JSON persistence under cache_dir/billing/state.json."""

    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "billing" / "state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self._write(self._default_state())

    def get_state(self) -> BillingState:
        return self._load()

    def list_plans(self) -> list[dict[str, Any]]:
        return list(PLANS.values())

    def create_checkout_session(self, *, plan: PlanId) -> dict[str, Any]:
        if plan not in PLANS or plan == "free":
            raise ValueError("checkout supports pro plan only")
        state = self._load()
        session_id = f"cs_stub_{uuid.uuid4().hex[:16]}"
        state.pending_checkout_session = session_id
        state.status = "pending_checkout"
        self._write(state)
        return {
            "id": session_id,
            "plan": plan,
            "amount_usd": PLANS[plan]["price_usd"],
            "currency": "usd",
            "status": "open",
            "url": f"/dashboard/checkout?session={session_id}",
            "stub_mode": True,
            "message": "Stripe stub — no real charge. Complete via portal or webhook.",
        }

    def complete_checkout(self, *, session_id: str) -> BillingState:
        state = self._load()
        if state.pending_checkout_session != session_id:
            raise ValueError("invalid or expired checkout session")
        state.plan = "pro"
        state.status = "active"
        state.stripe_subscription_id = f"sub_stub_{uuid.uuid4().hex[:12]}"
        state.current_period_end = _period_end()
        state.pending_checkout_session = None
        self._write(state)
        return state

    def simulate_stripe_webhook(self, *, event_type: str, session_id: Optional[str] = None) -> dict[str, Any]:
        if event_type == "checkout.session.completed":
            if not session_id:
                raise ValueError("session_id required")
            state = self.complete_checkout(session_id=session_id)
            return {"received": True, "event": event_type, "subscription": state.to_dict()}
        if event_type == "customer.subscription.deleted":
            state = self._load()
            state.plan = "free"
            state.status = "canceled"
            state.stripe_subscription_id = None
            state.current_period_end = _period_end()
            self._write(state)
            return {"received": True, "event": event_type, "subscription": state.to_dict()}
        raise ValueError(f"unsupported stub event: {event_type}")

    def create_portal_session(self) -> dict[str, Any]:
        state = self._load()
        return {
            "url": "/dashboard/plans",
            "stripe_customer_id": state.stripe_customer_id,
            "stub_mode": True,
        }

    def check_quota(self) -> Optional[str]:
        state = self._load()
        limit = PLANS[state.plan].get("packages_limit")
        if limit is not None and state.packages_used >= limit:
            return f"monthly package limit reached ({limit}). Upgrade to Pro at /dashboard/plans."
        return None

    def record_package_generated(self) -> None:
        state = self._load()
        state.packages_used += 1
        self._write(state)
    def _default_state(self) -> BillingState:
        return BillingState(
            plan="free",
            status="active",
            seats=1,
            packages_used=0,
            stripe_customer_id=f"cus_stub_{uuid.uuid4().hex[:12]}",
            stripe_subscription_id=None,
            current_period_end=_period_end(),
        )

    def _load(self) -> BillingState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        return BillingState(
            plan=raw.get("plan", "free"),
            status=raw.get("status", "active"),
            seats=int(raw.get("seats", 1)),
            packages_used=int(raw.get("packages_used", 0)),
            stripe_customer_id=str(raw.get("stripe_customer_id", f"cus_stub_{uuid.uuid4().hex[:8]}")),
            stripe_subscription_id=raw.get("stripe_subscription_id"),
            current_period_end=str(raw.get("current_period_end", _period_end())),
            pending_checkout_session=raw.get("pending_checkout_session"),
        )

    def _write(self, state: BillingState) -> None:
        payload = {
            "plan": state.plan,
            "status": state.status,
            "seats": state.seats,
            "packages_used": state.packages_used,
            "stripe_customer_id": state.stripe_customer_id,
            "stripe_subscription_id": state.stripe_subscription_id,
            "current_period_end": state.current_period_end,
            "pending_checkout_session": state.pending_checkout_session,
            "updated_at": _now_iso(),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_billing_store(settings: Settings) -> BillingStore:
    return BillingStore(settings)
