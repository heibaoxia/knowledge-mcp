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
from knowledge_mcp.index import MAP_FILE, fill_chapter_names, invalidate, map_problems
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


WINDOW = 8000
LONG_BLOCK = 8 * WINDOW
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
IMG_LINE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HOLLOW_SLUG_RE = re.compile(r"^[0-9]+(?:-[0-9]+)*$")
CHAPTER_TITLE_RE = re.compile(r"^第[0-9一二三四五六七八九十百千零〇两]+章")
SLUG_OK_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def _img_lines(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if IMG_LINE_RE.search(ln))


def is_no_text_layer(text: str) -> bool:
    cjk = _cjk_count(text)
    imgs = _img_lines(text)
    if imgs >= 20 and cjk < imgs * 8:
        return True
    if cjk < 200 and imgs >= 5:
        return True
    return False


def _short_block_name(stem: str) -> str:
    m = re.match(r"^\d+-", stem)
    name = stem[m.end() :] if m else stem
    return re.sub(r"-\d+$", "", name)


def book_health(book_dir: Path) -> list[str]:
    """机械未入完。不含缺地图（那是 map_problems）。"""
    book_dir = Path(book_dir)
    flags: list[str] = []
    if HOLLOW_SLUG_RE.match(book_dir.name):
        flags.append("空心目录名")
    bodies: list[str] = []
    shorts: list[str] = []
    rare_names = 0
    long_hit = False
    for p in book_dir.glob("*.md"):
        if p.name in ("导读.md", MAP_FILE):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        bodies.append(text)
        if len(text) > LONG_BLOCK:
            long_hit = True
        shorts.append(_short_block_name(p.stem))
        if "\ufffd" in p.name:
            rare_names += 2
        else:
            rare_names += sum(
                1
                for ch in p.name
                if (0x3400 <= ord(ch) <= 0x4DBF) or ord(ch) >= 0x20000
            )
    if long_hit:
        flags.append("超长块")
    counts: dict[str, int] = {}
    for n in shorts:
        counts[n] = counts.get(n, 0) + 1
    if any(c >= 3 for c in counts.values()):
        flags.append("同名章撞车")
    if rare_names >= 2:
        flags.append("文件名乱码")
    if is_no_text_layer("\n".join(bodies)):
        flags.append("无文字层")
    return flags


def withdraw_book(slug: str) -> dict:
    """只删 资料/书/<slug>/。不存在则 raise ValueError。"""
    slug = (slug or "").strip().strip("/")
    if not slug or not SLUG_OK_RE.fullmatch(slug):
        raise ValueError("退书只许 书/<slug>")
    book = dirs()["books"] / slug
    if not book.is_dir():
        raise ValueError(f"没有这本书：{slug}")
    title, source = slug, ""
    guide = book / "导读.md"
    if guide.is_file():
        raw = guide.read_text(encoding="utf-8")
        if raw.startswith("---"):
            bits = raw.split("---", 2)
            if len(bits) >= 3:
                meta = yaml.safe_load(bits[1]) or {}
                if isinstance(meta, dict):
                    title = str(meta.get("title") or slug)
                    source = str(meta.get("source") or "")
    shutil.rmtree(book)
    invalidate()
    return {"slug": slug, "title": title, "source": source}


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
    s = slugify(s)
    if not s or HOLLOW_SLUG_RE.match(s):
        return f"book-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"
    return s


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
NUM_CN = r"[0-9一二三四五六七八九十百千零〇两]+"
STRUCT_RE = re.compile(
    rf"^(第{NUM_CN}[章节篇]"
    r"|[一二三四五六七八九十]+、"
    r"|（[一二三四五六七八九十]+）"
    r"|壹、)"
)
HEADING_JUNK_RE = re.compile(r"\[\\?\*\]\(#id[^)]*\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
VOLUME_RE = re.compile(rf"第{NUM_CN}卷")
VOL_LABEL_RE = re.compile(rf"第{NUM_CN}[卷册]")
CHAPTER_HEAD_RE = re.compile(rf"^第{NUM_CN}[章节篇]")
YI_HEAD_RE = re.compile(r"^([一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|壹、)(.*)$")


def clean_heading(name: str) -> str:
    """剥 epub 残渣，只用于命名和切点。"""
    s = str(name)
    s = HEADING_JUNK_RE.sub("", s)
    s = MD_LINK_RE.sub(r"\1", s)
    s = re.sub(r"</?a\b[^>]*>", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _plain_line(line: str) -> str:
    return clean_heading(line.strip())


def _short_uncut(s: str) -> bool:
    return bool(s) and len(s) <= 40 and s[-1] not in "。！？：；"


def is_toc_link_line(line: str) -> bool:
    """目录里的 [章名](part.html)，不当切点、不当卷行。"""
    s = line.strip()
    if s.startswith(">"):
        s = s[1:].strip()
    return s.startswith("[") and "](" in s


def volume_label(line: str) -> str | None:
    """短标题行里的第X卷/册。脚注『版第2卷』『第8卷和第13卷』不算。"""
    if is_toc_link_line(line):
        return None
    s = _plain_line(line)
    if not s or len(s) > 30 or CHAPTER_HEAD_RE.match(s) or "页" in s:
        return None
    if any(ch in s for ch in "，。；") or "——" in s or "—" in s:
        return None
    m = re.match(rf"^(第{NUM_CN}[卷册])(?:\s*\S.*)?$", s)
    if m:
        return m.group(1)
    m = re.search(rf"（(第{NUM_CN}[卷册])）", s)
    if m and len(s) <= 24:
        return m.group(1)
    if re.match(r"^[上下]册(?:\s|$)", s):
        return s[:2]
    return None


def is_volume_line(line: str) -> bool:
    return volume_label(line) is not None


def is_yi_clause(s: str) -> bool:
    """一、后面是条款句子，不是短标题。"""
    m = YI_HEAD_RE.match(s)
    if not m:
        return False
    rest = (m.group(2) or "").strip()
    if len(rest) > 16:
        return True
    if any(ch in rest for ch in "，。；"):
        return True
    return False


def is_structure_line(line: str) -> bool:
    """无 ATX 时才当切点：第一章 / 短「一、标题」。册/卷、条款、目录链接不当切点。"""
    if is_toc_link_line(line):
        return False
    s = _plain_line(line)
    if not _short_uncut(s):
        return False
    if is_volume_line(line):
        return False
    if is_yi_clause(s):
        return False
    return bool(STRUCT_RE.match(s))


def _atx_heads(lines: list[str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = ATX_RE.match(line)
        if m:
            found.append((i, len(m.group(1)), clean_heading(m.group(2))))
    return found


def _cut_level(atx: list[tuple[int, int, str]]) -> int:
    """篇/章这一层：毛选落到 h3，多 h1 的扁平书停在 h1，单书名+章停在 h2。"""
    lvls = [l for _, l, _ in atx if l <= 3]
    if not lvls:
        return max((l for _, l, _ in atx), default=1)
    n1, n2, n3 = lvls.count(1), lvls.count(2), lvls.count(3)
    vol = any(VOLUME_RE.search(n) for _, l, n in atx if l == 1)
    if n3 and (vol or n1 <= 1):
        if n2 >= 4 and not vol:
            return 2
        return 3
    if n2 and n1 <= 1:
        return 2
    if n1:
        return 1
    if n2:
        return 2
    return 3


def _natural_cuts(atx: list[tuple[int, int, str]], L: int) -> list[tuple[int, str]]:
    cuts: list[tuple[int, str]] = []
    for n, (i, lvl, name) in enumerate(atx):
        if lvl > L:
            continue
        if lvl == L:
            cuts.append((i, name))
            continue
        has_L = False
        for _, nl, _ in atx[n + 1 :]:
            if nl <= lvl:
                break
            if nl == L:
                has_L = True
                break
        if not has_L:
            cuts.append((i, name))
    return cuts


def _part_starts(
    lines: list[str],
    cuts: list[tuple[int, str]],
    atx: list[tuple[int, int, str]],
    L: int,
) -> list[int]:
    """第一块从文首；卷/时期等上级标题并进其后第一块。"""
    atx_lvl = {i: lvl for i, lvl, _ in atx}
    starts: list[int] = []
    for n, (i, _) in enumerate(cuts):
        if n == 0:
            starts.append(0)
            continue
        prev_i = cuts[n - 1][0]
        start = i
        j = i - 1
        while j > prev_i:
            if not lines[j].strip():
                j -= 1
                continue
            lvl = atx_lvl.get(j)
            if lvl is not None and lvl < L:
                start = j
                j -= 1
                continue
            break
        starts.append(start)
    return starts


def _uniq_name(name: str, seen: set[str]) -> str:
    base = name or "正文"
    if base not in seen:
        seen.add(base)
        return base
    k = 2
    while f"{base}-{k}" in seen:
        k += 1
    out = f"{base}-{k}"
    seen.add(out)
    return out


def _name_from_body(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        m = ATX_RE.match(s)
        if m:
            s = clean_heading(m.group(2))
        else:
            s = clean_heading(s)
        if s:
            return s[:20]
    return "正文"


def pick_title(candidates: list[str], fallback: str, meta_title: str | None) -> str:
    """书名来源：书的元数据 > 书里的一级标题 > 原始文件名。

    抬头只能来自书本身，不许编；版权/扉页这类不算书名。
    """
    if meta_title and meta_title.strip():
        return meta_title.strip()
    for c in candidates:
        s = c.strip()
        if not s or looks_boilerplate(s):
            continue
        rest = re.sub(rf"^第{NUM_CN}[卷册]\s*", "", s)
        if CHAPTER_TITLE_RE.match(rest) or re.match(rf"^第{NUM_CN}[节篇]", rest):
            continue
        return s
    return fallback


def split_markdown(
    text: str, fallback_title: str, *, meta_title: str | None = None
) -> tuple[str, list[str], list[tuple[str, str]]]:
    """切书成自然篇/章，同时给出标题候选。

    有 ATX 标题：切在篇/章这一层（毛选落到 h3，不撕 h4 节；卷/时期并进其后第一篇）。
    没有 ATX：才把「第一章 / 一、」当切点。
    第一个切点之前的字并进第一块。不按字数再切文件。
    """
    lines = text.splitlines()
    atx = _atx_heads(lines)
    h1 = [(i, name) for i, lvl, name in atx if lvl == 1]
    h2 = [(i, name) for i, lvl, name in atx if lvl == 2]
    if atx:
        L = _cut_level(atx)
        cuts = _natural_cuts(atx, L)
        starts = _part_starts(lines, cuts, atx, L)
    else:
        cuts = []
        vol = ""
        for i, line in enumerate(lines):
            lab = volume_label(line)
            if lab:
                vol = lab
                continue
            if is_structure_line(line):
                name = _plain_line(line)
                if vol and vol not in name:
                    name = f"{vol} {name}"
                cuts.append((i, name))
        starts = []
        for n, (i, _) in enumerate(cuts):
            if n == 0:
                starts.append(0)
                continue
            start, j, prev = i, i - 1, cuts[n - 1][0]
            while j > prev:
                if not lines[j].strip():
                    j -= 1
                    continue
                if is_volume_line(lines[j]):
                    start = j
                    j -= 1
                    continue
                break
            starts.append(start)
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
        seen: set[str] = set()
        for n, (_i, name) in enumerate(cuts):
            start = starts[n]
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            body = "\n".join(lines[start:end]).strip() + "\n"
            parts.append((_uniq_name(name or _name_from_body(body), seen), body))
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
    if is_no_text_layer(text):
        raise RuntimeError(
            "转换产物几乎没有可检索的正文（无文字层）。本工具不 OCR。换文字版再入，或不要这本。"
        )
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
        width = max(2, len(str(len(parts))))
        for i, (name, body) in enumerate(parts, 1):
            fn = f"{i:0{width}d}-{safe_filename(name) or f'第{i}章'}.md"
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
    fill_chapter_names(book_dir)
    invalidate()
    return {
        "slug": slug,
        "title": title,
        "archive": rel,
        "dir": book_dir.as_posix(),
        "map_target": f"书/{slug}/地图",
        "blocks": names,
        "map_ok": not map_problems(book_dir),
        "health": book_health(book_dir),
    }


WORK_ORDER_SHOWN = 30


def _map_work_order(item: dict) -> str:
    """缺地图时交还给 Agent 的「编地图」工作单：写哪、什么格式、走哪扇门。代码不代编内容。"""
    slug = item["slug"]
    blocks = list(item.get("blocks") or [])
    out = [
        f"编地图 书/{slug}/地图（{item['title']}）——不算入完，按下面补：",
        f"· 写哪：资料/书/{slug}/地图.md（没有就新建）",
        "· 走哪扇门：kb_lint_notes(action=apply, plan=…)，plan 里放一条 "
        f'{{"op":"update","target":"书/{slug}/地图","markdown":"<整份地图>"}}'
        "。地图不存在也能这样新建；校验不过会回滚。",
        "· frontmatter：title 与 导读.md 的 title 一字不差；type: 地图；"
        f"book: 书/{slug}；generated: true",
        "· 必填段：能解决什么 3–8 条（每条 ≤40 字）；不解决什么 1–5 条；"
        "建议从哪读（身份）；依据块（条数 ≥ 能解决什么）；章名（已机械补上，别删）；"
        f"别名一行一条 <专名 ≥2 字> → 书/{slug}/<已存在的块名>",
    ]
    if blocks:
        shown = blocks[:WORK_ORDER_SHOWN]
        more = len(blocks) - len(shown)
        out.append(
            f"· 块名（共 {len(blocks)}）：" + "、".join(shown)
            + (f"；还有 {more} 个，看 资料/书/{slug}/ 目录" if more else "")
        )
    out.append("· 别名与「能解决什么」由你编——工具只给清单和校验，不代写。")
    return "\n".join(out)


def ingest_sources(files: list[Path], step_prefix: str) -> str:
    ok: list[dict] = []
    failed: list[tuple[Path, str, int]] = []
    for i, src in enumerate(files, 1):
        try:
            ok.append(convert_one(src))
        except Exception as e:
            failed.append((src, str(e), i))
    lines = []
    missing = 0
    unfinished: list[str] = []
    for item in ok:
        lines.append(f"- {item['title']} → 资料/书/{item['slug']}/导读.md ；源文件 {item['archive']}")
        reasons: list[str] = []
        if not item.get("map_ok"):
            missing += 1
            reasons.append("缺地图")
        for r in item.get("health") or []:
            if r not in reasons:
                reasons.append(r)
        if reasons:
            unfinished.append(f"未入完 书/{item['slug']}：{'；'.join(reasons)}")
    if not failed:
        out = f"入库完成\n成功 {len(ok)} 本\n" + "\n".join(lines) + "\n"
        if missing:
            out += f"\n缺地图 {missing} 本（源文件已归档，不算入完）：\n"
            for item in ok:
                if not item.get("map_ok"):
                    out += _map_work_order(item) + "\n"
        if unfinished:
            out += "\n".join(unfinished) + "\n"
        return out
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
