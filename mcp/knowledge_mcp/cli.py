"""CLI for the knowledge skill. Same gates as MCP; no extra doors."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _print(out: str) -> int:
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 1 if out.startswith("失败") else 0


def cmd_init(root: Path) -> str:
    root = root.resolve()
    for p in (
        "原始资料",
        "原始资料归档",
        "资料/书",
        "资料/笔记",
        "检修/提案",
    ):
        (root / p).mkdir(parents=True, exist_ok=True)
    return (
        f"已初始化资料室\nKNOWLEDGE_ROOT={root}\n"
        "把 PDF/EPUB/MOBI 放进 原始资料/，然后 knowledge ingest\n"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="knowledge",
        description="本机资料室。检索只回路标；入库走操作流程。",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建 原始资料/ 资料/ 检修/")

    s = sub.add_parser("search", help="检索，只回路标")
    s.add_argument("query", nargs="+")

    r = sub.add_parser("read", help="点名阅读")
    r.add_argument("targets", nargs="+")

    i = sub.add_parser("ingest", help="收件箱入库；有路径则指定入库")
    i.add_argument("paths", nargs="*")

    n = sub.add_parser("note", help="写笔记 preview|verify|create|update")
    n.add_argument("action", choices=["preview", "verify", "create", "update"])
    n.add_argument("--file", dest="file", default="-")
    n.add_argument("--target", default=None)

    l = sub.add_parser("lint", help="scan 或 apply")
    l.add_argument("action", nargs="?", default="scan", choices=["scan", "apply"])
    l.add_argument("--plan", default=None)

    ins = sub.add_parser("inspect", help="自检")
    ins.add_argument("--look-back", default="7d")
    ins.add_argument("--proposal", default=None)

    args = p.parse_args(argv)

    if args.cmd == "init":
        import os

        root = Path(os.environ["KNOWLEDGE_ROOT"]) if os.environ.get("KNOWLEDGE_ROOT") else Path.cwd()
        return _print(cmd_init(root))

    if args.cmd == "search":
        from knowledge_mcp.retrieve import search

        return _print(search(" ".join(args.query)))

    if args.cmd == "read":
        from knowledge_mcp.retrieve import read

        ts = args.targets
        if len(ts) == 1:
            return _print(read(ts[0], None, None))
        return _print(read("", None, ts))

    if args.cmd == "ingest":
        from knowledge_mcp.ingest import ingest_inbox, ingest_named

        if args.paths:
            return _print(ingest_named(args.paths))
        return _print(ingest_inbox())

    if args.cmd == "note":
        from knowledge_mcp.notes import write_note

        if args.file in (None, "-"):
            md = sys.stdin.read()
        else:
            md = Path(args.file).read_text(encoding="utf-8")
        return _print(write_note(md, args.action, args.target))

    if args.cmd == "lint":
        from knowledge_mcp.notes import lint_notes

        return _print(lint_notes(args.action, args.plan))

    if args.cmd == "inspect":
        from knowledge_mcp.inspect import inspect

        return _print(inspect(args.look_back, args.proposal))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
