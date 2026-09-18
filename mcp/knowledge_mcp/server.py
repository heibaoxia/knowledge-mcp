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
        '这是本机资料室。人点名用它时再来。'
        '先 kb_search 拿路标（无正文，三栏：两路都中 / 仅字面 / 仅语义），再 kb_read 点名建议块。不要打开资料/灌全文。'
        '一次最多 5 块，每块约 8000 字，整次约 24000 字。'
        '超长篇用 块名#2 续下一窗，不要通读目录。够答就停。'
        '写笔记：preview → verify → create/update。'
        '坏书走 kb_lint_notes：先 scan，再 apply withdraw 点名 书/<slug>，不要去删文件夹。'
        '自检不改本工具源码。'
    ),
)


@mcp.tool
def kb_search(query: str = "", q: str = "") -> str:
    """检索资料室。输入你想了解什么。只回路标（含建议块），无正文。两路都跑，路标三栏：两路都中 / 仅字面 / 仅语义。书和笔记一起搜。先检索再点名阅读；够答就停，不要按目录把每章都读完。"""
    return retrieve_search(query or q)


@mcp.tool
def kb_read(
    target: str = "",
    part: Optional[str] = None,
    targets: Optional[list[str]] = None,
) -> str:
    """阅读点名的块。先检索拿身份再点。单块：target + part。多块：targets=[书/<slug>/<章> 或 笔记/<slug>]，一次最多 5 块、单块顶 8000 字、整次顶 24000 字；超顶截断并列出没读到的项；某块找不到只这一块失败交还；没身份或点名整本（书/<slug>）整单拒绝。超长章只给开头；同一身份再读不会续后半。不够请换问法再检索或点另一章。够答就停。检索默认无正文。"""
    return retrieve_read(target, part, targets)


@mcp.tool
def kb_ingest_inbox() -> str:
    """收件箱入库：把「原始资料」文件夹里现有的 PDF/EPUB/MOBI 全部转换成书。入库后每本书要有合格地图才算入完；缺地图时回报里会给「编地图」工作单，编好走 kb_lint_notes apply（地图不存在也能 update 新建）。"""
    return ingest_inbox()


@mcp.tool
def kb_ingest_files(paths: list[str]) -> str:
    """指定入库：只转换这些源文件路径。指定的是文件，不是书名。找不到文件不要编书。入库后同样要有合格地图；缺地图时照回报里的工作单编，走 kb_lint_notes apply。"""
    return ingest_named(paths)


@mcp.tool
def kb_write_note(
    markdown: str,
    action: str = "preview",
    target: Optional[str] = None,
) -> str:
    """写笔记。只能进笔记，不能当书。先 action=preview 看类似条目，再 action=verify（稿上 verify：相符 / 部分不符 / 库中无 / 非事实），再 create 或 update；相符 / 部分不符 必须先成功 kb_read 过 sources 里的身份。"""
    return write_note(markdown, action, target)


@mcp.tool
def kb_lint_notes(action: str = "scan", plan: Optional[str] = None) -> str:
    """净化笔记、地图；scan 含书的未入完。先 scan 出清单，再 apply。笔记可删改合并；地图可改/标过期，**地图没有也能 update 新建**（target=书/<slug>/地图）；整本可 withdraw（target=书/<slug>）。动某一章会拒绝。"""
    return lint_notes(action, plan)


@mcp.tool
def kb_inspect(look_back: str = "7d", proposal: Optional[str] = None) -> str:
    """自检：查看最近的调用和失败记录。只给记录和建议材料，不改闸门、不改源码。提案写入检修/提案/。"""
    return inspect(look_back, proposal)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
