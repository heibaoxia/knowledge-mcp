"""Search headers only; read one named part with a char cap."""
from __future__ import annotations

from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.log import guarded, log_call
from knowledge_mcp.paths import dirs

SEARCH_LIMIT = 5
CHAR_CAP = 8000
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
    q = query.strip()
    out: list[str] = []
    for t in [q, *q.split()]:
        if t and t not in out:
            out.append(t)
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


def _score(item: dict, tokens: list[str]) -> tuple[float, list[str]]:
    why: list[str] = []
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
    return total, why


@guarded("kb_search")
def search(query: str) -> str:
    q = (query or "").strip()
    if not q:
        out = fail("检索", "没有问什么。", "无", "用一句话说想了解什么。")
        log_call("kb_search", False, step="输入")
        return out
    tokens = _tokens(q)
    ranked: list[tuple[float, dict, list[str]]] = []
    for item in iter_headers():
        score, why = _score(item, tokens)
        if score > 0:
            ranked.append((score, item, why))
    ranked.sort(key=lambda r: r[0], reverse=True)
    top = ranked[:SEARCH_LIMIT]
    if not top:
        out = "路标：没有像的。抬头扫过了，没有贴近这个问法的。不要装查过。\n"
        log_call("kb_search", True, hits=0, query=q)
        return out
    lines = [f"路标（最多 {SEARCH_LIMIT} 条，无正文）"]
    for i, (_s, item, why) in enumerate(top, 1):
        lines.append(f"{i}. [{item['kind']}] {item['title'] or item['ident']}  身份：{item['ident']}")
        lines.append(f"   像在：{'；'.join(why)}")
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
    return text[:CHAR_CAP] + "\n\n[已截断，一次一块有字数顶。要下一块请再点名。]\n"


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


@guarded("kb_read")
def read(target: str, part: str | None = None) -> str:
    target = (target or "").strip()
    if not target:
        out = fail(
            "阅读-点名",
            "没有身份。",
            "无",
            "先检索，拿路标上的身份再点名某一块。",
        )
        log_call("kb_read", False, step="点名")
        return out
    kind, slug, extra = _parse_target(target)
    if not kind or not slug:
        out = fail(
            "阅读-点名",
            f"身份无法识别：{target}。要 书/<slug> 或 笔记/<slug>。",
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
    log_call("kb_read", not out.startswith("失败"), target=target, part=use_part or "")
    return out
