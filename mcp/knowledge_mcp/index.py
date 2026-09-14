"""进程内 FTS5：二字片+单字索引，语片查询。不落盘。"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml

from knowledge_mcp.paths import dirs

HAN = re.compile(r"[\u4e00-\u9fff]+")
ASCII = re.compile(r"[A-Za-z0-9_]+")
FUN_WORDS = ("什么", "怎么", "如何", "这个", "一个", "我们", "自己")
FUN_CHARS = set("的了是和与及或在有被把让就都也还很到从对")
NAV_MARKS = ("目录", "目 录", "索引", "参考文献", "术语表")
MAP_FILE = "地图.md"
SKIP_FILES = frozenset({"导读.md", MAP_FILE})
IDENT_IN_LINE = re.compile(r"(?:书|笔记)/\S.*")

_con: sqlite3.Connection | None = None
_root: str | None = None


def tokenize_index(text: str) -> str:
    toks: list[str] = []
    for run in HAN.findall(text or ""):
        if len(run) == 1:
            toks.append(run)
        else:
            toks.extend(run[i : i + 2] for i in range(len(run) - 1))
            toks.extend(list(run))
    toks.extend(ASCII.findall(text or ""))
    return " ".join(toks)


def parse_query(q: str) -> list[str]:
    s = (q or "").strip()
    parts: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        token = "".join(buf)
        buf.clear()
        if not token:
            return
        for w in FUN_WORDS:
            if w == "什么" and "为什么" in token:
                token = token.replace("为什么", "\0")
                token = token.replace("什么", " ")
                token = token.replace("\0", "为什么")
            else:
                token = token.replace(w, " ")
        for bit in token.split():
            if bit in FUN_WORDS or all(c in FUN_CHARS for c in bit):
                continue
            parts.append(bit)

    for ch in s:
        if "\u4e00" <= ch <= "\u9fff":
            if ch in FUN_CHARS:
                flush()
            else:
                buf.append(ch)
        elif ch.isalnum() or ch == "_":
            buf.append(ch)
        else:
            flush()
    flush()
    return parts


def is_nav_name(filename: str) -> bool:
    name = Path(filename).name
    return any(m in name for m in NAV_MARKS)


def _fts_piece(piece: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_]+", piece) or len(piece) == 1:
        return piece
    if HAN.search(piece) and len(piece) >= 2:
        grams = [piece[i : i + 2] for i in range(len(piece) - 1)]
        return "(" + " AND ".join(grams) + ")"
    return piece


def _expand_pieces(parts: list[str]) -> list[str]:
    out: list[str] = []
    for p in parts:
        out.append(p)
        if HAN.search(p) and len(p) >= 4:
            out.extend(p[i : i + 3] for i in range(len(p) - 2))
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def query_match(q: str) -> str | None:
    parts = _expand_pieces(parse_query(q))
    if not parts:
        return None
    return " OR ".join(_fts_piece(p) for p in parts)


def _real_pieces(parts: list[str]) -> list[str]:
    return [p for p in parts if len(p) >= 2 or re.fullmatch(r"[A-Za-z0-9_]+", p)]


def invalidate() -> None:
    global _con, _root
    if _con is not None:
        _con.close()
        _con = None
    _root = None


def _block_name(path: Path) -> str:
    stem = path.stem
    m = re.match(r"^\d+-", stem)
    return stem[m.end() :] if m else stem


def _frontmatter(text: str) -> tuple[dict, str]:
    if not (text or "").startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, parts[2].lstrip("\n")


def _map_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in (body or "").splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _bullets(text: str) -> list[str]:
    return [ln.strip()[2:].strip() for ln in (text or "").splitlines() if ln.strip().startswith("- ")]


def parse_map(text: str) -> dict:
    meta, body = _frontmatter(text or "")
    secs = _map_sections(body)
    gen = meta.get("generated")
    errors: list[str] = []
    if meta.get("type") != "地图":
        errors.append("type 不是地图")
    if gen is not True and str(gen).lower() != "true":
        errors.append("generated 不是 true")
    return {
        "title": str(meta.get("title") or ""),
        "type": meta.get("type"),
        "book": meta.get("book"),
        "generated": gen,
        "solves": _bullets(secs.get("能解决什么", "")),
        "not_solves": _bullets(secs.get("不解决什么", "")),
        "suggest": _bullets(secs.get("建议从哪读", "")),
        "evidence": _bullets(secs.get("依据块", "")),
        "solves_body": secs.get("能解决什么", ""),
        "suggest_body": secs.get("建议从哪读", ""),
        "errors": errors,
        "sections": secs,
    }


def ident_exists(ident: str) -> bool:
    t = (ident or "").replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    t = re.sub(r"#\d+$", "", t)
    if t.startswith("笔记/"):
        slug = Path(t[3:]).stem
        return bool(slug) and (dirs()["notes"] / f"{slug}.md").is_file()
    if not t.startswith("书/"):
        return False
    bits = t[2:].split("/")
    slug = bits[0] if bits else ""
    if not slug:
        return False
    book = dirs()["books"] / slug
    if not book.is_dir():
        return False
    part = "/".join(bits[1:]) if len(bits) > 1 else ""
    if not part:
        return False
    if part in ("导读", "导读.md"):
        return (book / "导读.md").is_file()
    if part in ("地图", MAP_FILE):
        return (book / MAP_FILE).is_file()
    for p in book.glob("*.md"):
        if p.name in SKIP_FILES:
            continue
        if _block_name(p) == part:
            return True
    return False


def _idents_in(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        m = IDENT_IN_LINE.search(line)
        if m:
            out.append(m.group(0).strip().rstrip("。．"))
    return out


def map_problems(book_dir: Path) -> list[str]:
    book_dir = Path(book_dir)
    mp = book_dir / MAP_FILE
    if not mp.is_file():
        return ["缺地图"]
    try:
        text = mp.read_text(encoding="utf-8")
    except OSError as e:
        return [f"读地图失败：{e}"]
    parsed = parse_map(text)
    probs = list(parsed.get("errors") or [])
    slug = book_dir.name
    if parsed.get("book") != f"书/{slug}":
        probs.append(f"book 应为 书/{slug}")
    guide = book_dir / "导读.md"
    guide_title = ""
    if guide.is_file():
        try:
            meta, _ = _frontmatter(guide.read_text(encoding="utf-8"))
            guide_title = str(meta.get("title") or "")
        except OSError:
            guide_title = ""
    if parsed.get("title") != guide_title:
        probs.append("title 与导读不一致")
    secs = parsed.get("sections") or {}
    for name in ("能解决什么", "不解决什么", "建议从哪读", "依据块"):
        if name not in secs:
            probs.append(f"缺「{name}」段")
    solves = parsed.get("solves") or []
    if not (3 <= len(solves) <= 8):
        probs.append("能解决什么须 3–8 条")
    if any(len(s) > 40 for s in solves):
        probs.append("能解决什么某条超过 40 字")
    not_solves = parsed.get("not_solves") or []
    if not (1 <= len(not_solves) <= 5):
        probs.append("不解决什么须 1–5 条")
    evidence = parsed.get("evidence") or []
    suggest = parsed.get("suggest") or []
    for ident in _idents_in(suggest + evidence):
        if not ident_exists(ident):
            probs.append(f"身份不存在：{ident}")
    if sum(1 for line in evidence if "书/" in line) < len(solves):
        probs.append("依据块条数少于能解决什么")
    if solves:
        by_text = all(any(s in line for line in evidence) for s in solves)
        if not (by_text or len(evidence) >= len(solves)):
            probs.append("能解决什么未挂依据块")
    return probs


def map_index_text(text: str) -> str:
    parsed = parse_map(text)
    return "\n".join(
        x for x in (parsed.get("solves_body") or "", parsed.get("suggest_body") or "") if x
    )


def _ensure() -> sqlite3.Connection:
    global _con, _root
    root = str(dirs()["root"])
    if _con is not None and _root != root:
        invalidate()
    if _con is not None:
        return _con
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE VIRTUAL TABLE docs USING fts5("
        "ident UNINDEXED, book_id UNINDEXED, kind UNINDEXED, label UNINDEXED, "
        "title, name, body)"
    )
    books = dirs()["books"]
    if books.is_dir():
        for guide in sorted(books.glob("*/导读.md")):
            slug = guide.parent.name
            title = slug
            try:
                head = guide.read_text(encoding="utf-8")
                m = re.search(r"^title:\s*(.+)$", head, re.M)
                if m:
                    title = m.group(1).strip().strip("\"'")
            except OSError:
                pass
            for p in sorted(guide.parent.glob("*.md")):
                if p.name in SKIP_FILES:
                    continue
                try:
                    raw = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                name = _block_name(p)
                body = "" if is_nav_name(p.name) else raw
                ident = f"书/{slug}/{name}"
                con.execute(
                    "INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
                    (
                        ident,
                        slug,
                        "书",
                        name,
                        tokenize_index(title),
                        tokenize_index(name),
                        tokenize_index(body),
                    ),
                )
    notes = dirs()["notes"]
    if notes.is_dir():
        for p in sorted(notes.glob("*.md")):
            try:
                raw = p.read_text(encoding="utf-8")
            except OSError:
                continue
            ident = f"笔记/{p.stem}"
            tm = re.search(r"^title:\s*(.+)$", raw, re.M)
            note_title = tm.group(1).strip().strip("\"'") if tm else p.stem
            con.execute(
                "INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
                (
                    ident,
                    p.stem,
                    "笔记",
                    note_title,
                    tokenize_index(note_title),
                    tokenize_index(note_title),
                    tokenize_index(raw),
                ),
            )
    _con = con
    _root = str(dirs()["root"])
    return con


def _df(con: sqlite3.Connection, piece: str) -> int:
    expr = _fts_piece(piece)
    try:
        row = con.execute(
            "SELECT count(*) FROM docs WHERE docs MATCH ?", (expr,)
        ).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.OperationalError:
        return 0


def search_index(q: str) -> list[dict]:
    parts = parse_query(q)
    expr = query_match(q)
    if not expr:
        return []
    con = _ensure()
    real = _real_pieces(_expand_pieces(parts))
    if real:
        dfs = [(p, _df(con, p)) for p in real]
        latin_miss = any(
            d == 0 and re.fullmatch(r"[A-Za-z0-9_]+", p) for p, d in dfs
        )
        if latin_miss:
            return []
        dfs = [(p, d) for p, d in dfs if d > 0]
        if not dfs:
            return []
        long = [p for p, d in dfs if d > 0 and (len(p) >= 3 or re.fullmatch(r"[A-Za-z0-9_]{3,}", p))]
        if long:
            gate = " OR ".join(_fts_piece(p) for p in long)
        else:
            gate = expr
    else:
        gate = expr
    try:
        rows = con.execute(
            "SELECT ident, book_id, kind, label, bm25(docs, 3.0, 3.0, 1.0) FROM docs "
            "WHERE docs MATCH ? AND docs MATCH ? ORDER BY bm25(docs, 3.0, 3.0, 1.0)",
            (expr, gate),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ident, book_id, kind, label, score in rows:
        if ident in seen:
            continue
        seen.add(ident)
        why = [p for p in parts if p and (p in ident or p in (label or ""))][:3]
        out.append(
            {
                "ident": ident,
                "book_id": book_id,
                "kind": kind,
                "title": label or ident,
                "name": label or ident.rsplit("/", 1)[-1],
                "score": score,
                "why": why,
            }
        )
    boost_bits = _expand_pieces(parts)
    out.sort(
        key=lambda h: (
            0
            if any(p in (h.get("name") or "") for p in boost_bits if len(p) >= 2)
            else 1,
            h["score"],
        )
    )
    return out
