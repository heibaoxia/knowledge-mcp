"""真书暴露的缺口：中文书名、EPUB 元数据、章节文件名、来源水印。

对应提案 检修/提案/2026-09-12-入库抬头中文书失效.md
"""
import zipfile
from pathlib import Path

import pytest

from knowledge_mcp.ingest import convert_one, slugify
from tests.conftest import drop_source, stub_convert

CH = "被讨厌的勇气：“自我启发之父”阿德勒的哲学课"
NL = "\n"


def make_epub(path: Path, *, title: str | None = None, body: str = "\n") -> Path:
    """最小 EPUB：只有 container.xml 和 content.opf。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        meta = f"<dc:title>{title}</dc:title>" if title else ""
        z.writestr(
            "content.opf",
            f'<?xml version="1.0"?><package xmlns:dc="d"><metadata>{meta}</metadata>'
            f"<manifest/><spine/></package>",
        )
    return path


def chinese_markdown() -> str:
    return (
        "# 版权信息\n\nCOPYRIGHT\n\n"
        f"# {CH}\n\n这本书讲阿德勒心理学。\n\n"
        "## 第一夜 我们的不幸是谁的错？\n\n第一夜正文。\n\n"
        "## 第二夜 一切烦恼都来自人际关系\n\n第二夜正文。\n"
    )


def read_guide(book_dir: Path) -> str:
    return (book_dir / "导读.md").read_text(encoding="utf-8")


def test_epub_metadata_wins_over_copyright_heading(kb, monkeypatch):
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chinese_markdown()))
    src = drop_source(kb, "z-library.sk、1lib.sk 被讨厌的勇气.epub")
    make_epub(src, title=CH)
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert f"title: {CH}" in guide


def test_copyright_page_does_not_become_the_book_title(kb, monkeypatch):
    """版权页常见在第一个一级标题；书名不许是它（没有 EPUB 元数据时也要成立）。

    注意：版权这一块正文照留不删——规格要求按一级标题切，切出来就是一块。
    """
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chinese_markdown()))
    src = drop_source(kb, "simple.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "title: 版权信息" not in guide
    assert f"title: {CH}" in guide  # 取的是书里那个一级标题


def chaptered_markdown() -> str:
    """更像真书的桩：每一章各有一个一级标题。"""
    return (
        "# 版权信息" + NL + NL + "COPYRIGHT" + NL + NL
        + "# " + CH + NL + NL + "这本书讲阿德勒心理学。" + NL + NL
        + "# 第一夜 我们的不幸是谁的错？" + NL + NL + "第一夜正文。" + NL + NL
        + "# 第二夜 一切烦恼都来自人际关系" + NL + NL + "第二夜正文。" + NL
    )


def test_intro_ignores_labelled_title_line(kb, monkeypatch):
    """markitdown 会把书名输出成 **Title:** …，这行也不能当介绍。"""
    md = (
        "# " + CH + NL + NL
        + "**Title:** " + CH + NL + NL
        + "这本书讲阿德勒心理学。" + NL + NL
        + "## 第一夜 我们的不幸是谁的错？" + NL + NL + "正文。" + NL
    )
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(md))
    src = drop_source(kb, "labelled.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "intro: 这本书讲阿德勒心理学。" in guide


def test_intro_skips_metadata_field_lines(kb, monkeypatch):
    """markitdown 会输出 **Language:** zh 这类元数据行，不能当介绍。"""
    md = (
        "# " + CH + NL + NL
        + "**Title:** " + CH + NL
        + "**Language:** zh" + NL
        + "**Author:** 岸见一郎" + NL + NL
        + "这本书讲阿德勒心理学。" + NL
    )
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(md))
    src = drop_source(kb, "meta.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "intro: 这本书讲阿德勒心理学。" in guide
    assert "Language" not in guide.split("---")[1]


def test_metadata_only_book_gets_placeholder_intro(kb, monkeypatch):
    """整本书只有元数据、没有正文时，介绍要退回占位话，不能抄元数据。"""
    md = (
        "# " + CH + NL + NL
        + "**Title:** " + CH + NL
        + "**Language:** zh" + NL
    )
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(md))
    src = drop_source(kb, "metaonly.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "intro: 由源文件转换，含 1 块。" in guide


def test_intro_skips_copyright_page(kb, monkeypatch):
    """抬头里的几句话不许是 COPYRIGHT，要取书里第一块真内容。"""
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chaptered_markdown()))
    src = drop_source(kb, "intro.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "intro: COPYRIGHT" not in guide
    assert "intro: 这本书讲阿德勒心理学。" in guide


def test_only_copyright_page_falls_back_to_filename(kb, monkeypatch):
    """书里只有一块版权页时，姓名兜底只能来自源文件名，绝不许把版权页当书名。"""
    only_copyright = "# 版权信息" + NL + NL + "COPYRIGHT" + NL
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(only_copyright))
    src = drop_source(kb, "被讨厌的勇气.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert "title: 被讨厌的勇气" in guide.splitlines()
    assert "title: 版权信息" not in guide


def test_chapter_files_keep_their_titles(kb, monkeypatch):
    """章文件名要看得见章标题：不许缩成 chapter，也不许变成纯序号。"""
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chaptered_markdown()))
    src = drop_source(kb, "chapters.epub")
    info = convert_one(src)
    book = Path(info["dir"])
    names = sorted(p.name for p in book.glob("*.md"))
    assert not list(book.glob("*chapter*"))
    assert "01-版权信息.md" in names
    assert "02-" + CH + ".md" in names
    assert "03-第一夜 我们的不幸是谁的错？.md" in names
    assert "04-第二夜 一切烦恼都来自人际关系.md" in names
    assert "导读.md" in names


def test_slug_cleans_source_watermark(kb, monkeypatch):
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chinese_markdown()))
    src = drop_source(kb, "被讨厌的勇气 (z-library.sk, 1lib.sk).epub")
    info = convert_one(src)
    assert "z-library" not in info["dir"]
    assert "1lib" not in info["dir"]


def test_empty_slug_falls_back_to_ascii_book_hash():
    assert slugify("被讨厌的勇气") == ""
    assert slugify("   ") == ""


def test_chinese_stem_gets_readable_archive_and_book_dir(kb, monkeypatch):
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert(chinese_markdown()))
    src = drop_source(kb, "被讨厌的勇气.epub")
    info = convert_one(src)
    guide = read_guide(Path(info["dir"]))
    assert info["dir"].split("/")[-1].startswith("book-")
    assert "被讨厌的勇气.epub" in guide
    assert not (kb / "原始资料" / "被讨厌的勇气.epub").exists()
