"""Knowledge MCP. Six doors over a Markdown room."""
from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from knowledge_mcp.ingest import ingest_inbox, ingest_named
from knowledge_mcp.inspect import inspect
from knowledge_mcp.notes import lint_notes, write_note
from knowledge_mcp.retrieve import read as retrieve_read
from knowledge_mcp.retrieve import search as retrieve_search

mcp = FastMCP(
    name="knowledge",
    instructions=(
        "这是本机资料室。人点名用它时再来。"
        "检索先拿路标再点名阅读；书从源文件入库；笔记另走写笔记和净化；"
        "自检只看记录出建议，不能改本工具源码。"
        "不要为了省事去直接打开资料文件夹灌全文。"
    ),
)


@mcp.tool
def kb_search(query: str = "", q: str = "") -> str:
    """检索资料室。输入你想了解什么。现在只回路标，不返回章节正文。书和笔记一起搜。"""
    return retrieve_search(query or q)


@mcp.tool
def kb_read(target: str, part: Optional[str] = None) -> str:
    """阅读某一份资料的某一块。必须先检索得到身份再点名。一次一块，有字数上限。"""
    return retrieve_read(target, part)


@mcp.tool
def kb_ingest_inbox() -> str:
    """收件箱入库：把「原始资料」文件夹里现有的 PDF/EPUB/MOBI 全部转换成书。"""
    return ingest_inbox()


@mcp.tool
def kb_ingest_files(paths: list[str]) -> str:
    """指定入库：只转换这些源文件路径。指定的是文件，不是书名。找不到文件不要编书。"""
    return ingest_named(paths)


@mcp.tool
def kb_write_note(
    markdown: str,
    action: str = "preview",
    target: Optional[str] = None,
) -> str:
    """写笔记。只能进笔记，不能当书。先 action=preview 看类似条目，再 create 或 update。"""
    return write_note(markdown, action, target)


@mcp.tool
def kb_lint_notes(action: str = "scan", plan: Optional[str] = None) -> str:
    """净化笔记。先 scan 出清单，再 apply 提交处理。只动笔记，动书会拒绝。"""
    return lint_notes(action, plan)


@mcp.tool
def kb_inspect(look_back: str = "7d", proposal: Optional[str] = None) -> str:
    """自检：查看最近的调用和失败记录。只给记录和建议材料，不改闸门、不改源码。提案写入检修/提案/。"""
    return inspect(look_back, proposal)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
