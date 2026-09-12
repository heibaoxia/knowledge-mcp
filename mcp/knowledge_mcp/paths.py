"""Repo layout. Override with KNOWLEDGE_ROOT for tests."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("KNOWLEDGE_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


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
