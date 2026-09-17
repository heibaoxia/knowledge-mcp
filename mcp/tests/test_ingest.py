"""Block 1 gates: inbox + named ingest share one convert; books from sources only."""
from pathlib import Path

import pytest

from tests.conftest import drop_source, fake_markdown, stub_convert


def _patch_convert(monkeypatch, md: str | None = None):
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(md))


def test_empty_inbox_uses_fail_handoff(kb):
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert out.startswith("失败")
    assert "卡在哪一步" in out
    assert "为什么" in out
    assert "已经做成了什么" in out
    assert "正门上还能怎么试" in out


def test_inbox_writes_guide_and_archives_source(kb, monkeypatch):
    _patch_convert(monkeypatch)
    drop_source(kb, "delay.epub")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败")
    books = kb / "资料" / "书"
    slugs = [p for p in books.iterdir() if p.is_dir()]
    assert len(slugs) == 1
    guide = slugs[0] / "导读.md"
    assert guide.is_file()
    text = guide.read_text(encoding="utf-8")
    assert "拖延心理学" in text
    assert "第一章 为什么拖" in text
    assert "第二章 怎么改" in text
    assert "type: 书" in text or "type:书" in text
    assert not (kb / "原始资料" / "delay.epub").exists()
    archived = list((kb / "原始资料归档").glob("delay.epub"))
    assert archived


def test_named_and_inbox_share_convert(kb, monkeypatch):
    calls = []

    def spy(src, out_dir):
        calls.append(Path(src).name)
        return stub_convert()(src, out_dir)

    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", spy)
    a = drop_source(kb, "a.epub")
    drop_source(kb, "b.epub")
    from knowledge_mcp.ingest import ingest_inbox, ingest_named

    ingest_named([str(a)])
    ingest_inbox()
    assert calls == ["a.epub", "b.epub"]


def test_named_leaves_other_inbox_files(kb, monkeypatch):
    _patch_convert(monkeypatch)
    a = drop_source(kb, "keep-me.epub")
    b = drop_source(kb, "take-me.pdf")
    from knowledge_mcp.ingest import ingest_named

    ingest_named([str(b)])
    assert a.exists()
    assert not b.exists()
    assert (kb / "原始资料归档" / "take-me.pdf").exists()


def test_named_rejects_book_title_not_path(kb):
    from knowledge_mcp.ingest import ingest_named

    out = ingest_named(["思考快与慢"])
    assert out.startswith("失败")
    assert "文件" in out
    books = [p for p in (kb / "资料" / "书").iterdir() if p.is_dir()]
    assert books == []


def test_named_missing_file_touches_nothing(kb, monkeypatch):
    _patch_convert(monkeypatch)
    drop_source(kb, "still-here.epub")
    from knowledge_mcp.ingest import ingest_named

    out = ingest_named([str(kb / "no-such.pdf")])
    assert out.startswith("失败")
    assert (kb / "原始资料" / "still-here.epub").exists()
    books = [p for p in (kb / "资料" / "书").iterdir() if p.is_dir()]
    assert books == []


def test_markdown_cannot_be_ingested_as_book(kb):
    fake = kb / "handwritten.md"
    fake.write_text("# 假书\n\n没有源文件。\n", encoding="utf-8")
    from knowledge_mcp.ingest import ingest_named

    out = ingest_named([str(fake)])
    assert out.startswith("失败")
    books = [p for p in (kb / "资料" / "书").iterdir() if p.is_dir()]
    assert books == []


def test_convert_fail_keeps_source_continues_others(kb, monkeypatch):
    def flaky(src, out_dir):
        if Path(src).name == "bad.epub":
            raise RuntimeError("boom")
        return stub_convert()(src, out_dir)

    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", flaky)
    drop_source(kb, "bad.epub")
    drop_source(kb, "good.pdf")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert (kb / "原始资料" / "bad.epub").exists()
    assert not (kb / "原始资料" / "good.pdf").exists()
    assert (kb / "原始资料归档" / "good.pdf").exists()
    assert "bad.epub" in out
    assert "卡在哪一步" in out or "失败" in out


def _tiny_epub(path: Path) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles><rootfile full-path=\"OEBPS/content.opf\" "
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'unique-identifier="BookId" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>验收小书</dc:title><dc:language>zh</dc:language>"
            '<dc:identifier id="BookId">urn:uuid:1234</dc:identifier></metadata>'
            "<manifest><item id=\"ch1\" href=\"ch1.xhtml\" "
            'media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            "</manifest><spine toc=\"ncx\"><itemref idref=\"ch1\"/></spine></package>",
        )
        z.writestr(
            "OEBPS/ch1.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
            "<h1>验收小书</h1><p>这是验收用的一小段。</p>"
            "<h2>第一章 开门</h2><p>正文在这里。</p></body></html>",
        )


def test_real_epub_inbox_makes_guide_and_archives(kb):
    src = kb / "原始资料" / "yanshou.epub"
    _tiny_epub(src)
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败"), out
    guides = list((kb / "资料" / "书").glob("*/导读.md"))
    assert len(guides) == 1
    text = guides[0].read_text(encoding="utf-8")
    assert "验收小书" in text
    assert "第一章 开门" in text
    assert not src.exists()
    assert (kb / "原始资料归档" / "yanshou.epub").exists()


def test_clean_heading_strips_epub_anchor():
    from knowledge_mcp.ingest import clean_heading

    assert clean_heading("实践论[\\*](#id0a)") == "实践论"


def test_split_uses_h3_not_h1_volume():
    from knowledge_mcp.ingest import split_markdown

    text = "# 第一卷\n\n前言若干。\n\n### 实践论\n\n实践论正文。\n\n### 矛盾论\n\n矛盾论正文。\n"
    title, _, parts = split_markdown(text, "毛选")
    names = [n for n, _ in parts]
    assert "实践论" in names
    assert "矛盾论" in names
    assert "第一卷" not in names


def test_structure_lines_ignored_when_atx_present():
    from knowledge_mcp.ingest import split_markdown

    text = "# 第一章 生活的意义\n\n正文。\n\n一、先说土地\n\n还是同一章。\n"
    _, _, parts = split_markdown(text, "书")
    assert len(parts) == 1
    assert "生活的意义" in parts[0][0]


def test_structure_lines_used_when_no_atx():
    from knowledge_mcp.ingest import split_markdown

    text = "第一章 生活的意义\n\n甲段。\n\n第二章 心理与身体\n\n乙段。\n"
    _, _, parts = split_markdown(text, "书")
    assert len(parts) == 2
    assert "生活的意义" in parts[0][0]


def test_split_keeps_text_before_first_heading():
    from knowledge_mcp.ingest import split_markdown

    text = "出版说明在前。\n\n# 正章\n\n章正文。\n"
    _, _, parts = split_markdown(text, "书")
    blob = "".join(b for _, b in parts)
    assert "出版说明在前" in blob


def test_conservation_over_99_percent():
    from knowledge_mcp.ingest import split_markdown

    text = "# A\n\n" + ("字" * 1000) + "\n\n### B\n\n" + ("词" * 1000) + "\n"
    _, _, parts = split_markdown(text, "书")
    got = sum(len(b) for _, b in parts)
    assert got >= int(len(text) * 0.99)


def test_h3_article_keeps_h4_sections():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "# 第一卷\n\n"
        "### 矛盾论\n\n引言。\n\n"
        "#### 一　两种宇宙观\n\n甲。\n\n"
        "#### 二　矛盾的普遍性\n\n乙。\n"
    )
    _, _, parts = split_markdown(text, "毛选")
    names = [n for n, _ in parts]
    assert names == ["矛盾论"]
    assert "两种宇宙观" in parts[0][1]
    assert "矛盾的普遍性" in parts[0][1]


def test_period_heading_joins_following_article():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "# 第一卷\n\n"
        "### 出版说明\n\n说明正文。\n\n"
        "## 第一次国内革命战争时期\n\n"
        "### 中国社会各阶级的分析\n\n分析正文。\n"
    )
    _, _, parts = split_markdown(text, "毛选")
    names = [n for n, _ in parts]
    assert names == ["出版说明", "中国社会各阶级的分析"]
    assert "第一次国内革命战争时期" in parts[1][1]
    assert "第一次国内革命战争时期" not in parts[0][1]


def test_chapter_h1_not_sunk_to_h3():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "# 7 记忆\n\n章引言。\n\n"
        "## 什么是记忆\n\n"
        "### 短时记忆\n\n短时记忆正文。\n\n"
        "# 8 认知\n\n另一章。\n"
    )
    _, _, parts = split_markdown(text, "书")
    names = [n for n, _ in parts]
    assert len(parts) == 2
    assert "短时记忆" not in names
    assert "记忆" in names[0]


def test_no_atx_volume_prefixes_duplicate_pian():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "套装（第一卷）\n\n"
        "第一篇 甲篇\n\n甲正文。\n\n"
        "第一章 商品\n\n商品正文。\n\n"
        "套装（第二卷）\n\n"
        "第一篇 乙篇\n\n乙正文。\n\n"
        "第一章 循环\n\n循环正文。\n"
    )
    _, _, parts = split_markdown(text, "套装")
    names = [n for n, _ in parts]
    vol1 = [n for n in names if "第一卷" in n]
    vol2 = [n for n in names if "第二卷" in n]
    assert vol1 and vol2, names
    assert any("商品" in n for n in vol1)
    assert any("循环" in n for n in vol2)
    bare = [n for n in names if n in ("第一篇 甲篇", "第一篇 乙篇", "第一章 商品", "第一章 循环")]
    assert not bare, names


def test_no_atx_link_volume_still_counts():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "[套装（第一卷）](part1.html)\n\n"
        "套装（第一卷）\n\n"
        "第一篇 甲篇\n\n甲正文。\n\n"
        "[套装（第二卷）](part2.html)\n\n"
        "套装（第二卷）\n\n"
        "第一篇 乙篇\n\n乙正文。\n"
    )
    _, _, parts = split_markdown(text, "套装")
    names = [n for n, _ in parts]
    assert any("第一卷" in n and "甲篇" in n for n in names), names
    assert any("第二卷" in n and "乙篇" in n for n in names), names


def test_yi_clause_not_a_cut_without_atx():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "第一章 革命委员会\n\n章引言。\n\n"
        "一、必须坚决支持真正的无产阶级革命派，争取团结大多数\n\n条款正文。\n\n"
        "第二章 不进则退\n\n另一章。\n"
    )
    _, _, parts = split_markdown(text, "史")
    names = [n for n, _ in parts]
    assert len(parts) == 2, names
    assert "必须坚决" in parts[0][1]
    assert not any(n.startswith("一、") for n in names)


def test_toc_link_is_not_a_cut():
    from knowledge_mcp.ingest import split_markdown

    text = (
        "[套装（第一卷）](a.html)\n\n"
        "[第一章 商品](b.html)\n\n"
        "套装（第一卷）\n\n"
        "第一章 商品\n\n真正的商品正文若干字。\n"
    )
    _, _, parts = split_markdown(text, "套装")
    assert len(parts) == 1, [n for n, _ in parts]
    assert "第一卷" in parts[0][0] and "商品" in parts[0][0]
    assert "真正的商品" in parts[0][1]


def test_short_yi_title_still_cuts_when_no_atx():
    from knowledge_mcp.ingest import split_markdown

    text = "一、总则\n\n总则正文。\n\n二、分则\n\n分则正文。\n"
    _, _, parts = split_markdown(text, "法")
    assert len(parts) == 2
    assert "总则" in parts[0][0]
    assert "分则" in parts[1][0]


def test_guide_comes_from_headings_not_llm(kb, monkeypatch):
    md = fake_markdown("矛盾论")
    _patch_convert(monkeypatch, md)
    drop_source(kb, "maodun.epub")
    from knowledge_mcp.ingest import ingest_inbox

    ingest_inbox()
    guides = list((kb / "资料" / "书").glob("*/导读.md"))
    assert len(guides) == 1
    text = guides[0].read_text(encoding="utf-8")
    assert "矛盾论" in text
    assert "第一章 为什么拖" in text
    assert "LLM" not in text


def test_inbox_reports_missing_map(kb, monkeypatch):
    _patch_convert(monkeypatch)
    drop_source(kb, "delay.epub")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败")
    assert "缺地图" in out
    slugs = list((kb / "资料" / "书").iterdir())
    assert slugs and not (slugs[0] / "地图.md").is_file()


def test_convert_one_calls_invalidate(kb, monkeypatch):
    _patch_convert(monkeypatch)
    called = []
    monkeypatch.setattr("knowledge_mcp.ingest.invalidate", lambda: called.append(1))
    src = drop_source(kb, "delay.epub")
    from knowledge_mcp.ingest import convert_one

    convert_one(src)
    assert called


def test_image_only_ingest_leaves_source(kb, monkeypatch):
    md = "封面\n\n" + "\n".join(f"![p](img-{i}.jpg)" for i in range(30))
    _patch_convert(monkeypatch, md)
    src = drop_source(kb, "scan-only.epub")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert out.startswith("失败")
    assert "无文字层" in out or "不 OCR" in out
    assert src.exists()
    assert list((kb / "资料" / "书").glob("*")) == []
    assert list((kb / "原始资料归档").glob("*")) == []


def test_numeric_stem_gets_hash_slug(kb, monkeypatch):
    _patch_convert(monkeypatch, fake_markdown("林间史"))
    drop_source(kb, "123-456.epub")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败"), out
    books = [p for p in (kb / "资料" / "书").iterdir() if p.is_dir()]
    assert len(books) == 1
    assert books[0].name.startswith("book-")
    assert books[0].name != "123-456"
    guide = (books[0] / "导读.md").read_text(encoding="utf-8")
    assert "林间史" in guide


def test_pick_title_skips_chapter_heading(kb, monkeypatch):
    md = "# 第一章 现代民族国家\n\n正文若干字。\n\n## 第二节 某处\n\n还是正文。\n"
    _patch_convert(monkeypatch, md)
    drop_source(kb, "forest-history.pdf")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败"), out
    guide = next((kb / "资料" / "书").glob("*/导读.md")).read_text(encoding="utf-8")
    title_line = guide.split("title:", 1)[1].splitlines()[0]
    assert "第一章" not in title_line
    assert "forest-history" in guide or "forest" in guide.lower()
