"""Inbox + named ingest share one convert. Books only from source files."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.log import guarded, log_call
from knowledge_mcp.paths import dirs

SOURCE_EXTS = {".pdf", ".epub", ".mobi", ".azw", ".azw3"}
def _convert_candidates() -> list[Path]:
    """markitdown 转换脚本的位置。别硬编码某台机器的路径。"""
    home = Path.home()
    return [
        home / ".claude" / "skills" / "markitdown" / "scripts" / "convert.py",
        Path(__file__).resolve().parents[2] / ".markitdown" / "convert.py",
    ]


def convert_script() -> Path:
    """环境变量 KNOWLEDGE_MARKITDOWN 优先，其次常见位置。"""
    override = os.environ.get("KNOWLEDGE_MARKITDOWN")
    if override:
        return Path(override).expanduser()
    for cand in _convert_candidates():
        if cand.is_file():
            return cand
    return _convert_candidates()[0]


def run_markitdown(src: Path, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = convert_script()
    if not script.is_file():
        nl = chr(10)
        where = nl + "  " + (nl + "  ").join(str(x) for x in _convert_candidates())
        raise RuntimeError(
            "找不到 markitdown 转换脚本。用 KNOWLEDGE_MARKITDOWN 指向 convert.py，"
            "当前找过：" + where
        )
    r = subprocess.run(
        [sys.executable, str(script), str(src), "--output-dir", str(out_dir)],
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


JUNK_RE = re.compile(
    r"(?:https?://\S+|www\.\S+"
    r"|z-library\S*|1lib\S*|z-lib\S*|libgen\S*|annas-archive\S*"
    r"|\.(?:epub|mobi|azw3?|pdf|djvu|txt)"
    r"|\((?:[^()]*\.(?:sk|com|net|org|io|cn)[^()]*)\)"
    r"|\[[^\[\]]*(?:www\.|https?://)\S*[^\[\]]*\])",
    re.I,
)


def slug_base(name: str) -> str:
    """原始文件名 -> 干净的 slug 候选（去掉来源水印/网址/扩展名）。"""
    s = JUNK_RE.sub(" ", name.lower())
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", s)
    s = re.sub(r"\s*[=—–]+\s*", " ", s).strip(" ._-()[]{}")
    return slugify(s) or f"book-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"


def safe_filename(name: str, limit: int = 60) -> str:
    """标题 -> 能用、能看见的文件名。中文照留，只去文件系统不认的字符。"""
    s = str(name).replace("\\", " ")
    for ch in '/:*?"<>|':
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:limit].strip(" .")


def epub_title(src: Path) -> str | None:
    """EPUB 自带的 dc:title。取不到就算了，不猜。"""
    try:
        with zipfile.ZipFile(src) as z:
            for name in [n for n in z.namelist() if n.lower().endswith(".opf")]:
                text = z.read(name).decode("utf-8", "replace")
                m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", text, re.S | re.I)
                if m:
                    title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                    if title:
                        return title
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return None


BOILERPLATE_RE = re.compile(
    r"^\s*(版权|copyright|扉页|书名页|题名页|colophon|title\s*page|copyright\s*page)",
    re.I,
)


def looks_boilerplate(heading: str) -> bool:
    return bool(BOILERPLATE_RE.match(heading.strip()))


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


ATX_RE = re.compile(r"^(#{1,6}) (.+)$")
STRUCT_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千零〇两]+[章节篇回]"
    r"|[一二三四五六七八九十]+、"
    r"|（[一二三四五六七八九十]+）"
    r"|壹、)"
)
HEADING_JUNK_RE = re.compile(r"\[\\?\*\]\(#id[^)]*\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def clean_heading(name: str) -> str:
    """剥 epub 残渣，只用于命名和切点。"""
    s = str(name)
    s = HEADING_JUNK_RE.sub("", s)
    s = MD_LINK_RE.sub(r"\1", s)
    s = re.sub(r"</?a\b[^>]*>", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def is_structure_line(line: str) -> bool:
    """无 ATX 时才当切点：第一章 / 一、 / （一）。"""
    s = line.strip()
    if not s or len(s) > 40:
        return False
    if s[-1] in "。！？：；":
        return False
    return bool(STRUCT_RE.match(s))


def _atx_heads(lines: list[str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = ATX_RE.match(line)
        if m:
            found.append((i, len(m.group(1)), clean_heading(m.group(2))))
    return found


def _leaf_cuts(heads: list[tuple[int, int, str]]) -> list[tuple[int, str]]:
    cuts: list[tuple[int, str]] = []
    for n, (i, lvl, name) in enumerate(heads):
        nxt = heads[n + 1][1] if n + 1 < len(heads) else None
        if nxt is None or nxt <= lvl:
            cuts.append((i, name or f"第{n + 1}段"))
    return cuts


def _heads(lines: list[str], prefix: str) -> list[tuple[int, str]]:
    out = []
    bang = prefix + "#"
    for i, line in enumerate(lines):
        if line.startswith(prefix) and not line.startswith(bang):
            out.append((i, clean_heading(line[len(prefix) :])))
    return out


def _ordered_heads(lines: list[str]) -> list[tuple[int, str]]:
    """所有一级/二级标题，按在原文里出现的先后排。"""
    found = [(i, name) for i, name in _heads(lines, "# ")]
    found += [(i, name) for i, name in _heads(lines, "## ")]
    return sorted(found)


def pick_title(candidates: list[str], fallback: str, meta_title: str | None) -> str:
    """书名来源：书的元数据 > 书里的一级标题 > 原始文件名。

    抬头只能来自书本身，不许编；版权/扉页这类不算书名。
    """
    if meta_title and meta_title.strip():
        return meta_title.strip()
    for c in candidates:
        if c.strip() and not looks_boilerplate(c):
            return c.strip()
    return fallback


def split_markdown(
    text: str, fallback_title: str, *, meta_title: str | None = None
) -> tuple[str, list[str], list[tuple[str, str]]]:
    """切书成自然篇/章，同时给出标题候选。

    有 ATX 标题：切在叶子标题（有子标题就下沉；卷名并进其后第一篇）。
    没有 ATX：才把「第一章 / 一、」当切点。
    第一个切点之前的字并进第一块。不按字数再切文件。
    """
    lines = text.splitlines()
    atx = _atx_heads(lines)
    h1 = [(i, name) for i, lvl, name in atx if lvl == 1]
    h2 = [(i, name) for i, lvl, name in atx if lvl == 2]
    if atx:
        cuts = _leaf_cuts(atx)
    else:
        cuts = [
            (i, clean_heading(line.strip()))
            for i, line in enumerate(lines)
            if is_structure_line(line)
        ]
    candidates = (
        [name for _, name in h1]
        or [name for _, name in h2]
        or [name for _, name in cuts]
        or [fallback_title]
    )
    title = pick_title(candidates, fallback_title, meta_title)
    parts: list[tuple[str, str]] = []
    if not cuts:
        name = h1[0][1] if h1 else fallback_title
        body = text if text.endswith("\n") else text + "\n"
        parts.append((clean_heading(name) or fallback_title, body))
    else:
        for n, (i, name) in enumerate(cuts):
            start = 0 if n == 0 else i
            end = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
            body = "\n".join(lines[start:end]).strip() + "\n"
            parts.append((name or fallback_title, body))
    return title, candidates, parts


META_KEYS = (
    "title", "标题", "author", "作者", "language", "语言", "date", "日期",
    "publisher", "出版", "isbn", "rights", "版权", "subject", "主题",
    "identifier", "来源", "source",
)
META_LINE_RE = re.compile(r"^\*\*([^*]{1,20}):\*\*\s*(.*)$")


def _plain(line: str) -> str:
    """去掉行内标记与 `**Title:**` 这类字段名，只留可比的正文。"""
    s = line.strip()
    m = META_LINE_RE.match(s)
    if m:
        s = m.group(2)
    s = re.sub(r"[*#`_\[\]]+", " ", s).strip()
    s = re.sub(r"^([A-Za-z一-鿿]{1,20})\s*[:：]\s*", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _is_metadata_field(line: str) -> bool:
    """`**Language:** zh` 这种「字段名 + 短值」是元数据，不是介绍。"""
    s = line.strip()
    m = META_LINE_RE.match(s)
    if m:
        key, val = m.group(1).strip().lower(), m.group(2).strip()
    else:
        m2 = re.match(r"^([A-Za-z一-鿿]{1,20})\s*[:：]\s*(.*)$", s)
        if not m2:
            return False
        key, val = m2.group(1).strip().lower(), m2.group(2).strip()
    if not val or len(val.split()) > 3:
        return False
    if key in META_KEYS:
        return True
    return len(key) <= 12


def first_intro(parts: list[tuple[str, str]], nchap: int, title: str | None = None) -> str:
    """取几句介绍：切好的块里，第一块「除了标题还有正文」的那句。

    跳过：版权/扉页整块、标题行、块标题本身、书名的各种写法
    （裸书名，或 markitdown 那种 `**Title:** 书名`）。
    """
    wanted = _plain(title) if title else ""
    for name, body in parts:
        if looks_boilerplate(name):
            continue
        part_head = _plain(name)
        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _is_metadata_field(s):
                continue
            plain = _plain(s)
            if not plain or plain == part_head or (wanted and plain == wanted):
                continue
            return s[:80]
    return f"由源文件转换，含 {nchap} 块。"


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
    title, _candidates, parts = split_markdown(
        text, src.stem, meta_title=epub_title(src)
    )
    slug = unique_slug(slug_base(src.stem))
    book_dir = dirs()["books"] / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    if len(parts) == 1:
        (book_dir / "正文.md").write_text(parts[0][1], encoding="utf-8")
        names = [parts[0][0]]
    else:
        for i, (name, body) in enumerate(parts, 1):
            fn = f"{i:02d}-{safe_filename(name) or f'第{i}章'}.md"
            (book_dir / fn).write_text(body, encoding="utf-8")
            names.append(name)
    intro = first_intro(parts, len(names), title)
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
