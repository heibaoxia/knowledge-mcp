"""Search headers only; read named parts with a char cap."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.index import (
    CANDIDATE_LIMIT,
    HAN,
    MAP_FILE,
    SKIP_FILES,
    _block_name,
    book_is_dead,
    core_chapter_name,
    _share_affix,
    evidence_pieces,
    is_nav_name,
    _df,
    _ensure,
    _fts_piece,
    latin_blocked,
    map_index_text,
    parse_map,
    parse_query,
    search_index,
    search_maps,
    search_vectors,
)
from knowledge_mcp.log import guarded, log_call
from knowledge_mcp.paths import dirs

SEARCH_LIMIT = 5
RRF_K = 60
CHAR_CAP = 8000
BATCH_LIMIT = 5
TOTAL_CHAR_CAP = 24000
CHAPTER_SUGGEST_LIMIT = 3
LIT_GAP = 20
OVERVIEW_MARKS = ("大概讲什么", "这本书讲什么", "简介")
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


def _why_bits(items: list[dict], q: str = "", minlen: int = 2) -> list[str]:
    parts = [p for p in parse_query(q) if len(p) >= minlen] if q else []
    blob = " ".join((it.get("ident") or "") + (it.get("name") or "") for it in items)
    bits: list[str] = []
    for p in sorted(parts, key=len, reverse=True):
        if p in blob and p not in bits:
            bits.append(p)
        if len(bits) >= 4:
            return bits
    if bits:
        return bits
    for it in items:
        for p in it.get("why") or []:
            s = str(p)
            if s and s not in bits and len(s) <= 20 and len(s) >= minlen:
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


def _long_pieces(q: str) -> list[str]:
    """问句里 len≥3 的证据片（ASCII 同长也算）。这类片才是「沾的到底是不是这条」。"""
    return [p for p in evidence_pieces(q) if len(p) >= 3 or re.fullmatch(r"[A-Za-z0-9_]{3,}", p)]


def _longest_pieces(q: str) -> list[str]:
    """问句 len≥3 原片里最长的那一档（并列同长全算）。DF=0 也当门槛：
    只沾了公共片（len<3）的书拿不出这条证据，就不占仅字面/仅语义的格。"""
    parts = _long_pieces(q)
    if not parts:
        return []
    top = max(len(p) for p in parts)
    return [p for p in parts if len(p) == top]


def _map_has_piece(bid: str, longs: list[str]) -> bool:
    """本地图正文（能解决什么 + 建议从哪读）有没有问句的最长原片。"""
    if not longs:
        return True
    p = dirs()["books"] / bid / MAP_FILE
    if not p.is_file():
        return False
    try:
        blob = map_index_text(p.read_text(encoding="utf-8"))
    except OSError:
        return False
    return any(piece in blob for piece in longs)

def _book_has_piece(bid: str, piece: str) -> bool:
    try:
        n = _ensure().execute(
            "SELECT count(*) FROM docs WHERE kind != '地图' AND book_id = ? AND docs MATCH ?",
            (bid, _fts_piece(piece)),
        ).fetchone()[0]
    except Exception:
        return False
    return int(n or 0) > 0


def _best_score(items: list[dict]) -> float:
    if not items:
        return 0.0
    return float(min(float(it.get("score") or 0) for it in items))


def _has_longest(bid: str, longs: list[str]) -> bool:
    """这本书拿不拿得出最长档里的原片。"""
    return any(_book_has_piece(bid, p) for p in longs)


def _drop_weak_literal(q: str, lit_only: list[str], both: list[str], lit_groups: dict) -> list[str]:
    keep = list(lit_only)
    longs = _longest_pieces(q)
    cands = both + keep
    # 一本书沾的到底是不是问句这条：它得拿得出问句自己的最长原片（DF=0 也算
    # 门槛）。只沾了公共片（len<3）的不占名额。
    # 最长原片谁都拿不出时（问句末尾粘出来的「讲中国社会各阶级」），这条闸
    # 没有可问的证据，退回现成的 LIT_GAP，不许把期望书一起打掉。
    if longs and any(_has_longest(b, longs) for b in cands):
        keep = [b for b in keep if _has_longest(b, longs)]
    scored = both + keep
    if not scored:
        return keep
    head = min(_best_score(lit_groups.get(("书", b), [])) for b in scored)
    return [b for b in keep if _best_score(lit_groups.get(("书", b), [])) - head <= LIT_GAP]


def _overlap3(q: str, left: str, title: str) -> bool:
    for run in HAN.findall(left or ""):
        for i in range(len(run) - 2):
            tri = run[i : i + 3]
            if tri in q and tri not in (title or ""):
                return True
    return False


def _evidence_idents(slug: str, q: str, title: str) -> list[str]:
    p = dirs()["books"] / slug / MAP_FILE
    if not p.is_file():
        return []
    try:
        parsed = parse_map(p.read_text(encoding="utf-8"))
    except OSError:
        return []
    out: list[str] = []
    for line in parsed.get("evidence") or []:
        raw = str(line)
        sep = "→" if "→" in raw else ("->" if "->" in raw else "")
        if not sep:
            continue
        left, right = raw.split(sep, 1)
        ident = right.strip()
        if ident and ident not in out and _overlap3(q, left, title):
            out.append(ident)
    return out


def _named_in_query(name: str, q: str) -> bool:
    n = (name or "").strip()
    if not n or not q:
        return False
    if n in q:
        return True
    core = _strip_chap(n)
    return bool(core) and len(core) >= 2 and core in q


def _alias_right_idents(slug: str, q: str) -> list[str]:
    p = dirs()["books"] / slug / MAP_FILE
    if not p.is_file():
        return []
    try:
        parsed = parse_map(p.read_text(encoding="utf-8"))
    except OSError:
        return []
    out: list[str] = []
    for line in parsed.get("aliases") or []:
        raw = str(line)
        sep = "→" if "→" in raw else ("->" if "->" in raw else "")
        if not sep:
            continue
        left, right = raw.split(sep, 1)
        if not _named_in_query(left.strip(), q):
            continue
        idents = re.findall(r"书/\S+", right)
        for ident in idents:
            ident = ident.strip().rstrip("。．")
            if ident and ident not in out:
                out.append(ident)
    return out


def _book_suggest(slug: str, q: str, lit_items: list[dict], mp: dict | None) -> list[str]:
    title = _book_title(slug)
    sug: list[str] = []
    if any(m in q for m in OVERVIEW_MARKS):
        for spec in ("导读", "地图"):
            if (dirs()["books"] / slug / f"{spec}.md").is_file():
                ident = f"书/{slug}/{spec}"
                if ident not in sug:
                    sug.append(ident)
        return sug[:CHAPTER_SUGGEST_LIMIT]
    book_dir = dirs()["books"] / slug
    if book_dir.is_dir():
        for p in sorted(book_dir.glob("*.md")):
            if p.name in SKIP_FILES or is_nav_name(p.name):
                continue
            name = _block_name(p)
            ident = f"书/{slug}/{name}"
            if ident not in sug and _named_in_query(name, q):
                sug.append(ident)
    for it in lit_items:
        ident = it["ident"]
        name = it.get("name") or ""
        if ident not in sug and _named_in_query(name, q):
            sug.append(ident)
    for ident in _alias_right_idents(slug, q):
        if ident not in sug:
            sug.append(ident)
    for ident in _evidence_idents(slug, q, title):
        if ident not in sug:
            sug.append(ident)
    bits = [p for p in parse_query(q) if len(p) >= 2 and p not in title]
    for it in lit_items:
        ident = it["ident"]
        name = it.get("name") or ""
        if ident not in sug and any(p in name for p in bits):
            sug.append(ident)
    for it in lit_items:
        ident = it["ident"]
        if ident not in sug:
            sug.append(ident)
    if not sug and mp:
        for s in mp.get("suggest") or []:
            if s not in sug:
                sug.append(s)
    return sug[:CHAPTER_SUGGEST_LIMIT]


def _strip_chap(name: str) -> str:
    s = core_chapter_name(name or "")
    s = re.sub(r"^[0-9]+\s+", "", s)
    return s.strip()


def _has_aboutness(bid: str, q: str, pieces: list[str]) -> bool:
    title = _book_title(bid)
    solves = ""
    chaps: list[str] = []
    book_dir = dirs()["books"] / bid
    mp = book_dir / MAP_FILE
    if mp.is_file():
        try:
            parsed = parse_map(mp.read_text(encoding="utf-8"))
            solves = "\n".join(parsed.get("solves") or [])
        except OSError:
            solves = ""
    if book_dir.is_dir():
        for p in sorted(book_dir.glob("*.md")):
            if p.name in SKIP_FILES or is_nav_name(p.name):
                continue
            chaps.append(_block_name(p))
    blob = title + "\n" + solves
    for p in pieces:
        if 2 <= len(p) <= 8 and p in blob:
            return True
        if 3 <= len(p) <= 6:
            for drop in (1, 2):
                sub = p[:-drop]
                if len(sub) >= 2 and sub in blob:
                    return True
        if len(p) >= 3 and any(p in n for n in chaps):
            return True
    for n in chaps:
        s = _strip_chap(n)
        if s and s in q:
            return True
        if s and any(len(p) >= 2 and _share_affix(p, s) for p in pieces):
            return True
    return False


def _drop_dead_books(bids: list[str]) -> list[str]:
    keep = []
    for b in bids:
        d = dirs()["books"] / b
        if d.is_dir() and book_is_dead(d):
            continue
        keep.append(b)
    return keep


def _drop_no_aboutness(
    q: str, both: list[str], lit_only: list[str], map_only: list[str]
) -> tuple[list[str], list[str], list[str]]:
    cands = list(dict.fromkeys(both + lit_only + map_only))
    if not cands:
        return both, lit_only, map_only
    pieces = evidence_pieces(q)
    flags = {b: _has_aboutness(b, q, pieces) for b in cands}
    if not any(flags.values()):
        return both, lit_only, map_only
    return (
        [b for b in both if flags[b]],
        [b for b in lit_only if flags[b]],
        [b for b in map_only if flags[b]],
    )


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
    lit_set = set(lit_books)
    longs = _longest_pieces(q)
    long_any = _long_pieces(q)
    if long_any:
        map_by = {bid: h for bid, h in map_by.items() if _map_has_piece(bid, long_any)}
    else:
        map_by = {
            bid: h
            for bid, h in map_by.items()
            if bid in lit_set or _map_has_piece(bid, long_any)
        }
    map_order = [bid for bid in map_order if bid in map_by]
    both = [bid for bid in lit_books if bid in map_by]
    both.sort(
        key=lambda bid: (
            0
            if any(
                _named_in_query(it.get("name") or "", q)
                for it in lit_groups.get(("书", bid), [])
            )
            else 1
        )
    )
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
            items = lit_groups.get(("书", bid), [])
            blob = title + " ".join(
                (it.get("ident") or "") + (it.get("name") or "") for it in items
            )
            mp = map_by.get(bid)
            if mp:
                blob += " ".join(mp.get("suggest") or [])
            return any(x in blob for x in quoted)

        both = [b for b in both if _quoted_ok(b)]
        lit_only = [b for b in lit_only if _quoted_ok(b)]
        map_only = [b for b in map_only if _quoted_ok(b)]
    both = _drop_dead_books(both)
    lit_only = _drop_dead_books(lit_only)
    lit_only = _drop_weak_literal(q, lit_only, both, lit_groups)
    both, lit_only, map_only = _drop_no_aboutness(q, both, lit_only, map_only)
    if life:
        rest = [("仅语义", "书", b) for b in map_only] + [
            ("仅字面", "书", b) for b in lit_only
        ] + [("仅字面", k, b) for k, b in notes]
    else:
        rest = [("仅字面", "书", b) for b in lit_only] + [
            ("仅字面", k, b) for k, b in notes
        ] + [("仅语义", "书", b) for b in map_only]
    rows: list[tuple[str, str, str]] = [("两路都中", "书", b) for b in both] + rest
    lines = ["路标（无正文）"]
    n = 0
    last_col = None
    col_label = {
        "两路都中": "两路都中（优先）：",
        "仅字面": "仅字面：",
        "仅语义": "仅语义：",
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
            sug = _book_suggest(bid, q, lit_items, mp)
            lines.append(f"{n}. [{kind}] {title}  身份：{ident}")
            n_hit = len(lit_items)
            n_all = len(lit)
            if n_hit:
                lines.append(f"   命中 {n_hit} 块（全库 {n_all} 块）")
            if sug:
                lines.extend(_suggest_lines(sug))
            lit_why = _why_bits(lit_items, q)
            map_why = _why_bits([mp] if mp else [], q)
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


def _rrf_pool(lit: list[dict], vec: list[dict]) -> tuple[list[dict], list[dict]]:
    if not vec:
        return lit[:CANDIDATE_LIMIT], []
    scores: dict[str, float] = {}
    for r, h in enumerate(lit):
        ident = str(h.get("ident") or "")
        scores[ident] = scores.get(ident, 0.0) + 2.0 / (RRF_K + r + 1)
    for r, h in enumerate(vec):
        ident = str(h.get("ident") or "")
        scores[ident] = scores.get(ident, 0.0) + 1.0 / (RRF_K + r + 1)
    keep = {i for i, _ in sorted(scores.items(), key=lambda x: -x[1])[:CANDIDATE_LIMIT]}
    lit2 = [h for h in lit if str(h.get("ident")) in keep]
    vec2 = [h for h in vec if str(h.get("ident")) in keep]
    return lit2, vec2


def _merge_vec_into_maps(maps: list[dict], vec: list[dict]) -> list[dict]:
    have = {str(h.get("book_id")) for h in maps}
    out = list(maps)
    for h in vec:
        bid = str(h.get("book_id") or "")
        if not bid or bid in have:
            continue
        kind = str(h.get("kind") or "书")
        ident = f"书/{bid}" if kind == "书" else str(h.get("ident") or bid)
        out.append(
            {
                "ident": ident,
                "book_id": bid,
                "kind": kind,
                "suggest": [str(h.get("ident") or ident)],
                "why": [],
                "score": h.get("score"),
            }
        )
        have.add(bid)
    return out


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
        lit = search_index(q)[:CANDIDATE_LIMIT]
    except Exception:
        lit = _header_hits(q)[:CANDIDATE_LIMIT]
        extra["degraded"] = 1
    try:
        off = os.environ.get("KNOWLEDGE_EMBED", "").strip().lower() in {"off", "0", "false"}
        maps = [] if off else search_maps(q)
        vec = [] if off else search_vectors(q)
    except Exception:
        maps = []
        vec = []
    else:
        lit, vec = _rrf_pool(lit, vec)
        if lit or maps:
            maps = _merge_vec_into_maps(maps, vec)
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


def _split_part(part: str) -> tuple[str, int, str | None, int | None]:
    s = part or ""
    m = re.match(r"^(.*)@(\d+)$", s)
    if m:
        return m.group(1), 1, None, int(m.group(2))
    m = re.match(r"^(.*)#(\d+)$", s)
    if m:
        return m.group(1), max(1, int(m.group(2))), None, None
    m = re.match(r"^(.*)#([^#]+)$", s)
    if m:
        return m.group(1), 1, m.group(2).strip(), None
    return s, 1, None, None


def _win_ident(slug: str, name: str, win: int) -> str:
    if win <= 1:
        return f"书/{slug}/{name}"
    return f"书/{slug}/{name}#{win}"


def _section_list(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.M):
        title = re.sub(r"\s+#+\s*$", "", m.group(2)).strip()
        if title:
            out.append((title, m.start()))
    return out


def _section_tail(text: str, path: Path | None = None) -> str:
    bits: list[str] = []
    if path is not None and is_nav_name(path.name):
        bits.append("不必读")
    secs = _section_list(text)
    if secs:
        bits.append("节：" + " ｜ ".join(f"{t} @{off}" for t, off in secs[:24]))
    return ("\n" + "\n".join(bits) + "\n") if bits else ""


def _neighbors(
    files: list[Path],
    idx: int,
    slug: str,
    name: str,
    win: int,
    nwin: int,
    start_off: int | None = None,
) -> str:
    bits: list[str] = [f"本窗 {win}/{nwin}"]
    if start_off is not None:
        if start_off > 0:
            bits.append(f"上一窗 书/{slug}/{name}@{max(0, start_off - CHAR_CAP)}")
        if win < nwin:
            bits.append(f"下一窗 书/{slug}/{name}@{start_off + CHAR_CAP}")
    else:
        if win > 1:
            bits.append(f"上一窗 {_win_ident(slug, name, win - 1)}")
        if win < nwin:
            bits.append(f"下一窗 {_win_ident(slug, name, win + 1)}")
    if idx > 0:
        bits.append(f"上一块 书/{slug}/{_block_name(files[idx - 1])}")
    if idx + 1 < len(files):
        bits.append(f"下一块 书/{slug}/{_block_name(files[idx + 1])}")
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
    name, win, section, off = _split_part(part)
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
            start = 0
            if off is not None:
                start = max(0, min(off, len(text)))
            elif section:
                found = next((s_off for s_title, s_off in _section_list(text) if s_title == section), None)
                if found is None:
                    return fail(
                        "阅读-点名",
                        f"在 {slug} 里找不到「{section}」这一节。",
                        "无",
                        "对照该块节目录上的标题再点一次。",
                    )
                start = found
            if start:
                remain = text[start:]
                nwin = max(1, (len(remain) + CHAR_CAP - 1) // CHAR_CAP)
                chunk = _cap(remain)
                nb = _neighbors(files, i, slug, bname, 1, nwin, start_off=start)
                return chunk + (("\n" + nb) if nb else "") + _section_tail(text, p)
            nwin = max(1, (len(text) + CHAR_CAP - 1) // CHAR_CAP)
            if win > nwin:
                win = nwin
            chunk = _cap(text[(win - 1) * CHAR_CAP : win * CHAR_CAP])
            nb = _neighbors(files, i, slug, bname, win, nwin)
            return chunk + (("\n" + nb) if nb else "") + _section_tail(text, p)
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
