"""Load eval-harness report for Admin Dashboard (PRD §4.2)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Settings


def eval_report_path(settings: Settings) -> Path:
    explicit = os.environ.get("UCP_EVAL_REPORT_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return settings.cache_dir.expanduser() / "eval" / "latest.json"


def load_eval_report(settings: Settings) -> dict[str, Any]:
    path = eval_report_path(settings)
    if not path.is_file():
        return {
            "status": "missing",
            "message": (
                "Нет отчёта eval-harness. Запустите: "
                "python tools/eval_ranking/run_eval.py --offline "
                "или --api-key $UCP_SERVER_API_KEY (live)"
            ),
            "report_path": str(path),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "ok"
        data["report_path"] = str(path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "message": f"Не удалось прочитать отчёт: {exc}",
            "report_path": str(path),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
