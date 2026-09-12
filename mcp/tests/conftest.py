from pathlib import Path

import pytest


@pytest.fixture
def kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KNOWLEDGE_ROOT", str(tmp_path))
    for p in (
        "原始资料",
        "原始资料归档",
        "资料/书",
        "资料/笔记",
        "检修/提案",
    ):
        (tmp_path / p).mkdir(parents=True)
    return tmp_path


def drop_source(kb: Path, name: str = "demo.epub") -> Path:
    src = kb / "原始资料" / name
    src.write_bytes(b"fake-source")
    return src


def fake_markdown(title: str = "拖延心理学") -> str:
    return (
        f"# {title}\n\n"
        "这是一本关于拖延的书。\n\n"
        "## 第一章 为什么拖\n\n第一章正文若干字。\n\n"
        "## 第二章 怎么改\n\n第二章正文若干字。\n"
    )


def stub_convert(md: str | None = None):
    text = md if md is not None else fake_markdown()

    def _run(src: Path, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / (Path(src).stem + ".md")
        dest.write_text(text, encoding="utf-8")
        return dest

    return _run
