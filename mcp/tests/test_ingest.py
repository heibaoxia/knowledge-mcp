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
