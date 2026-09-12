"""Block 4 gates: scan then apply; touching a book rejects the whole plan."""
from pathlib import Path


def plant_note(kb: Path, slug: str, text: str) -> Path:
    p = kb / "资料" / "笔记" / f"{slug}.md"
    p.write_text(text, encoding="utf-8")
    return p


def plant_book(kb: Path) -> Path:
    d = kb / "资料" / "书" / "delay"
    d.mkdir(parents=True)
    p = d / "导读.md"
    p.write_text(
        "---\ntitle: 拖延心理学\ntype: 书\nintro: 教材。\n---\n\n# 拖延心理学\n",
        encoding="utf-8",
    )
    (d / "正文.md").write_text("原书不可改。\n", encoding="utf-8")
    return p


SHORT = "---\ntitle: 短\ntype: 笔记\nintro: 太短了。\n---\n\n嗯。\n"
DUP_A = "---\ntitle: 同一主题\ntype: 笔记\nintro: 第一条。\n---\n\n" + "内容甲。" * 20 + "\n"
DUP_B = "---\ntitle: 同一主题\ntype: 笔记\nintro: 第二条。\n---\n\n" + "内容乙。" * 20 + "\n"
KEEP = "---\ntitle: 留下\ntype: 笔记\nintro: 正常笔记。\n---\n\n" + "正常正文。" * 20 + "\n"


def test_scan_does_not_delete(kb):
    plant_note(kb, "short", SHORT)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert (kb / "资料" / "笔记" / "short.md").exists()
    assert "短" in out or "short" in out
    assert "删" not in out or "不删" in out or "清单" in out


def test_apply_book_rejects_whole_plan(kb):
    plant_book(kb)
    keep = plant_note(kb, "keep", KEEP)
    from knowledge_mcp.notes import lint_notes

    plan = '[{"op":"delete","target":"笔记/keep"},{"op":"delete","target":"书/delay"}]'
    out = lint_notes("apply", plan)
    assert out.startswith("失败")
    assert keep.exists()
    assert "原书不可改" in (kb / "资料" / "书" / "delay" / "正文.md").read_text(
        encoding="utf-8"
    )


def test_apply_deletes_only_listed_notes(kb):
    gone = plant_note(kb, "short", SHORT)
    stay = plant_note(kb, "keep", KEEP)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"delete","target":"笔记/short"}]')
    assert not out.startswith("失败"), out
    assert not gone.exists()
    assert stay.exists()


def test_scan_flags_dupes_and_short(kb):
    plant_note(kb, "a", DUP_A)
    plant_note(kb, "b", DUP_B)
    plant_note(kb, "short", SHORT)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "同一主题" in out
    assert "短" in out or "short" in out
