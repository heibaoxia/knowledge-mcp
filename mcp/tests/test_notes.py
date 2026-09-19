"""Block 7 gates: preview → verify → create/update; claims need real reads."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def plant_book(kb: Path) -> None:
    d = kb / "资料" / "书" / "delay"
    d.mkdir(parents=True)
    (d / "导读.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 书\nintro: 教材。\ntags: []\n---\n\n# 拖延心理学\n",
        encoding="utf-8",
    )
    (d / "01-ch.md").write_text(
        "# 第一章 为什么拖\n\n拖延从逃避开始。\n", encoding="utf-8"
    )
    (d / "正文.md").write_text("# 正文\n原书不可改。\n", encoding="utf-8")


CHAPTER = "书/delay/第一章 为什么拖"


def draft(
    verify: str | None = None,
    sources: list[str] | None = None,
    body: str = "先拆成很小的一步。",
) -> str:
    head = "---\ntitle: 我的拖延对策\ntype: 笔记\nintro: 自己用过的办法。\n"
    if verify is not None:
        head += f"verify: {verify}\n"
    if sources is not None:
        head += "sources:\n" + "".join(f"  - {s}\n" for s in sources)
    head += "---\n\n# 我的拖延对策\n\n" + body + "\n"
    return head


NOTE = draft()


def notes_of(kb: Path) -> list[Path]:
    return list((kb / "资料" / "笔记").glob("*.md"))


def test_create_without_preview_refused(kb):
    from knowledge_mcp.notes import write_note

    out = write_note(NOTE, action="create")
    assert out.startswith("失败")
    assert "搜" in out or "预览" in out
    assert notes_of(kb) == []


def test_preview_does_not_write(kb):
    from knowledge_mcp.notes import write_note

    out = write_note(NOTE, action="preview")
    assert notes_of(kb) == []
    assert not out.startswith("失败")


def test_create_after_preview_only_refused(kb):
    """Block 7: preview alone is no longer enough; the old path must go red."""
    from knowledge_mcp.notes import write_note

    out = write_note(NOTE, action="preview")
    assert not out.startswith("失败")
    out = write_note(NOTE, action="create")
    assert out.startswith("失败")
    assert notes_of(kb) == []


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
    assert notes_of(kb) == []


def test_preview_verify_non_fact_create_writes_note(kb):
    from knowledge_mcp.notes import write_note

    md = draft("非事实")
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert not out.startswith("失败"), out
    out = write_note(md, action="create")
    assert not out.startswith("失败"), out
    notes = notes_of(kb)
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "verify: 非事实" in text
    assert "generated: true" in text


def test_missing_or_unknown_verify_refused(kb):
    from knowledge_mcp.notes import write_note

    for md in (draft(), draft("大概吧")):
        write_note(md, action="preview")
        out = write_note(md, action="verify")
        assert out.startswith("失败")
        assert "卡在哪一步" in out
        assert notes_of(kb) == []


@pytest.mark.parametrize("verdict", ["相符", "部分不符"])
def test_claim_match_without_read_refused(kb, verdict):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    md = draft(verdict, [CHAPTER])
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert out.startswith("失败")
    assert "卡在哪一步" in out
    out = write_note(md, action="create")
    assert out.startswith("失败")
    assert notes_of(kb) == []


@pytest.mark.parametrize("verdict", ["相符", "部分不符"])
def test_claim_match_after_read_writes_note(kb, verdict):
    plant_book(kb)
    from knowledge_mcp.notes import write_note
    from knowledge_mcp.retrieve import read

    assert not read("书/delay", "第一章 为什么拖").startswith("失败")
    md = draft(verdict, [CHAPTER])
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert not out.startswith("失败"), out
    out = write_note(md, action="create")
    assert not out.startswith("失败"), out
    notes = notes_of(kb)
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert f"verify: {verdict}" in text
    assert CHAPTER in text


def test_claim_match_missing_source_refused(kb):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    md = draft("相符", ["书/delay/第九章 没这章"])
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert out.startswith("失败")
    assert notes_of(kb) == []


def test_non_fact_source_must_exist(kb):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    md = draft("非事实", ["笔记/没有这条"])
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert out.startswith("失败")
    assert notes_of(kb) == []


def test_no_in_book_with_claim_refused(kb):
    from knowledge_mcp.notes import write_note

    md = draft("库中无", [], body="根据《拖延心理学》第一章，先拆成很小的一步。")
    write_note(md, action="preview")
    out = write_note(md, action="verify")
    assert out.startswith("失败")
    out = write_note(md, action="create")
    assert out.startswith("失败")
    assert notes_of(kb) == []


def test_no_in_book_without_claim_writes_note(kb):
    from knowledge_mcp.notes import write_note

    md = draft("库中无", [], body="查过了，库里没有。先拆成很小的一步。")
    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")
    assert not write_note(md, action="create").startswith("失败")
    assert "verify: 库中无" in notes_of(kb)[0].read_text(encoding="utf-8")


def test_body_change_after_verify_refused(kb):
    from knowledge_mcp.notes import write_note

    md = draft("非事实")
    write_note(md, action="preview")
    write_note(md, action="verify")
    out = write_note(draft("非事实", body="换了一整段。"), action="create")
    assert out.startswith("失败")
    assert notes_of(kb) == []


def test_verify_fields_do_not_change_the_draft(kb):
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    write_note(NOTE, action="preview")  # no verify yet
    md = draft("非事实", ["书/delay/导读"])  # same title+intro+body, plus verify/sources
    assert not write_note(md, action="verify").startswith("失败")
    assert not write_note(md, action="create").startswith("失败")
    assert len(notes_of(kb)) == 1


def test_pre_block6_read_log_target_plus_part_counts(kb):
    plant_book(kb)
    (kb / "检修" / "calls.jsonl").write_text(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "door": "kb_read",
                "ok": True,
                "target": "书/delay",
                "part": "第一章 为什么拖",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    from knowledge_mcp.notes import write_note

    md = draft("相符", [CHAPTER])
    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")


def test_read_older_than_24h_does_not_count(kb):
    plant_book(kb)
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    (kb / "检修" / "calls.jsonl").write_text(
        json.dumps(
            {
                "ts": old.isoformat(),
                "door": "kb_read",
                "ok": True,
                "target": CHAPTER,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    from knowledge_mcp.notes import write_note

    md = draft("相符", [CHAPTER])
    write_note(md, action="preview")
    assert write_note(md, action="verify").startswith("失败")


def test_read_beyond_100_calls_does_not_count(kb):
    plant_book(kb)
    from knowledge_mcp.log import log_call
    from knowledge_mcp.notes import write_note
    from knowledge_mcp.retrieve import read

    assert not read("书/delay", "第一章 为什么拖").startswith("失败")
    for i in range(100):
        log_call("kb_search", True, query=f"q{i}")
    md = draft("相符", [CHAPTER])
    write_note(md, action="preview")
    assert write_note(md, action="verify").startswith("失败")


def test_single_string_note_source_accepted(kb):
    (kb / "资料" / "笔记" / "other.md").write_text(
        "---\ntitle: 别条\ntype: 笔记\nintro: 别的。\n---\n\n# 别条\n\n别的正文。\n",
        encoding="utf-8",
    )
    from knowledge_mcp.notes import write_note
    from knowledge_mcp.retrieve import read

    assert not read("笔记/other").startswith("失败")
    md = NOTE.replace("type: 笔记\n", "type: 笔记\nverify: 相符\nsources: 笔记/other\n")
    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")
    assert not write_note(md, action="create").startswith("失败")
    text = notes_of(kb)[0].read_text(encoding="utf-8")
    assert "sources: 笔记/other" in text or "- 笔记/other" in text


def test_verdict_swapped_after_verify_refused(kb):
    """Same 稿 (key unchanged), verify says 非事实 but create says 相符: re-gate."""
    plant_book(kb)
    from knowledge_mcp.notes import write_note

    md = draft("非事实")
    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")
    out = write_note(draft("相符", [CHAPTER]), action="create")
    assert out.startswith("失败")
    assert notes_of(kb) == []


def _commit(md: str) -> str:
    from knowledge_mcp.notes import write_note

    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")
    out = write_note(md, action="create")
    assert not out.startswith("失败"), out
    return out


def test_create_invalidates_index(kb):
    from knowledge_mcp.retrieve import search

    _commit(draft("非事实"))
    out = search("我的拖延对策")
    assert "笔记/" in out
    assert "路标" in out


def test_create_says_same_retrieve_as_books(kb):
    out = _commit(draft("非事实"))
    assert "检索与书同一套" in out
    assert "求证" in out


def test_create_appends_note_map_skeleton(kb):
    _commit(draft("非事实"))
    text = notes_of(kb)[0].read_text(encoding="utf-8")
    assert "## 能解决什么" in text
    assert "## 别名" in text
    assert "## 依据块" in text
    assert "笔记/" in text


def test_preview_lists_heading_conflicts(kb):
    from knowledge_mcp.notes import write_note

    old = (
        "---\ntitle: 旧对策\ntype: 笔记\nintro: 以前的办法。\n---\n\n"
        "# 旧对策\n\n## 课题分离\n\n旧的说法。\n"
    )
    (kb / "资料" / "笔记" / "old-way.md").write_text(old, encoding="utf-8")
    md = (
        "---\ntitle: 新对策\ntype: 笔记\nintro: 新的办法。\nverify: 非事实\n---\n\n"
        "# 新对策\n\n## 课题分离\n\n新的说法，更准。\n"
    )
    out = write_note(md, action="preview")
    assert "课题分离" in out
    assert "冲突" in out


def test_same_heading_overlays_old_section(kb):
    old = (
        "---\ntitle: 旧对策\ntype: 笔记\nintro: 以前的办法。\n---\n\n"
        "# 旧对策\n\n## 课题分离\n\n旧的说法。\n\n## 其它\n\n不动。\n"
    )
    (kb / "资料" / "笔记" / "old-way.md").write_text(old, encoding="utf-8")
    md = (
        "---\ntitle: 新对策\ntype: 笔记\nintro: 新的办法。\nverify: 非事实\n---\n\n"
        "# 新对策\n\n## 课题分离\n\n新的说法，更准。\n"
    )
    _commit(md)
    old_text = (kb / "资料" / "笔记" / "old-way.md").read_text(encoding="utf-8")
    assert "新的说法，更准" in old_text
    assert "旧的说法" not in old_text
    assert "不动" in old_text
    assert "已被 笔记/" in old_text
    assert len(notes_of(kb)) >= 2


def test_same_title_no_headings_updates_instead_of_create(kb):
    (kb / "资料" / "笔记" / "old-same.md").write_text(
        "---\ntitle: 我的拖延对策\ntype: 笔记\nintro: 自己用过的办法。\n---\n\n"
        "# 我的拖延对策\n\n先拆成很小的一步。\n",
        encoding="utf-8",
    )
    _commit(draft("非事实", body="先拆成很小的一步。后来改了。"))
    notes = notes_of(kb)
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "后来改了" in text


def test_similar_but_different_headings_do_not_touch_old(kb):
    old = (
        "---\ntitle: 旧对策\ntype: 笔记\nintro: 以前的办法。\n---\n\n"
        "# 旧对策\n\n## 早起\n\n六点起床。\n"
    )
    (kb / "资料" / "笔记" / "old-way.md").write_text(old, encoding="utf-8")
    md = (
        "---\ntitle: 新对策\ntype: 笔记\nintro: 新的办法。\nverify: 非事实\n---\n\n"
        "# 新对策\n\n## 课题分离\n\n别人的事别管。\n"
    )
    _commit(md)
    old_text = (kb / "资料" / "笔记" / "old-way.md").read_text(encoding="utf-8")
    assert old_text == old


def test_windowed_read_counts_as_chapter_read(kb):
    plant_book(kb)
    (kb / "检修" / "calls.jsonl").write_text(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "door": "kb_read",
                "ok": True,
                "target": CHAPTER + "#2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    from knowledge_mcp.notes import write_note

    md = draft("相符", [CHAPTER])
    write_note(md, action="preview")
    assert not write_note(md, action="verify").startswith("失败")
