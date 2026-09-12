"""Inspect recent calls. Records and proposals only; never patch this tool."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from knowledge_mcp.ingest import slugify, uniquify
from knowledge_mcp.log import guarded, log_call, read_calls
from knowledge_mcp.paths import dirs, repo_root


def _since(look_back: str) -> datetime:
    s = (look_back or "7d").strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())
    n = int(digits or "7")
    now = datetime.now(timezone.utc)
    if s.endswith("h"):
        return now - timedelta(hours=n)
    return now - timedelta(days=n)


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@guarded("kb_inspect")
def inspect(look_back: str = "7d", proposal: str | None = None) -> str:
    start = _since(look_back)
    rows = []
    for rec in read_calls():
        ts = _parse_ts(str(rec.get("ts") or ""))
        if ts is None or ts < start:
            continue
        rows.append(rec)
    fails = [r for r in rows if not r.get("ok")]
    lines = [
        "自检",
        f"仓库：{repo_root()}",
        f"范围：最近 {look_back or '7d'}",
        f"调用 {len(rows)} 次，失败 {len(fails)} 次",
    ]
    if not rows:
        lines.append("最近记录：还没有。")
    else:
        for rec in rows[-30:]:
            door = rec.get("door", "?")
            flag = "ok" if rec.get("ok") else "失败"
            extra = rec.get("step") or rec.get("query") or rec.get("action") or ""
            lines.append(f"- {rec.get('ts', '')}  {door}  {flag}  {extra}".rstrip())
    lines.append("第一版不准改本工具源码。要改功能先写提案进 检修/提案/。")
    if proposal and proposal.strip():
        repair = dirs()["repair"]
        repair.mkdir(parents=True, exist_ok=True)
        title = proposal.strip().splitlines()[0][:40]
        base = slugify(title) or "proposal"
        day = datetime.now().strftime("%Y-%m-%d")
        path = uniquify(repair / f"{day}-{base}.md")
        path.write_text(
            f"# 提案\n\n{proposal.strip()}\n\n"
            "修理规范：写清加还是减、动哪扇门、对「书不改 / 先抬头后正文」有没有风险。"
            "等人点头后先改说明书，再考虑改程序。本工具不会把提案补丁进 mcp/。\n",
            encoding="utf-8",
        )
        try:
            rel = path.resolve().relative_to(dirs()["root"]).as_posix()
        except ValueError:
            rel = path.name
        lines.append(f"已写下提案：{rel}")
    out = "\n".join(lines) + "\n"
    log_call("kb_inspect", True, n=len(rows), fails=len(fails))
    return out
