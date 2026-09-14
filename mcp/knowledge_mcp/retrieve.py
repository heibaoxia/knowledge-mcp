"""Search headers only; read named parts with a char cap."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.index import _block_name, search_index
from knowledge_mcp.log import guarded, log_call
from knowledge_mcp.paths import dirs

SEARCH_LIMIT = 5
CHAR_CAP = 8000
BATCH_LIMIT = 5
TOTAL_CHAR_CAP = 24000
CHAPTER_SUGGEST_LIMIT = 3
UNREAD_HEAD = "\n未读（整次字数顶或超过 5 块，正文没给）：\n"
PUNCT = r"\s,，.。;；:：!！?？、·—()（）\[\]【】"
HAN = re.compile(r"[一-鿿]+")
WEIGHTS = {"title": 4.0, "tags": 3.5, "intro": 2.5, "chapters": 2.0}


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, parts[2].lstrip("\n")


def _tokens(query: str) -> list[str]:
    """Whole sentence + pieces split on space/punctuation + two-char slices of han runs."""
    q = query.strip()
    out: list[str] = []
    for t in [q, *re.split(f"[{PUNCT}]+", q)]:
        if t and t not in out:
            out.append(t)
    for run in HAN.findall(q):
        for i in range(len(run) - 1):
            gram = run[i : i + 2]
            if gram not in out:
                out.append(gram)
    return out


def _load_header(path: Path, kind: str, ident: str) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, rest = split_frontmatter(text)
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    chapters = []
    if kind == "书":
        chapters = [ln[1:].strip() for ln in rest.splitlines() if ln.startswith("- ")]
    return {
        "ident": ident,
        "kind": kind,
        "title": str(meta.get("title") or ""),
        "intro": str(meta.get("intro") or meta.get("description") or ""),
        "tags": [str(t) for t in tags],
        "chapters": chapters,
        "path": path,
    }


def iter_headers() -> list[dict]:
    rows: list[dict] = []
    books = dirs()["books"]
    if books.is_dir():
        for guide in sorted(books.glob("*/导读.md")):
            rows.append(_load_header(guide, "书", f"书/{guide.parent.name}"))
    notes = dirs()["notes"]
    if notes.is_dir():
        for p in sorted(notes.glob("*.md")):
            rows.append(_load_header(p, "笔记", f"笔记/{p.stem}"))
    return rows


def _score(item: dict, tokens: list[str]) -> tuple[float, list[str], list[str]]:
    why: list[str] = []
    hits: list[str] = []
    total = 0.0
    fields = {
        "title": item["title"],
        "tags": " ".join(item["tags"]),
        "intro": item["intro"],
        "chapters": " ".join(item["chapters"]),
    }
    labels = {"title": "标题", "tags": "标签", "intro": "介绍", "chapters": "章节名"}
    for key, text in fields.items():
        blob = text.lower()
        hit = [t for t in tokens if t.lower() in blob]
        if hit:
            total += WEIGHTS[key] * len(hit)
            why.append(f"{labels[key]}含「{'、'.join(hit)}」")
        if key == "chapters":
            hits = [c for c in item["chapters"] if any(t.lower() in c.lower() for t in tokens)]
    return total, why, hits[:CHAPTER_SUGGEST_LIMIT]


@guarded("kb_search")
def search(query: str) -> str:
    q = (query or "").strip()
    if not q:
        out = fail("检索", "没有问什么。", "无", "用一句话说想了解什么。")
        log_call("kb_search", False, step="输入")
        return out
    try:
        hits = search_index(q)
    except Exception:
        out = _header_search(q)
        log_call("kb_search", True, hits=0, query=q, degraded=1)
        return out
    if not hits:
        out = "路标：没有像的。索引扫过了，没有贴近这个问法的。不要装查过。\n"
        log_call("kb_search", True, hits=0, query=q)
        return out
    groups: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for h in hits:
        key = (str(h["kind"]), str(h["book_id"]))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(h)
    lines = [f"路标（最多 {SEARCH_LIMIT} 条，无正文）"]
    shown = 0
    for kind, bid in order:
        shown += 1
        if shown > SEARCH_LIMIT:
            break
        items = groups[(kind, bid)]
        if kind == "书":
            ident = f"书/{bid}"
            title = _book_title(bid)
        else:
            ident = f"笔记/{bid}"
            title = items[0].get("title") or items[0].get("name") or bid
        lines.append(f"{shown}. [{kind}] {title}  身份：{ident}")
        why = [
            p
            for p in (items[0].get("why") or [])
            if p and p not in ident and len(p) <= 20
        ]
        if why:
            lines.append(f"   像在：含「{'、'.join(str(x) for x in why[:4])}」")
        else:
            lines.append("   像在：正文")
        lines.append(f"   命中 {len(items)} 块")
        lines.append(f"   建议块（最多 {CHAPTER_SUGGEST_LIMIT} 个）：")
        for it in items[:CHAPTER_SUGGEST_LIMIT]:
            lines.append(f"   · {it['ident']}")
    out = "\n".join(lines) + "\n"
    log_call("kb_search", True, hits=min(shown, SEARCH_LIMIT), query=q)
    return out


def _header_search(q: str) -> str:
    tokens = _tokens(q)
    ranked: list[tuple[float, dict, list[str], list[str]]] = []
    for item in iter_headers():
        score, why, hits = _score(item, tokens)
        if score > 0:
            ranked.append((score, item, why, hits))
    ranked.sort(key=lambda r: r[0], reverse=True)
    top = ranked[:SEARCH_LIMIT]
    if not top:
        return "路标：没有像的。抬头扫过了，没有贴近这个问法的。不要装查过。\n"
    lines = [f"路标（最多 {SEARCH_LIMIT} 条，无正文；索引不可用，已退化成抬头）"]
    for i, (_s, item, why, hits) in enumerate(top, 1):
        lines.append(f"{i}. [{item['kind']}] {item['title'] or item['ident']}  身份：{item['ident']}")
        lines.append(f"   像在：{'；'.join(why)}")
        if hits:
            lines.append(f"   建议块（最多 {CHAPTER_SUGGEST_LIMIT} 个）：")
            for c in hits:
                lines.append(f"   · {item['ident']}/{c}")
        elif item["kind"] == "书":
            lines.append(f"   没有命中章（可点 {item['ident']}/导读）")
    return "\n".join(lines) + "\n"


def _book_title(slug: str) -> str:
    p = dirs()["books"] / slug / "导读.md"
    if not p.is_file():
        return slug
    try:
        meta, _ = split_frontmatter(p.read_text(encoding="utf-8"))
        return str(meta.get("title") or slug)
    except OSError:
        return slug


def _parse_target(target: str) -> tuple[str | None, str | None, str | None]:
    t = target.replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    if t.startswith("书/"):
        bits = t[2:].split("/")
        return "书", bits[0], "/".join(bits[1:]) or None
    if t.startswith("笔记/"):
        rest = t[3:]
        return "笔记", Path(rest).stem, None
    return None, None, None


def _cap(text: str) -> str:
    if len(text) <= CHAR_CAP:
        return text
    return text[:CHAR_CAP]


def _split_part(part: str) -> tuple[str, int]:
    m = re.match(r"^(.*)#(\d+)$", part or "")
    if m:
        return m.group(1), max(1, int(m.group(2)))
    return part or "", 1


def _win_ident(slug: str, name: str, win: int) -> str:
    if win <= 1:
        return f"书/{slug}/{name}"
    return f"书/{slug}/{name}#{win}"


def _neighbors(files: list[Path], idx: int, slug: str, name: str, win: int, nwin: int) -> str:
    bits: list[str] = []
    if win > 1:
        bits.append(f"上一窗 {_win_ident(slug, name, win - 1)}")
    if win < nwin:
        bits.append(f"下一窗 {_win_ident(slug, name, win + 1)}")
    if idx > 0:
        bits.append(f"上一块 书/{slug}/{_block_name(files[idx - 1])}")
    if idx + 1 < len(files):
        bits.append(f"下一块 书/{slug}/{_block_name(files[idx + 1])}")
    if not bits:
        return ""
    return "邻块：" + " ｜ ".join(bits) + "\n"


def _read_book(slug: str, part: str | None) -> str:
    book = dirs()["books"] / slug
    if not book.is_dir():
        return fail(
            "阅读-点名",
            f"没有这份书：{slug}。",
            "无",
            "先检索拿路标上的身份，再点名导读或某一章。",
        )
    if not part:
        return fail(
            "阅读-点名",
            "书必须点名某一块（导读或某一章）。一次不能拿走整本。",
            "无",
            "例如 part=导读 或 part=第一章。",
        )
    name, win = _split_part(part)
    if name in ("导读", "导读.md"):
        p = book / "导读.md"
        if not p.is_file():
            return fail("阅读-点名", "这份书没有导读。", "无", "换一块或先入库。")
        text = p.read_text(encoding="utf-8")
        nwin = max(1, (len(text) + CHAR_CAP - 1) // CHAR_CAP)
        chunk = _cap(text[(win - 1) * CHAR_CAP : win * CHAR_CAP])
        nb = _neighbors([], 0, slug, "导读", win, nwin)
        return chunk + (("\n" + nb) if nb else "")
    files = [p for p in sorted(book.glob("*.md")) if p.name != "导读.md"]
    for i, p in enumerate(files):
        text = p.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        bname = _block_name(p)
        if name in p.name or name in p.stem or name in first or name == bname:
            nwin = max(1, (len(text) + CHAR_CAP - 1) // CHAR_CAP)
            if win > nwin:
                win = nwin
            chunk = _cap(text[(win - 1) * CHAR_CAP : win * CHAR_CAP])
            nb = _neighbors(files, i, slug, bname, win, nwin)
            return chunk + (("\n" + nb) if nb else "")
    return fail(
        "阅读-点名",
        f"在 {slug} 里找不到「{name}」这一块。",
        "无",
        "对照路标或导读里的章节名再点一次。",
    )


def _looks_whole_book(target: str) -> bool:
    kind, slug, part = _parse_target(target)
    return kind == "书" and bool(slug) and not part


def _ident_of(target: str, part: str | None) -> str:
    """Canonical identity for the call log: 书/<slug>/<章> or 笔记/<slug>; "" if unusable."""
    kind, slug, extra = _parse_target(target)
    if kind == "书":
        use_part = part or extra
        if not use_part or use_part in ("导读", "导读.md"):
            use_part = "导读"
        return f"书/{slug}/{use_part}"
    if kind == "笔记":
        return f"笔记/{slug}"
    return ""


def _read_note(slug: str) -> str:
    p = dirs()["notes"] / f"{slug}.md"
    if not p.is_file():
        return fail(
            "阅读-点名",
            f"没有这条笔记：{slug}。",
            "无",
            "先检索拿身份，再点名 笔记/<slug>。",
        )
    text = p.read_text(encoding="utf-8")
    nwin = max(1, (len(text) + CHAR_CAP - 1) // CHAR_CAP)
    chunk = _cap(text[:CHAR_CAP])
    extra = ""
    if nwin > 1:
        extra = f"\n邻块：下一窗 笔记/{slug}#2\n"
    return chunk + extra


def _why_of(out: str) -> str:
    for line in out.splitlines():
        if line.startswith("为什么："):
            return line[len("为什么：") :]
    return ""


def _read_one(ident: str) -> tuple[str, bool]:
    """Read one identity without logging. Returns (text, ok)."""
    kind, slug, extra = _parse_target(ident)
    if not kind or not slug:
        why = f"身份无法识别：{ident}。要 书/<slug>/<章> 或 笔记/<slug>。"
        return fail("阅读-点名", why, "无", "先检索，用路标上的身份。不要说「把心理学全给我」。"), False
    if kind == "书":
        out = _read_book(slug, extra)
    else:
        out = _read_note(slug)
    return out, not out.startswith("失败")


def _read_many(targets: list[str]) -> str:
    asked = len(targets)
    if not asked or any(not (t or "").strip() for t in targets):
        out = fail(
            "阅读-点名",
            "没有身份：清单是空的，或里面有没有身份的空项。",
            "无",
            "每个身份都要写明 书/<slug>/<章> 或 笔记/<slug>。",
        )
        log_call("kb_read", False, step="点名", asked=asked)
        return out
    if any(_looks_whole_book(t) for t in targets):
        out = fail(
            "阅读-点名",
            "清单里出现一次要整本（只有 书/<slug>，没点名章或导读）。一次不能拿走整本。",
            "无",
            "每条都要点名：书/<slug>/<章>、书/<slug>/导读 或 笔记/<slug>。",
        )
        log_call("kb_read", False, step="点名", asked=asked)
        return out
    sections: list[str] = []
    unread: list[str] = []
    total = 0
    for i, t in enumerate(targets):
        ident = _ident_of(t, None) or t
        if i >= BATCH_LIMIT:
            unread.append(ident)
            log_call("kb_read", False, target=ident, why="超过单次最多 5 块，未读")
            continue
        out, ok = _read_one(t)
        if ok and total + len(out) > TOTAL_CHAR_CAP:
            unread.append(ident)
            log_call("kb_read", False, target=ident, why="超过整次字数顶，未读")
            continue
        sections.append(f"# {ident}\n{out}")
        if ok:
            total += len(out)
        log_call("kb_read", ok, target=ident, why="" if ok else _why_of(out))
    result = "\n".join(sections)
    if unread:
        result += UNREAD_HEAD + "\n".join(f"- {u}" for u in unread) + "\n"
    return result


@guarded("kb_read")
def read(target: str = "", part: str | None = None, targets: list[str] | None = None) -> str:
    if targets is not None:
        return _read_many(targets)
    named = (target or "").strip()
    if not named:
        out = fail(
            "阅读-点名",
            "没有身份。",
            "无",
            "先检索，拿路标上的身份再点名某一块。",
        )
        log_call("kb_read", False, step="点名")
        return out
    kind, slug, extra = _parse_target(named)
    if not kind or not slug:
        out = fail(
            "阅读-点名",
            f"身份无法识别：{named}。要 书/<slug>/<章> 或 笔记/<slug>。",
            "无",
            "先检索，用路标上的身份。不要说「把心理学全给我」。",
        )
        log_call("kb_read", False, step="点名")
        return out
    use_part = part or extra
    if kind == "书":
        out = _read_book(slug, use_part)
    else:
        out = _read_note(slug)
    if out.startswith("失败"):
        log_call("kb_read", False, target=named, part=use_part or "", why=_why_of(out))
    else:
        log_call("kb_read", True, target=_ident_of(named, use_part))
    return out
