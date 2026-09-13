"""Search headers only; read named parts with a char cap."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
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
    tokens = _tokens(q)
    ranked: list[tuple[float, dict, list[str], list[str]]] = []
    for item in iter_headers():
        score, why, hits = _score(item, tokens)
        if score > 0:
            ranked.append((score, item, why, hits))
    ranked.sort(key=lambda r: r[0], reverse=True)
    top = ranked[:SEARCH_LIMIT]
    if not top:
        out = "路标：没有像的。抬头扫过了，没有贴近这个问法的。不要装查过。\n"
        log_call("kb_search", True, hits=0, query=q)
        return out
    lines = [f"路标（最多 {SEARCH_LIMIT} 条，无正文）"]
    for i, (_s, item, why, hits) in enumerate(top, 1):
        lines.append(f"{i}. [{item['kind']}] {item['title'] or item['ident']}  身份：{item['ident']}")
        lines.append(f"   像在：{'；'.join(why)}")
        if hits:
            lines.append(f"   建议块（最多 {CHAPTER_SUGGEST_LIMIT} 个）：")
            for c in hits:
                lines.append(f"   · {item['ident']}/{c}")
        elif item["kind"] == "书":
            lines.append(f"   没有命中章（可点 {item['ident']}/导读）")
    out = "\n".join(lines) + "\n"
    log_call("kb_search", True, hits=len(top), query=q)
    return out


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
    tail = chr(10) + chr(10) + '[' + '已截断：这一块最多 {n} 字，只给了开头。同一块再读还是这段开头，不能续页。要更多请换问法再检索，或点另一章。够答就停。'.format(n=CHAR_CAP) + ']' + chr(10)
    return text[:CHAR_CAP] + tail


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
    if part in ("导读", "导读.md"):
        p = book / "导读.md"
        if not p.is_file():
            return fail("阅读-点名", "这份书没有导读。", "无", "换一块或先入库。")
        return _cap(p.read_text(encoding="utf-8"))
    files = [p for p in sorted(book.glob("*.md")) if p.name != "导读.md"]
    for p in files:
        text = p.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        if part in p.name or part in p.stem or part in first:
            return _cap(text)
    return fail(
        "阅读-点名",
        f"在 {slug} 里找不到「{part}」这一块。",
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
    return _cap(p.read_text(encoding="utf-8"))


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
