"""Search headers only; read named parts with a char cap."""
from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.index import (
    HAN,
    MAP_FILE,
    SKIP_FILES,
    _block_name,
    latin_blocked,
    map_index_text,
    parse_map,
    parse_query,
    search_index,
    search_maps,
)
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


LIFE_MARKS = ("怎么办", "我总是")
EMPTY_LANDMARKS = "路标：没有像的。索引扫过了，没有贴近这个问法的。不要装查过。\n"


def _life_query(q: str) -> bool:
    return any(m in q for m in LIFE_MARKS)


def _map_suggest(slug: str) -> list[str]:
    p = dirs()["books"] / slug / MAP_FILE
    if not p.is_file():
        return []
    try:
        parsed = parse_map(p.read_text(encoding="utf-8"))
    except OSError:
        return []
    return [s for s in (parsed.get("suggest") or []) if s]


def _life_fallback(q: str) -> list[dict]:
    grams: list[str] = []
    for run in HAN.findall(q):
        grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    scored: list[tuple[int, dict]] = []
    books = dirs()["books"]
    if not books.is_dir():
        return []
    for guide in books.glob("*/导读.md"):
        mp = guide.parent / MAP_FILE
        if not mp.is_file():
            continue
        try:
            raw = mp.read_text(encoding="utf-8")
        except OSError:
            continue
        blob = map_index_text(raw)
        n = sum(1 for g in grams if g in blob)
        if n <= 0:
            continue
        slug = guide.parent.name
        scored.append(
            (
                n,
                {
                    "ident": f"书/{slug}",
                    "book_id": slug,
                    "kind": "书",
                    "suggest": _map_suggest(slug),
                    "why": [g for g in grams if g in blob][:4],
                    "score": -n,
                },
            )
        )
    scored.sort(key=lambda x: -x[0])
    return [h for _, h in scored[:1]]


def _why_bits(items: list[dict]) -> list[str]:
    bits: list[str] = []
    for it in items:
        for p in it.get("why") or []:
            s = str(p)
            if s and s not in bits and len(s) <= 20:
                bits.append(s)
    return bits[:4]


def _suggest_lines(idents: list[str]) -> list[str]:
    out = ["   建议块："]
    for ident in idents[:CHAPTER_SUGGEST_LIMIT]:
        out.append(f"   · {ident}")
    return out


def _header_hits(q: str) -> list[dict]:
    tokens = _tokens(q)
    out: list[dict] = []
    for item in iter_headers():
        score, why, chaps = _score(item, tokens)
        if score <= 0:
            continue
        bid = item["ident"].split("/", 1)[-1]
        if item["kind"] == "书" and chaps:
            idents = [f"{item['ident']}/{c}" for c in chaps]
        else:
            idents = [item["ident"]]
        for ident in idents:
            out.append(
                {
                    "ident": ident,
                    "book_id": bid,
                    "kind": item["kind"],
                    "title": item["title"] or bid,
                    "name": item["title"] or bid,
                    "score": -score,
                    "why": why,
                }
            )
    out.sort(key=lambda h: h["score"])
    return out


def _life_literal_ok(q: str, bid: str, items: list[dict]) -> bool:
    longs = [p for p in parse_query(q) if len(p) >= 3]
    if not longs:
        return True
    blob = _book_title(bid) + " ".join(
        (it.get("ident") or "") + (it.get("name") or "") for it in items
    )
    return any(p in blob for p in longs)


def _format_landmarks(
    lit: list[dict], maps: list[dict], life: bool, q: str
) -> tuple[str, int, int, int]:
    lit_groups: dict[tuple[str, str], list[dict]] = {}
    lit_order: list[tuple[str, str]] = []
    for h in lit:
        key = (str(h["kind"]), str(h["book_id"]))
        if key not in lit_groups:
            lit_groups[key] = []
            lit_order.append(key)
        lit_groups[key].append(h)
    map_by: dict[str, dict] = {}
    map_order: list[str] = []
    for h in maps:
        bid = str(h["book_id"])
        if bid not in map_by:
            map_by[bid] = h
            map_order.append(bid)
    lit_books = [bid for kind, bid in lit_order if kind == "书"]
    notes = [(kind, bid) for kind, bid in lit_order if kind != "书"]
    both = [bid for bid in lit_books if bid in map_by]
    lit_only = [bid for bid in lit_books if bid not in map_by]
    if life:
        lit_only = [
            bid
            for bid in lit_only
            if _life_literal_ok(q, bid, lit_groups.get(("书", bid), []))
        ]
    map_only = [bid for bid in map_order if bid not in set(lit_books)]
    quoted = re.findall(r"《([^》]+)》", q)
    if quoted:
        def _quoted_ok(bid: str) -> bool:
            title = _book_title(bid)
            return any(x in title for x in quoted)

        both = [b for b in both if _quoted_ok(b)]
        lit_only = [b for b in lit_only if _quoted_ok(b)]
        map_only = [b for b in map_only if _quoted_ok(b)]
    if life:
        rest = [("仅地图", "书", b) for b in map_only] + [
            ("仅字面", "书", b) for b in lit_only
        ] + [("仅字面", k, b) for k, b in notes]
    else:
        rest = [("仅字面", "书", b) for b in lit_only] + [
            ("仅字面", k, b) for k, b in notes
        ] + [("仅地图", "书", b) for b in map_only]
    rows: list[tuple[str, str, str]] = [("两路都中", "书", b) for b in both] + rest
    lines = ["路标（无正文）"]
    n = 0
    last_col = None
    col_label = {
        "两路都中": "两路都中（优先）：",
        "仅字面": "仅字面：",
        "仅地图": "仅地图：",
    }
    for col, kind, bid in rows:
        n += 1
        if n > SEARCH_LIMIT:
            break
        if col != last_col:
            lines.append(col_label[col])
            last_col = col
        if kind == "书":
            ident = f"书/{bid}"
            title = _book_title(bid)
            lit_items = lit_groups.get(("书", bid), [])
            mp = map_by.get(bid)
            sug: list[str] = []
            for it in lit_items:
                if it["ident"] not in sug:
                    sug.append(it["ident"])
            if mp:
                for s in mp.get("suggest") or []:
                    if s not in sug:
                        sug.append(s)
            if not sug and mp:
                sug = list(mp.get("suggest") or [])
            lines.append(f"{n}. [{kind}] {title}  身份：{ident}")
            if sug:
                lines.extend(_suggest_lines(sug))
            lit_why = _why_bits(lit_items)
            map_why = _why_bits([mp] if mp else [])
            if col == "两路都中":
                lw = "、".join(lit_why) if lit_why else "正文"
                mw = "、".join(map_why) if map_why else "能解决什么"
                lines.append(f"   字面：含「{lw}」；地图：能解决「{mw}」")
            elif col == "仅字面":
                if lit_why:
                    lines.append(f"   字面：含「{'、'.join(lit_why)}」")
                else:
                    lines.append("   字面：正文")
            else:
                if map_why:
                    lines.append(f"   地图：能解决「{'、'.join(map_why)}」")
                else:
                    lines.append("   地图：能解决什么")
        else:
            items = lit_groups[(kind, bid)]
            ident = f"笔记/{bid}"
            title = items[0].get("title") or items[0].get("name") or bid
            lines.append(f"{n}. [{kind}] {title}  身份：{ident}")
            lines.extend(_suggest_lines([it["ident"] for it in items]))
            why = _why_bits(items)
            if why:
                lines.append(f"   字面：含「{'、'.join(why)}」")
            else:
                lines.append("   字面：正文")
    return (
        "\n".join(lines) + "\n",
        len(both),
        len(lit_only) + len(notes),
        len(map_only),
    )


@guarded("kb_search")
def search(query: str) -> str:
    q = (query or "").strip()
    if not q:
        out = fail("检索", "没有问什么。", "无", "用一句话说想了解什么。")
        log_call("kb_search", False, step="输入")
        return out
    t0 = time.perf_counter()
    extra: dict = {}
    try:
        lit = search_index(q)
    except Exception:
        lit = _header_hits(q)
        extra["degraded"] = 1
    try:
        maps = search_maps(q)
    except Exception:
        maps = []
    if not lit and not maps:
        if not latin_blocked(q) and _life_query(q):
            maps = _life_fallback(q)
        if not lit and not maps:
            out = EMPTY_LANDMARKS
            log_call(
                "kb_search",
                True,
                hits=0,
                query=q,
                search_ms=int((time.perf_counter() - t0) * 1000),
                both=0,
                lit=0,
                map=0,
                **extra,
            )
            return out
    out, both_n, lit_n, map_n = _format_landmarks(lit, maps, _life_query(q), q)
    log_call(
        "kb_search",
        True,
        hits=min(out.count("身份："), SEARCH_LIMIT),
        query=q,
        search_ms=int((time.perf_counter() - t0) * 1000),
        both=both_n,
        lit=lit_n,
        map=map_n,
        **extra,
    )
    return out


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
    special = "导读" if name in ("导读", "导读.md") else ("地图" if name in ("地图", "地图.md") else None)
    if special:
        p = book / f"{special}.md"
        if not p.is_file():
            return fail("阅读-点名", f"这份书没有{special}。", "无", "换一块或先入库。")
        text = p.read_text(encoding="utf-8")
        nwin = max(1, (len(text) + CHAR_CAP - 1) // CHAR_CAP)
        chunk = _cap(text[(win - 1) * CHAR_CAP : win * CHAR_CAP])
        nb = _neighbors([], 0, slug, special, win, nwin)
        return chunk + (("\n" + nb) if nb else "")
    def _file_key(p: Path) -> tuple[int, str]:
        m = re.match(r"^(\d+)", p.name)
        return (int(m.group(1)) if m else 10**9, p.name)

    files = [p for p in sorted(book.glob("*.md"), key=_file_key) if p.name not in SKIP_FILES]
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
