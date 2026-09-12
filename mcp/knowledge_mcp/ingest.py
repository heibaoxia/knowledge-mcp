"""Inbox + named ingest share one convert. Books only from source files."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.log import guarded, log_call
from knowledge_mcp.paths import dirs

SOURCE_EXTS = {".pdf", ".epub", ".mobi", ".azw", ".azw3"}
CONVERT = Path(
    os.environ.get(
        "KNOWLEDGE_MARKITDOWN",
        r"C:\Users\Maxingyu\.claude\skills\markitdown\scripts\convert.py",
    )
)


def run_markitdown(src: Path, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not CONVERT.is_file():
        raise RuntimeError(f"找不到 markitdown 脚本：{CONVERT}")
    r = subprocess.run(
        [sys.executable, str(CONVERT), str(src), "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "markitdown 失败").strip()[:400])
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if lines:
        printed = Path(lines[-1])
        if printed.is_file():
            return printed
    cand = out_dir / (src.stem + ".md")
    if cand.is_file():
        return cand
    raise RuntimeError("转换没有产出 Markdown")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s[:60]


def uniquify(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def unique_slug(base: str) -> str:
    books = dirs()["books"]
    if not (books / base).exists():
        return base
    n = 2
    while (books / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def _heads(lines: list[str], prefix: str) -> list[tuple[int, str]]:
    out = []
    bang = prefix + "#"
    for i, line in enumerate(lines):
        if line.startswith(prefix) and not line.startswith(bang):
            out.append((i, line[len(prefix) :].strip()))
    return out


def split_markdown(text: str, fallback_title: str) -> tuple[str, list[tuple[str, str]]]:
    lines = text.splitlines()
    h1 = _heads(lines, "# ")
    h2 = _heads(lines, "## ")
    title = h1[0][1] if h1 else fallback_title
    cuts = h1 if len(h1) >= 2 else h2 if h2 else []
    if not cuts:
        body = text if text.endswith("\n") else text + "\n"
        return title, [(title, body)]
    parts = []
    for n, (i, name) in enumerate(cuts):
        end = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
        body = "\n".join(lines[i:end]).strip() + "\n"
        parts.append((name, body))
    return title, parts


def first_intro(text: str, nchap: int) -> str:
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or re.match(r"\*\*[\w\s]+:\*\*", s):
            continue
        return s[:80]
    return f"由源文件转换，含 {nchap} 章。"


def render_guide(title: str, intro: str, chapters: list[str], source: str) -> str:
    meta = {
        "title": title,
        "type": "书",
        "intro": intro,
        "tags": [],
        "source": source,
    }
    toc = "\n".join(f"- {c}" for c in chapters)
    return (
        "---\n"
        + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + f"# {title}\n\n{intro}\n\n## 目录\n{toc}\n"
    )


def list_inbox() -> list[Path]:
    inbox = dirs()["inbox"]
    if not inbox.is_dir():
        return []
    return sorted(
        p
        for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() in SOURCE_EXTS
    )


def convert_one(src: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="kb-") as td:
        md_path = run_markitdown(src, Path(td))
        text = md_path.read_text(encoding="utf-8")
    title, parts = split_markdown(text, src.stem)
    base = slugify(src.stem) or slugify(title) or (
        "book-" + hashlib.sha1(src.stem.encode("utf-8")).hexdigest()[:8]
    )
    slug = unique_slug(base)
    book_dir = dirs()["books"] / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    if len(parts) == 1:
        (book_dir / "正文.md").write_text(parts[0][1], encoding="utf-8")
        names = [parts[0][0]]
    else:
        for i, (name, body) in enumerate(parts, 1):
            fn = f"{i:02d}-{slugify(name) or 'chapter'}.md"
            (book_dir / fn).write_text(body, encoding="utf-8")
            names.append(name)
    intro = first_intro(text, len(names))
    archive_dir = dirs()["archive"]
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_dest = uniquify(archive_dir / src.name)
    shutil.move(str(src), str(archive_dest))
    root = dirs()["root"]
    try:
        rel = archive_dest.resolve().relative_to(root).as_posix()
    except ValueError:
        rel = archive_dest.name
    (book_dir / "导读.md").write_text(
        render_guide(title, intro, names, rel), encoding="utf-8"
    )
    return {"slug": slug, "title": title, "archive": rel, "dir": book_dir.as_posix()}


def ingest_sources(files: list[Path], step_prefix: str) -> str:
    ok: list[dict] = []
    failed: list[tuple[Path, str, int]] = []
    for i, src in enumerate(files, 1):
        try:
            ok.append(convert_one(src))
        except Exception as e:
            failed.append((src, str(e), i))
    lines = []
    for item in ok:
        lines.append(f"- {item['title']} → 资料/书/{item['slug']}/导读.md ；源文件 {item['archive']}")
    if not failed:
        return f"入库完成\n成功 {len(ok)} 本\n" + "\n".join(lines) + "\n"
    why = "；".join(f"{p.name}：{err}" for p, err, _ in failed)
    step = f"{step_prefix}-转换第 {failed[0][2]} 个文件"
    nxt = "坏的源文件仍在原处，不要编书顶上；修好或换文件后再走这一门。"
    done = f"成功 {len(ok)} 本。" + (" " + "；".join(x["title"] for x in ok) if ok else "")
    return fail(step, why, done.strip(), nxt)


@guarded("kb_ingest_inbox")
def ingest_inbox() -> str:
    files = list_inbox()
    if not files:
        out = fail(
            "收件箱入库-扫描",
            "原始资料里没有待处理的 PDF/EPUB/MOBI。",
            "无",
            "把源文件丢进 原始资料/ 再调这一门。",
        )
        log_call("kb_ingest_inbox", False, step="扫描")
        return out
    out = ingest_sources(files, "收件箱入库")
    log_call("kb_ingest_inbox", not out.startswith("失败"), n=len(files))
    return out


def resolve_source(raw: str) -> Path | None:
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    inbox = dirs()["inbox"] / raw
    if inbox.is_file():
        return inbox.resolve()
    return None


@guarded("kb_ingest_files")
def ingest_named(paths: list[str]) -> str:
    if not paths:
        out = fail(
            "指定入库-找文件",
            "没有给出源文件路径。指定的是文件，不是书名。",
            "无",
            "交上 PDF/EPUB/MOBI 的路径或原始资料里的文件名。",
        )
        log_call("kb_ingest_files", False, step="找文件")
        return out
    resolved: list[Path] = []
    for raw in paths:
        p = resolve_source(raw)
        if p is None:
            out = fail(
                "指定入库-找文件",
                f"找不到源文件：{raw}。指定的是文件路径，不是书名。",
                "无",
                "自己先找到文件再调；找不到就去问人，不要编书。",
            )
            log_call("kb_ingest_files", False, step="找文件")
            return out
        if p.suffix.lower() not in SOURCE_EXTS:
            out = fail(
                "指定入库-找文件",
                f"{p.name} 不是 PDF/EPUB/MOBI。书只从源文件转换来。",
                "无",
                "交源文件路径。不要把自编 Markdown 当书写进 资料/书/。",
            )
            log_call("kb_ingest_files", False, step="找文件")
            return out
        resolved.append(p)
    out = ingest_sources(resolved, "指定入库")
    log_call("kb_ingest_files", not out.startswith("失败"), n=len(resolved))
    return out
