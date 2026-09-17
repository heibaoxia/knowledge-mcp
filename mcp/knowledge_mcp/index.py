"""进程内 FTS5：二字片+单字索引，语片查询。不落盘。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import yaml

from knowledge_mcp.paths import dirs

CANDIDATE_LIMIT = 30
BM25_WEIGHTS = (4.0, 3.0, 3.0, 1.0)

HAN = re.compile(r"[\u4e00-\u9fff]+")
ASCII = re.compile(r"[A-Za-z0-9_]+")
FUN_WORDS = ("什么", "怎么", "如何", "这个", "一个", "我们", "自己")
FUN_CHARS = set("的了是和与及或在有被把让就都也还很到从对")
NAV_MARKS = ("目录", "目 录", "索引", "参考文献", "术语表")
MAP_FILE = "地图.md"
SKIP_FILES = frozenset({"导读.md", MAP_FILE})
IDENT_IN_LINE = re.compile(r"(?:书|笔记)/\S.*")
CHAP_PREFIX = re.compile(r"^第[零一二三四五六七八九十百千0-9]+[章节卷]\s*")
ALIAS_BAN = frozenset({"变化", "发生", "怎么回事", "一回事"})

_con: sqlite3.Connection | None = None
_root: str | None = None
_lock = threading.RLock()
_vectors: dict[str, list[float]] = {}
_vec_meta: dict[str, tuple[str, str, str]] = {}  # ident -> (book_id, kind, label)
EmbedFn = Callable[[list[str]], list[list[float]]]
_embed_fn: EmbedFn | None = None
VEC_DIM = 16
_ENV_LOADED = False
EMBED_BATCH = 8


def set_embedder(fn: EmbedFn | None) -> None:
    global _embed_fn
    _embed_fn = fn


def _embed_off() -> bool:
    return os.environ.get("KNOWLEDGE_EMBED", "").strip().lower() in {"off", "0", "false"}


def _load_dotenv() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    p = Path(__file__).resolve().parents[2] / ".env"
    if not p.is_file():
        return
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _embed_key() -> str:
    _load_dotenv()
    return (
        os.environ.get("KNOWLEDGE_EMBED_KEY")
        or os.environ.get("SILICONFLOW_API_KEY")
        or ""
    ).strip()


def _embed_url() -> str:
    _load_dotenv()
    return (os.environ.get("KNOWLEDGE_EMBED_URL") or "https://api.siliconflow.cn/v1").strip().rstrip("/")


def _embed_model() -> str:
    _load_dotenv()
    return (os.environ.get("KNOWLEDGE_EMBED_MODEL") or "BAAI/bge-m3").strip()


def _use_remote() -> bool:
    if _embed_fn is not None or _embed_off():
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return bool(_embed_key())


def _l2(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _hash_embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for t in texts:
        acc = [0.0] * VEC_DIM
        raw = hashlib.sha256((t or "").encode("utf-8", "ignore")).digest()
        for i, b in enumerate(raw):
            acc[i % VEC_DIM] += (b - 127.5) / 127.5
        out.append(_l2(acc))
    return out


def _api_embed(texts: list[str]) -> list[list[float]]:
    url = _embed_url() + "/embeddings"
    key = _embed_key()
    model = _embed_model()
    out: list[list[float] | None] = [None] * len(texts)
    n = len(texts)
    for i in range(0, n, EMBED_BATCH):
        if n > 8:
            print(f"embed {min(i + EMBED_BATCH, n)}/{n}", flush=True)
        chunk = [(t or " ").strip() or " " for t in texts[i : i + EMBED_BATCH]]
        body = json.dumps({"model": model, "input": chunk, "encoding_format": "float"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        last_err: Exception | None = None
        payload = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                last_err = None
                break
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in {429, 500, 502, 503} and attempt < 3:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise RuntimeError(f"embedding HTTP {e.code}") from None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = e
                if attempt < 3:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise RuntimeError("embedding request failed") from None
        if payload is None:
            raise RuntimeError("embedding request failed") from last_err
        rows = payload.get("data") or []
        for row in rows:
            idx = int(row.get("index") or 0)
            vec = [float(x) for x in (row.get("embedding") or [])]
            if 0 <= idx < len(chunk):
                out[i + idx] = vec
        if any(out[i + j] is None for j in range(len(chunk))):
            raise RuntimeError("embedding response missing rows")
    return [_l2(v) for v in out]  # type: ignore[arg-type]


def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if _embed_fn is not None:
        vecs = _embed_fn(texts)
    elif _use_remote():
        vecs = _api_embed(texts)
    else:
        vecs = _hash_embed(texts)
    return [_l2(list(v)) for v in vecs]


def _vec_cache_path() -> Path:
    return dirs()["root"] / "mcp" / ".kb-index.sqlite"


def _vec_digest(text: str) -> str:
    return hashlib.sha256((_embed_model() + "\n" + (text or "")).encode("utf-8", "ignore")).hexdigest()


def _cache_conn() -> sqlite3.Connection:
    path = _vec_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS vecs ("
        "ident TEXT NOT NULL, model TEXT NOT NULL, digest TEXT NOT NULL, "
        "dim INTEGER NOT NULL, blob BLOB NOT NULL, "
        "PRIMARY KEY (ident, model))"
    )
    return con


def _cache_get(ident: str, digest: str) -> list[float] | None:
    model = _embed_model()
    try:
        con = _cache_conn()
        row = con.execute(
            "SELECT dim, blob FROM vecs WHERE ident = ? AND model = ? AND digest = ?",
            (ident, model, digest),
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    dim, blob = int(row[0]), row[1]
    if not blob or dim <= 0:
        return None
    return list(struct.unpack(f"{dim}f", blob))


def _cache_put(ident: str, digest: str, vec: list[float]) -> None:
    model = _embed_model()
    blob = struct.pack(f"{len(vec)}f", *vec)
    try:
        con = _cache_conn()
        con.execute(
            "INSERT OR REPLACE INTO vecs (ident, model, digest, dim, blob) VALUES (?,?,?,?,?)",
            (ident, model, digest, len(vec), blob),
        )
        con.commit()
        con.close()
    except sqlite3.Error:
        return


def _fill_vectors(items: list[tuple[str, str]]) -> None:
    if not items:
        return
    remote = _use_remote()
    missing: list[tuple[str, str, str]] = []
    for ident, text in items:
        digest = _vec_digest(text)
        cached = _cache_get(ident, digest) if remote else None
        if cached:
            _vectors[ident] = _l2(cached)
        else:
            missing.append((ident, text, digest))
    if not missing:
        return
    n = len(missing)
    for i in range(0, n, EMBED_BATCH):
        chunk = missing[i : i + EMBED_BATCH]
        if n > EMBED_BATCH:
            print(f"embed {min(i + EMBED_BATCH, n)}/{n}", flush=True)
        try:
            vecs = _embed([t for _, t, _ in chunk])
        except Exception:
            if remote:
                vecs = _hash_embed([t for _, t, _ in chunk])
            else:
                raise
        for (ident, _, digest), vec in zip(chunk, vecs):
            _vectors[ident] = vec
            if remote:
                _cache_put(ident, digest, vec)


def _map_bits_for(ident: str, parsed: dict | None) -> str:
    if not parsed:
        return ""
    bits: list[str] = []
    for line in parsed.get("aliases") or []:
        if ident in line:
            bits.append(_alias_left(line))
    for line in parsed.get("evidence") or []:
        if ident in line:
            bits.append(_alias_left(line))
    return " ".join(bits)


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

    def flush(drop_tail: bool = False) -> None:
        if not buf:
            return
        # 「矛盾论讲了什么」：了把动词甩在词尾（矛盾论讲）。只认「了」，
        # 不按字面杀「讲」——否则「如何克服演讲」会被啃成「克服演」。
        if drop_tail and len(buf) >= 3:
            buf.pop()
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
            if bit:
                parts.append(bit)

    for i, ch in enumerate(s):
        if "\u4e00" <= ch <= "\u9fff":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            one_each = len(buf) == 1 and "\u4e00" <= nxt <= "\u9fff" and nxt not in FUN_CHARS
            if ch in FUN_CHARS and not one_each:
                flush(ch == "了")
            else:
                buf.append(ch)
        elif ch.isalnum() or ch == "_":
            buf.append(ch)
        else:
            flush()
    flush()
    for quoted in re.findall(r"《([^》]+)》", s):
        quoted = quoted.strip()
        if quoted and quoted not in parts:
            parts.append(quoted)
    return parts


def _strip_fun_tail(piece: str) -> str:
    s = piece
    while len(s) >= 2 and s[-1] in FUN_CHARS:
        s = s[:-1]
    return s


def _edge_existing(con: sqlite3.Connection, piece: str) -> str:
    if len(piece) < 5:
        return piece
    best = None
    n = len(piece)
    for drop_l in range(0, 3):
        for drop_r in range(0, 3):
            if drop_l == 0 and drop_r == 0:
                continue
            end = n - drop_r if drop_r else n
            s = piece[drop_l:end]
            if len(s) < 3:
                continue
            if _df(con, s) > 0 and (best is None or len(s) > len(best)):
                best = s
    return best or piece


EXPAND_BAN = ALIAS_BAN | {"怎么", "什么"}


def _longest_existing_prefix(con: sqlite3.Connection, piece: str) -> str:
    if len(piece) < 3 or _df(con, piece) > 0:
        return piece
    for n in range(len(piece) - 1, 1, -1):
        s = piece[:n]
        if _df(con, s) > 0:
            return s
    return piece


def _overlap2(q: str, left: str) -> bool:
    if not q or not left or len(left) < 2:
        return False
    if left in q:
        return True
    return any(left[i : i + 2] in q for i in range(len(left) - 1))


def _share_affix(piece: str, core: str) -> bool:
    """问句片与章名：整核在片里，或较长片与较短章名共享前后缀。"""
    if len(piece) < 2 or len(core) < 2:
        return False
    if core in piece:
        return True
    if piece in core and len(piece) >= 3:
        return True
    if len(piece) >= 4 and 2 <= len(core) <= len(piece):
        nmax = min(len(core), 4)
        for n in range(nmax, 1, -1):
            if piece[-n:] == core[-n:] or piece[:n] == core[:n]:
                return True
    return False


def _expand_struct_terms(q: str) -> list[str]:
    """别名左串按 ≥2 字重叠扩；章名只在问句出现或与原片前后缀相关时扩。"""
    out: list[str] = []
    books = dirs()["books"]
    if not books.is_dir():
        return out
    pieces = [_strip_fun_tail(p) for p in parse_query(q)]
    pieces = [p for p in pieces if len(p) >= 2]

    def add(term: str) -> None:
        t = (term or "").strip()
        if t and t not in EXPAND_BAN and len(t) >= 2 and t not in out:
            out.append(t)

    for mp in books.glob("*/" + MAP_FILE):
        try:
            parsed = parse_map(mp.read_text(encoding="utf-8"))
        except OSError:
            continue
        for left in parsed.get("alias_lefts") or []:
            if _overlap2(q, left):
                add(left)
        for ch in parsed.get("chapters") or []:
            core = core_chapter_name(ch) or ch
            if core in q or ch in q or any(_share_affix(p, core) for p in pieces):
                add(core)
    for pth in books.glob("*/*.md"):
        if pth.name in SKIP_FILES or is_nav_name(pth.name):
            continue
        name = _block_name(pth)
        core = core_chapter_name(name) or name
        if core in q or name in q or any(_share_affix(p, core) for p in pieces):
            add(core)
    return out[:12]


def _base_pieces(q: str) -> list[str]:
    parts = parse_query(q)
    if not parts:
        return []
    con = _ensure()
    out: list[str] = []
    for s in parts:
        s = _strip_fun_tail(s)
        if not s:
            continue
        if len(s) >= 5 and _df(con, s) == 0:
            s = _edge_existing(con, s)
        if len(s) >= 3 and _df(con, s) == 0:
            s = _longest_existing_prefix(con, s)
        if s and s not in out:
            out.append(s)
    return out


def evidence_pieces(q: str) -> list[str]:
    """原片（剥前缀）+ 别名/章名扩写。扩写不进最长片闸。"""
    out = _base_pieces(q)
    for extra in _expand_struct_terms(q):
        if extra not in out:
            out.append(extra)
    return out


def is_shell_text(raw: str) -> bool:
    han = len(re.findall(r"[\u4e00-\u9fff]", raw or ""))
    img = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", raw or ""))
    return han < 80 and img >= 10


def book_is_dead(book_dir: Path) -> bool:
    book_dir = Path(book_dir)
    content: list[bool] = []
    for p in sorted(book_dir.glob("*.md")):
        if p.name in SKIP_FILES or is_nav_name(p.name):
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            continue
        content.append(is_shell_text(raw))
    return bool(content) and all(content)


def is_nav_name(filename: str) -> bool:
    name = Path(filename).name
    return any(m in name for m in NAV_MARKS)


def _fts_piece(piece: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_]+", piece) or len(piece) == 1:
        return piece
    runs = HAN.findall(piece or "")
    ascii_toks = ASCII.findall(piece or "")
    parts: list[str] = []
    for run in runs:
        if len(run) == 1:
            parts.append(run)
        else:
            grams = [run[i : i + 2] for i in range(len(run) - 1)]
            parts.append('"' + " ".join(grams) + '"' if len(grams) > 1 else grams[0])
    parts.extend(ascii_toks)
    if not parts:
        return piece
    if len(parts) == 1:
        return parts[0]
    return "(" + " AND ".join(parts) + ")"


def query_match(q: str) -> str | None:
    parts = evidence_pieces(q)
    if not parts:
        return None
    return " OR ".join(_fts_piece(p) for p in parts)


def _real_pieces(parts: list[str]) -> list[str]:
    return [p for p in parts if len(p) >= 2 or re.fullmatch(r"[A-Za-z0-9_]+", p)]


def invalidate() -> None:
    global _con, _root, _vectors, _vec_meta
    with _lock:
        if _con is not None:
            _con.close()
            _con = None
        _root = None
        _vectors = {}
        _vec_meta = {}


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


def core_chapter_name(name: str) -> str:
    return CHAP_PREFIX.sub("", (name or "").strip()).strip()


def _alias_left(line: str) -> str:
    raw = (line or "").strip()
    if "→" in raw:
        return raw.split("→", 1)[0].strip()
    if "->" in raw:
        return raw.split("->", 1)[0].strip()
    return raw


def parse_map(text: str) -> dict:
    meta, body = _frontmatter(text or "")
    secs = _map_sections(body)
    gen = meta.get("generated")
    errors: list[str] = []
    if meta.get("type") != "地图":
        errors.append("type 不是地图")
    if gen is not True and str(gen).lower() != "true":
        errors.append("generated 不是 true")
    aliases = _bullets(secs.get("别名", ""))
    return {
        "title": str(meta.get("title") or ""),
        "type": meta.get("type"),
        "book": meta.get("book"),
        "generated": gen,
        "solves": _bullets(secs.get("能解决什么", "")),
        "not_solves": _bullets(secs.get("不解决什么", "")),
        "suggest": _bullets(secs.get("建议从哪读", "")),
        "evidence": _bullets(secs.get("依据块", "")),
        "chapters": _bullets(secs.get("章名", "")),
        "aliases": aliases,
        "alias_lefts": [_alias_left(a) for a in aliases],
        "topics": _bullets(secs.get("主题词", "")),
        "solves_body": secs.get("能解决什么", ""),
        "suggest_body": secs.get("建议从哪读", ""),
        "chapter_body": secs.get("章名", ""),
        "topic_body": secs.get("主题词", ""),
        "errors": errors,
        "sections": secs,
    }


def ident_exists(ident: str) -> bool:
    t = (ident or "").replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    t = re.sub(r"@\d+$", "", t)
    t = re.sub(r"#\d+$", "", t)
    t = re.sub(r"#[^/]+$", "", t)
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
    cover_blob = (parsed.get("chapter_body") or "") + "\n" + (parsed.get("solves_body") or "")
    cores: list[str] = []
    for p in sorted(book_dir.glob("*.md")):
        if p.name in SKIP_FILES or is_nav_name(p.name):
            continue
        core = core_chapter_name(_block_name(p))
        if core:
            cores.append(core)
    if cores:
        hit = sum(1 for c in cores if c in cover_blob)
        if hit / len(cores) < 0.8:
            probs.append("章名覆盖不足")
    for line in parsed.get("aliases") or []:
        sep = "→" if "→" in line else ("->" if "->" in line else "")
        if not sep:
            probs.append(f"别名须指向身份：{line}")
            continue
        left, right = line.split(sep, 1)
        left = left.strip()
        if len(left) < 2:
            probs.append(f"别名太短：{left}")
        if left in ALIAS_BAN:
            probs.append(f"别名禁止公共词：{left}")
        idents = _idents_in([right])
        if not idents:
            probs.append(f"别名须指向身份：{line}")
        for ident in idents:
            if not ident_exists(ident):
                probs.append(f"身份不存在：{ident}")
    if "主题词" in secs:
        topics = parsed.get("topics") or []
        if not (2 <= len(topics) <= 40):
            probs.append("主题词须 2–40 条")
        if any(len(t) > 20 for t in topics):
            probs.append("主题词某条超过 20 字")
    return probs


def map_index_text(text: str) -> str:
    parsed = parse_map(text)
    return "\n".join(
        x
        for x in (
            parsed.get("solves_body") or "",
            parsed.get("suggest_body") or "",
            parsed.get("chapter_body") or "",
            "\n".join(parsed.get("alias_lefts") or []),
            parsed.get("topic_body") or "",
        )
        if x
    )


def fill_chapter_names(book_dir: Path) -> bool:
    """地图缺章名段时，用块文件名机械补上。没有地图则不动。"""
    book_dir = Path(book_dir)
    mp = book_dir / MAP_FILE
    if not mp.is_file():
        return False
    try:
        text = mp.read_text(encoding="utf-8")
    except OSError:
        return False
    parsed = parse_map(text)
    if parsed.get("chapters"):
        return False
    names = [
        _block_name(p)
        for p in sorted(book_dir.glob("*.md"))
        if p.name not in SKIP_FILES and not is_nav_name(p.name)
    ]
    if not names:
        return False
    block = "## 章名\n" + "\n".join(f"- {n}" for n in names) + "\n"
    body = text.rstrip() + "\n\n" + block
    mp.write_text(body, encoding="utf-8")
    return True


def _ensure() -> sqlite3.Connection:
    global _con, _root
    with _lock:
        root = str(dirs()["root"])
        if _con is not None and _root != root:
            invalidate()
        if _con is not None:
            return _con
        _vectors.clear()
        _vec_meta.clear()
        pending_vec: list[tuple[str, str]] = []
        con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute(
        "CREATE VIRTUAL TABLE docs USING fts5("
        "ident UNINDEXED, book_id UNINDEXED, kind UNINDEXED, label UNINDEXED, "
        "title, name, aliases, body)"
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
            dead = book_is_dead(guide.parent)
            alias_src = ""
            map_raw = ""
            parsed: dict | None = None
            mp = guide.parent / MAP_FILE
            if mp.is_file():
                try:
                    map_raw = mp.read_text(encoding="utf-8")
                except OSError:
                    map_raw = ""
                if map_raw:
                    parsed = parse_map(map_raw)
                    alias_src = " ".join(
                        (parsed.get("chapters") or [])
                        + (parsed.get("alias_lefts") or [])
                        + (parsed.get("topics") or [])
                    )
            for p in sorted(guide.parent.glob("*.md")):
                if p.name in SKIP_FILES:
                    continue
                try:
                    raw = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                name = _block_name(p)
                nav = is_nav_name(p.name)
                shell = is_shell_text(raw)
                body = "" if nav or shell else raw
                name_ix = "" if nav or shell else name
                title_ix = "" if dead else title
                alias_ix = "" if nav or shell else alias_src
                ident = f"书/{slug}/{name}"
                con.execute(
                    "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        slug,
                        "书",
                        name,
                        tokenize_index(title_ix),
                        tokenize_index(name_ix),
                        tokenize_index(alias_ix),
                        tokenize_index(body),
                    ),
                )
                if not nav and not shell and not _embed_off():
                    vtext = "\n".join(
                        (
                            title_ix,
                            name,
                            _map_bits_for(ident, parsed),
                            (body or "")[:2000],
                        )
                    )
                    pending_vec.append((ident, vtext))
                    _vec_meta[ident] = (slug, "书", name)
            if parsed is not None and map_raw:
                blob = map_index_text(map_raw)
                suggest = " ".join(parsed.get("suggest") or [])
                con.execute(
                    "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?)",
                    (
                        f"书/{slug}",
                        slug,
                        "地图",
                        suggest,
                        tokenize_index(title),
                        tokenize_index(suggest),
                        tokenize_index(alias_src),
                        tokenize_index(blob),
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
                "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?)",
                (
                    ident,
                    p.stem,
                    "笔记",
                    note_title,
                    tokenize_index(note_title),
                    tokenize_index(note_title),
                    "",
                    tokenize_index(raw),
                ),
            )
            if not _embed_off():
                pending_vec.append((ident, f"{note_title}\n{raw[:2000]}"))
                _vec_meta[ident] = (p.stem, "笔记", note_title)
    if pending_vec and not _embed_off():
        _fill_vectors(pending_vec)
    _con = con
    _root = str(dirs()["root"])
    return con


def _df(con: sqlite3.Connection, piece: str, kind: str | None = None) -> int:
    expr = _fts_piece(piece)
    with _lock:
        try:
            if kind:
                row = con.execute(
                    "SELECT count(*) FROM docs WHERE kind = ? AND docs MATCH ?",
                    (kind, expr),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT count(*) FROM docs WHERE docs MATCH ?", (expr,)
                ).fetchone()
            return int(row[0] if row else 0)
        except sqlite3.OperationalError:
            return 0


def _match_gate(
    con: sqlite3.Connection, q: str, kind: str | None = None
) -> tuple[str, str, list[str]] | None:
    parts = evidence_pieces(q)
    expr = query_match(q)
    if not expr:
        return None
    real = _real_pieces(_base_pieces(q))
    if real:
        dfs = [(p, _df(con, p, kind)) for p in real]
        if any(d == 0 and re.fullmatch(r"[A-Za-z0-9_]+", p) for p, d in dfs):
            return None
        dfs = [(p, d) for p, d in dfs if d > 0]
        if not dfs:
            return None
        long = [
            p
            for p, d in dfs
            if d > 0 and (len(p) >= 3 or re.fullmatch(r"[A-Za-z0-9_]{3,}", p))
        ]
        extra = [p for p in parts if p not in (_base_pieces(q) or [])]
        gate_bits = list(long) + [p for p in extra if p not in long]
        gate = " OR ".join(_fts_piece(p) for p in gate_bits) if gate_bits else expr
    else:
        gate = expr
    return expr, gate, parts


def search_index(q: str) -> list[dict]:
    with _lock:
        return _search_index_locked(q)


def _search_index_locked(q: str) -> list[dict]:
    con = _ensure()
    gated = _match_gate(con, q)
    if not gated:
        return []
    expr, gate, parts = gated
    try:
        rows = con.execute(
            "SELECT ident, book_id, kind, label, bm25(docs, 4.0, 3.0, 3.0, 1.0) FROM docs "
            "WHERE kind != '地图' AND docs MATCH ? AND docs MATCH ? "
            "ORDER BY bm25(docs, 4.0, 3.0, 3.0, 1.0)",
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
        why = [
            p
            for p in parts
            if p and p in (q or "") and (p in ident or p in (label or ""))
        ][:3]
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
    boost_bits = [p for p in parts if len(p) >= 2]
    titles: dict[str, str] = {}
    for h in out:
        bid = str(h["book_id"])
        if bid not in titles:
            titles[bid] = _guide_title(bid)
    out.sort(
        key=lambda h: (
            0
            if any(
                p in (h.get("name") or "") and p not in titles.get(str(h["book_id"]), "")
                for p in boost_bits
            )
            else 1,
            h["score"],
        )
    )
    per: dict[str, int] = {}
    mixed: list[dict] = []
    for h in out:
        bid = str(h.get("book_id") or "")
        n = per.get(bid, 0)
        if n >= 8:
            continue
        per[bid] = n + 1
        mixed.append(h)
        if len(mixed) >= CANDIDATE_LIMIT:
            break
    return mixed or out[:CANDIDATE_LIMIT]


def _guide_title(slug: str) -> str:
    p = dirs()["books"] / slug / "导读.md"
    if not p.is_file():
        return ""
    try:
        m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return m.group(1).strip().strip("\"'") if m else ""


def latin_blocked(q: str) -> bool:
    parts = parse_query(q)
    with _lock:
        con = _ensure()
        return any(
            re.fullmatch(r"[A-Za-z0-9_]+", p) and _df(con, p) == 0 for p in parts
        )


def search_maps(q: str) -> list[dict]:
    if latin_blocked(q):
        return []
    with _lock:
        return _search_maps_locked(q)


def _search_maps_locked(q: str) -> list[dict]:
    con = _ensure()
    gated = _match_gate(con, q, "地图")
    if not gated:
        return []
    expr, gate, parts = gated
    try:
        rows = con.execute(
            "SELECT ident, book_id, bm25(docs, 4.0, 3.0, 3.0, 1.0) FROM docs "
            "WHERE kind = '地图' AND docs MATCH ? AND docs MATCH ? "
            "ORDER BY bm25(docs, 4.0, 3.0, 3.0, 1.0)",
            (expr, gate),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ident, book_id, score in rows:
        if ident in seen:
            continue
        seen.add(ident)
        suggest, why = [], []
        mp = dirs()["books"] / str(book_id) / MAP_FILE
        if mp.is_file():
            try:
                raw = mp.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            parsed = parse_map(raw)
            suggest = [s for s in (parsed.get("suggest") or []) if s]
            blob = map_index_text(raw)
            why = [p for p in parts if p and p in blob][:4]
        out.append(
            {
                "ident": f"书/{book_id}",
                "book_id": book_id,
                "kind": "书",
                "suggest": suggest,
                "why": why,
                "score": score,
            }
        )
    return out


def search_vectors(q: str) -> list[dict]:
    if _embed_off() or latin_blocked(q):
        return []
    with _lock:
        _ensure()
        if not _vectors:
            return []
        qv = _embed([q])[0]
        scored: list[tuple[float, str]] = []
        for ident, vec in _vectors.items():
            scored.append((sum(a * b for a, b in zip(qv, vec)), ident))
        scored.sort(key=lambda x: -x[0])
        out: list[dict] = []
        for dot, ident in scored[:CANDIDATE_LIMIT]:
            book_id, kind, label = _vec_meta.get(ident, ("", "书", ident.rsplit("/", 1)[-1]))
            out.append(
                {
                    "ident": ident,
                    "book_id": book_id,
                    "kind": kind,
                    "title": label,
                    "name": label,
                    "score": -float(dot),
                    "why": [],
                }
            )
        return out
