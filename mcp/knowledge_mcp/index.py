"""进程内 FTS5：二字片+单字索引，语片查询。不落盘。"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from knowledge_mcp.paths import dirs

HAN = re.compile(r"[\u4e00-\u9fff]+")
ASCII = re.compile(r"[A-Za-z0-9_]+")
FUN_WORDS = ("什么", "怎么", "如何", "这个", "一个", "我们", "自己")
FUN_CHARS = set("的了是和与及或在有被把让就都也还很到从对为")
NAV_MARKS = ("目录", "目 录", "索引", "参考文献", "术语表")

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


def query_match(q: str) -> str | None:
    parts = parse_query(q)
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
        "ident UNINDEXED, book_id UNINDEXED, kind UNINDEXED, "
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
                if p.name == "导读.md":
                    continue
                try:
                    raw = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                name = _block_name(p)
                body = "" if is_nav_name(p.name) else raw
                ident = f"书/{slug}/{name}"
                con.execute(
                    "INSERT INTO docs VALUES (?,?,?,?,?,?)",
                    (
                        ident,
                        slug,
                        "书",
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
                "INSERT INTO docs VALUES (?,?,?,?,?,?)",
                (
                    ident,
                    p.stem,
                    "笔记",
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
    real = _real_pieces(parts)
    if real:
        dfs = [(p, _df(con, p)) for p in real]
        if any(d == 0 for _, d in dfs):
            return []
        rarest = min(dfs, key=lambda x: (x[1], -len(x[0])))[0]
        gate = _fts_piece(rarest)
    else:
        gate = expr
    try:
        rows = con.execute(
            "SELECT ident, book_id, kind, name, bm25(docs) FROM docs "
            "WHERE docs MATCH ? AND docs MATCH ? ORDER BY bm25(docs)",
            (expr, gate),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ident, book_id, kind, name, score in rows:
        if ident in seen:
            continue
        seen.add(ident)
        why = [p for p in parts if p in ident or True][:3]
        out.append(
            {
                "ident": ident,
                "book_id": book_id,
                "kind": kind,
                "title": ident,
                "name": ident.rsplit("/", 1)[-1],
                "score": score,
                "why": why,
            }
        )
    return out
