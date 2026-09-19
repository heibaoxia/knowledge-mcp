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


def plant_kit(kb: Path, title: str = "林间史") -> Path:
    """合成书 kit：假书名、假 slug，独立于旧护书测试那本 delay。"""
    d = kb / "资料" / "书" / "kit"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: 合成。\n---\n\n# {title}\n",
        encoding="utf-8",
    )
    (d / "01-长.md").write_text("合成正文。\n", encoding="utf-8")
    return d


def plant_oversized_book(kb: Path, slug: str = "oversize", chars: int = 70000) -> Path:
    """一块长到不像章的书：字符数过 8 个阅读窗。"""
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        f"---\ntitle: 合成长块\ntype: 书\nintro: 测超长。\n---\n\n# 合成长块\n",
        encoding="utf-8",
    )
    (d / "01-长.md").write_text("字" * chars + "\n", encoding="utf-8")
    return d


def fs_snapshot(root: Path) -> set[str]:
    """盘上所有文件的相对路径。scan 只列不删，前后必须一模一样。"""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


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


GOOD_MAP = (
    "---\ntitle: 拖延心理学\ntype: 地图\nbook: 书/delay\ngenerated: true\n---\n\n"
    "## 能解决什么\n- 总是拖到截止日期前一晚怎么办\n- 明明想改却往后推怎么办\n- 工作一难就刷手机怎么办\n\n"
    "## 不解决什么\n- 怎么用 PyTorch\n\n"
    "## 建议从哪读\n- 书/delay/正文\n\n"
    "## 依据块\n- 总是拖到截止日期前一晚怎么办 → 书/delay/正文\n"
    "- 明明想改却往后推怎么办 → 书/delay/正文\n"
    "- 工作一难就刷手机怎么办 → 书/delay/正文\n"
    "\n## 章名\n- 正文\n"
)


def test_scan_flags_map_dead_link(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    (d / "地图.md").write_text(
        GOOD_MAP.replace("书/delay/正文", "书/delay/没有这一章"),
        encoding="utf-8",
    )
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "地图" in out
    assert "没有这一章" in out or "死" in out or "不存在" in out


def test_scan_flags_stale_map(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    import time

    (d / "地图.md").write_text(GOOD_MAP, encoding="utf-8")
    time.sleep(0.05)
    (d / "正文.md").write_text("原书不可改。又重切了。\n", encoding="utf-8")
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "stale" in out.lower() or "过期" in out or "早于" in out or "重切" in out


def test_apply_map_update_does_not_touch_body(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    import json
    from knowledge_mcp.notes import lint_notes

    out = lint_notes(
        "apply",
        json.dumps(
            [{"op": "update", "target": "书/delay/地图", "markdown": GOOD_MAP}],
            ensure_ascii=False,
        ),
    )
    assert not out.startswith("失败"), out
    assert "原书不可改" in (d / "正文.md").read_text(encoding="utf-8")
    assert (d / "地图.md").is_file()


def test_apply_chapter_still_rejected(kb):
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"delete","target":"书/delay/正文"}]')
    assert out.startswith("失败")
    assert "原书不可改" in (kb / "资料" / "书" / "delay" / "正文.md").read_text(
        encoding="utf-8"
    )


def test_withdraw_removes_book_keeps_notes(kb):
    plant_book(kb)
    keep = plant_note(kb, "keep", KEEP)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"withdraw","target":"书/delay"}]')
    assert not out.startswith("失败"), out
    assert not (kb / "资料" / "书" / "delay").exists()
    assert keep.exists()
    assert "已退" in out


def test_withdraw_chapter_rejected(kb):
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"withdraw","target":"书/delay/正文"}]')
    assert out.startswith("失败")
    assert (kb / "资料" / "书" / "delay" / "正文.md").exists()


def test_delete_op_on_book_still_rejected(kb):
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"delete","target":"书/delay"}]')
    assert out.startswith("失败")
    assert (kb / "资料" / "书" / "delay").exists()


def test_mixed_delete_note_and_withdraw_book(kb):
    plant_book(kb)
    gone = plant_note(kb, "short", SHORT)
    stay = plant_note(kb, "keep", KEEP)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes(
        "apply",
        '[{"op":"delete","target":"笔记/short"},{"op":"withdraw","target":"书/delay"}]',
    )
    assert not out.startswith("失败"), out
    assert not gone.exists()
    assert stay.exists()
    assert not (kb / "资料" / "书" / "delay").exists()


def test_withdraw_missing_rejects(kb):
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"withdraw","target":"书/nope"}]')
    assert out.startswith("失败")
    assert (kb / "资料" / "书" / "delay").exists()


def test_scan_flags_oversized_block(kb):
    d = kb / "资料" / "书" / "kit"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        "---\ntitle: 合成长块\ntype: 书\nintro: 测超长。\n---\n\n# 合成长块\n",
        encoding="utf-8",
    )
    (d / "01-长.md").write_text("字" * 70000, encoding="utf-8")
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "kit" in out and "超长" in out
    assert (d / "01-长.md").exists()


def test_scan_flags_duplicate_chapter_names(kb):
    d = kb / "资料" / "书" / "kit"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        "---\ntitle: 套装\ntype: 书\nintro: 测撞名。\n---\n\n# 套装\n",
        encoding="utf-8",
    )
    for name in ("01-第一篇.md", "02-第一篇-2.md", "03-第一篇-3.md"):
        (d / name).write_text("正文。\n", encoding="utf-8")
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "同名" in out or "撞车" in out


def test_delete_note_invalidates_index(kb):
    unique = "林间史专名甲"
    plant_note(
        kb,
        "gone",
        "---\ntitle: 离去\ntype: 笔记\nintro: 测失效。\n---\n\n"
        + (unique + "。") * 20
        + "\n",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.notes import lint_notes
    from knowledge_mcp.retrieve import search

    invalidate()
    before = search(unique)
    assert "笔记/gone" in before or "离去" in before
    lint_notes("apply", '[{"op":"delete","target":"笔记/gone"}]')
    after = search(unique)
    assert "笔记/gone" not in after


def test_apply_creates_missing_map(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    assert not (d / "地图.md").exists()
    import json
    from knowledge_mcp.notes import lint_notes

    out = lint_notes(
        "apply",
        json.dumps(
            [{"op": "update", "target": "书/delay/地图", "markdown": GOOD_MAP}],
            ensure_ascii=False,
        ),
    )
    assert not out.startswith("失败"), out
    assert (d / "地图.md").is_file()
    assert "拖延心理学" in (d / "地图.md").read_text(encoding="utf-8")


def test_apply_bad_new_map_leaves_no_file(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    import json
    from knowledge_mcp.notes import lint_notes

    bad = GOOD_MAP.replace("书/delay/正文", "书/delay/没有这一章")
    out = lint_notes(
        "apply",
        json.dumps(
            [{"op": "update", "target": "书/delay/地图", "markdown": bad}],
            ensure_ascii=False,
        ),
    )
    assert out.startswith("失败")
    assert not (d / "地图.md").exists()


def test_scan_does_not_delete_oversized(kb):
    d = kb / "资料" / "书" / "kit"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        "---\ntitle: 合成长块\ntype: 书\nintro: 测超长。\n---\n\n# 合成长块\n",
        encoding="utf-8",
    )
    (d / "01-长.md").write_text("字" * 70000, encoding="utf-8")
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "超长" in out
    assert (d / "01-长.md").exists()
    assert "不删" in out or "清单" in out
