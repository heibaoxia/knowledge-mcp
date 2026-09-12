"""Block 3 gates: search-before-write; notes only; never touch books."""
from pathlib import Path


def plant_book(kb: Path) -> None:
    d = kb / "资料" / "书" / "delay"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 书\nintro: 教材。\ntags: []\n---\n\n# 拖延心理学\n",
        encoding="utf-8",
    )
    (d / "正文.md").write_text("# 正文\n原书不可改。\n", encoding="utf-8")


NOTE = """---
title: 我的拖延对策
type: 笔记
intro: 自己用过的办法。
---

# 我的拖延对策

先拆成很小的一步。
"""


def test_create_without_preview_refused(kb):
    from knowledge_mcp.notes import write_note

    out = write_note(NOTE, action="create")
    assert out.startswith("失败")
    assert "搜" in out or "预览" in out
    assert list((kb / "资料" / "笔记").glob("*.md")) == []


def test_preview_does_not_write(kb):
    from knowledge_mcp.notes import write_note

    out = write_note(NOTE, action="preview")
    assert list((kb / "资料" / "笔记").glob("*.md")) == []
    assert not out.startswith("失败")


def test_create_after_preview_writes_note(kb):
    from knowledge_mcp.notes import write_note

    write_note(NOTE, action="preview")
    out = write_note(NOTE, action="create")
    assert not out.startswith("失败"), out
    notes = list((kb / "资料" / "笔记").glob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "我的拖延对策" in text
    assert "type: 笔记" in text or "type:笔记" in text


def test_cannot_write_into_books(kb):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    write_note(NOTE, action="preview")
    out = write_note(NOTE, action="create", target="书/delay")
    assert out.startswith("失败")
    assert "原书不可改" in (kb / "资料" / "书" / "delay" / "正文.md").read_text(
        encoding="utf-8"
    )
    books_md = list((kb / "资料" / "书").rglob("*.md"))
    assert all("我的拖延对策" not in p.read_text(encoding="utf-8") for p in books_md)


def test_update_book_target_refused(kb):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    write_note(NOTE, action="preview")
    out = write_note(NOTE, action="update", target="书/delay")
    assert out.startswith("失败")
    assert "原书不可改" in (kb / "资料" / "书" / "delay" / "正文.md").read_text(
        encoding="utf-8"
    )


def test_missing_title_refused(kb):
    from knowledge_mcp.notes import write_note

    md = "没有抬头的一段话。\n"
    write_note(md, action="preview")
    out = write_note(md, action="create")
    assert out.startswith("失败")
    assert list((kb / "资料" / "笔记").glob("*.md")) == []
