"""Repo layout. Override with KNOWLEDGE_ROOT for tests."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("KNOWLEDGE_ROOT")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd()
    if (cwd / "资料").is_dir() or (cwd / "原始资料").is_dir():
        return cwd.resolve()
    here = Path(__file__).resolve().parents[2]
    if (here / "资料").is_dir() or (here / "需求.md").is_file():
        return here
    return cwd.resolve()


def dirs() -> dict[str, Path]:
    root = repo_root()
    return {
        "root": root,
        "inbox": root / "原始资料",
        "archive": root / "原始资料归档",
        "books": root / "资料" / "书",
        "notes": root / "资料" / "笔记",
        "materials": root / "资料",
        "repair": root / "检修" / "提案",
        "log": root / "检修" / "calls.jsonl",
    }
