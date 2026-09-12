"""Call log for inspect. One jsonl line per door."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from knowledge_mcp.errors import fail
from knowledge_mcp.paths import dirs


def log_call(door: str, ok: bool, **extra: Any) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "door": door,
        "ok": ok,
        **extra,
    }
    path = dirs()["log"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_calls() -> list[dict[str, Any]]:
    path = dirs()["log"]
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def guarded(door: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        def inner(*args: Any, **kwargs: Any) -> str:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                log_call(door, False, error=f"{type(e).__name__}: {e}"[:200])
                return fail(
                    f"{door}（工具崩了）",
                    f"工具坏了：{type(e).__name__}: {e}",
                    "无",
                    "需要修工具；不要换个姿势把同一错误再砸十次。",
                )
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return deco
