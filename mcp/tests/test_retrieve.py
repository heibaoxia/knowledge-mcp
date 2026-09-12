"""Block 2 gates: search landmarks only; read must name a part; cap size."""
from pathlib import Path


def plant_book(
    kb: Path,
    slug: str,
    title: str,
    intro: str,
    chapters: list[str],
    bodies: list[str],
    tags: str = "[心理学]",
) -> None:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True)
    toc = "\n".join(f"- {c}" for c in chapters)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: {intro}\ntags: {tags}\n"
        f"source: 原始资料归档/{slug}.epub\n---\n\n# {title}\n\n{intro}\n\n## 目录\n{toc}\n",
        encoding="utf-8",
    )
    for i, (c, b) in enumerate(zip(chapters, bodies), 1):
        (d / f"{i:02d}-ch.md").write_text(f"# {c}\n\n{b}\n", encoding="utf-8")


def plant_note(kb: Path, slug: str, title: str, intro: str, body: str) -> None:
    (kb / "资料" / "笔记" / f"{slug}.md").write_text(
        f"---\ntitle: {title}\ntype: 笔记\nintro: {intro}\ntags: [感悟]\n"
        f"generated: true\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def test_search_returns_landmarks_without_body(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "讲拖延从哪来。",
        ["第一章 为什么拖"],
        ["SECRET_BODY_TOKEN 这一章很长很长。"],
    )
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert "拖延心理学" in out
    assert "书/delay" in out
    assert "SECRET_BODY_TOKEN" not in out
    assert not out.startswith("失败")


def test_search_body_token_is_not_a_hit(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "讲拖延从哪来。",
        ["第一章 为什么拖"],
        ["SECRET_BODY_TOKEN"],
    )
    from knowledge_mcp.retrieve import search

    out = search("SECRET_BODY_TOKEN")
    assert "拖延心理学" not in out
    assert "SECRET_BODY_TOKEN" not in out


def test_search_books_and_notes_together(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["正文"])
    plant_note(kb, "my-delay", "我的拖延对策", "自己用过的办法。", "笔记正文不该出现。")
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert "拖延心理学" in out
    assert "我的拖延对策" in out
    assert "笔记/my-delay" in out
    assert "笔记正文不该出现" not in out


def test_search_empty_is_honest(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["正文"])
    from knowledge_mcp.retrieve import search

    out = search("量子场论")
    assert "拖延心理学" not in out
    assert "没有" in out or "0" in out


def test_search_caps_at_five(kb):
    for i in range(8):
        plant_note(kb, f"n{i}", f"拖延笔记{i}", "关于拖延。", "x")
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert out.count("笔记/n") <= 5


def test_read_without_identity_refused(kb):
    from knowledge_mcp.retrieve import read

    out = read("", None)
    assert out.startswith("失败")
    assert "卡在哪一步" in out


def test_read_whole_book_refused(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["整章正文ABC"])
    from knowledge_mcp.retrieve import read

    out = read("书/delay", None)
    assert out.startswith("失败")
    assert "整章正文ABC" not in out


def test_read_named_chapter(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "教材。",
        ["第一章 为什么拖", "第二章 怎么改"],
        ["第一章正文AAA", "第二章正文BBB"],
    )
    from knowledge_mcp.retrieve import read

    out = read("书/delay", "第一章 为什么拖")
    assert "第一章正文AAA" in out
    assert "第二章正文BBB" not in out


def test_read_has_char_cap(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["字" * 20000])
    from knowledge_mcp.retrieve import read

    out = read("书/delay", "第一章")
    assert not out.startswith("失败")
    assert len(out) < 12000
    assert "截断" in out


def test_read_note_by_id(kb):
    plant_note(kb, "my-delay", "我的拖延对策", "办法。", "只此一段。")
    from knowledge_mcp.retrieve import read

    out = read("笔记/my-delay", None)
    assert "只此一段" in out
