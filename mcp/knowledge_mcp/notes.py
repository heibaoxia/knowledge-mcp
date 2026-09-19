"""Write notes (search-before-write) and lint (block 4)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from knowledge_mcp.errors import fail
from knowledge_mcp.index import (
    MAP_FILE,
    ident_exists,
    invalidate,
    map_problems,
    map_thin,
)
from knowledge_mcp.ingest import book_health, slugify, uniquify, withdraw_book
from knowledge_mcp.log import guarded, log_call, read_calls
from knowledge_mcp.paths import dirs
from knowledge_mcp.retrieve import _ident_of, _parse_target, _split_part, search, split_frontmatter

VERDICTS = ("相符", "部分不符", "库中无", "非事实")
WINDOW_CALLS = 100
WINDOW_SECONDS = 24 * 3600


def _fields(md: str) -> tuple[str, str, dict, str]:
    meta, rest = split_frontmatter(md)
    title = str(meta.get("title") or "")
    intro = str(meta.get("intro") or "")
    if not title:
        for line in rest.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    if not intro:
        for line in rest.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                intro = s[:80]
                break
    return title, intro, meta if isinstance(meta, dict) else {}, rest


def _similar(title: str, intro: str) -> str:
    q = " ".join(x for x in (title, intro) if x).strip()
    if not q:
        return "路标：没有像的。先补标题和几句介绍再搜。\n"
    return search(q)


def _key(md: str) -> str:
    """同一份稿 = 标题 + 介绍 + 正文；verify/sources 不算改稿。"""
    title, intro, _meta, rest = _fields(md)
    return hashlib.sha1(f"{title}\n{intro}\n{rest}".encode("utf-8")).hexdigest()


def _previewed(key: str) -> bool:
    for rec in reversed(read_calls()):
        if (
            rec.get("door") == "kb_write_note"
            and rec.get("action") == "preview"
            and rec.get("key") == key
        ):
            return True
    return False


def _verified(key: str) -> bool:
    for rec in reversed(read_calls()):
        if (
            rec.get("door") == "kb_write_note"
            and rec.get("action") == "verify"
            and rec.get("key") == key
        ):
            return True
    return False


def _sources(meta: dict) -> list[str]:
    raw = meta.get("sources")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]


def _exists(ident: str) -> bool:
    """身份在盘上存在吗？对标 _read_book 的匹配，只查不读（不调 kb_read）。"""
    t = (ident or "").replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    if t.startswith("笔记/"):
        return (dirs()["notes"] / f"{Path(t[3:]).stem}.md").is_file()
    if not t.startswith("书/"):
        return False
    bits = t[2:].split("/")
    part = "/".join(bits[1:])
    book = dirs()["books"] / bits[0]
    if not part or not book.is_dir():
        return False
    if part in ("导读", "导读.md"):
        return (book / "导读.md").is_file()
    for p in sorted(book.glob("*.md")):
        if p.name == "导读.md":
            continue
        with p.open(encoding="utf-8") as f:
            first = f.readline()
        if part in p.name or part in p.stem or part in first:
            return True
    return False


def _base_ident(ident: str) -> str:
    """剥掉 #n / @偏移，只留章。#1 与不带 # 等价。"""
    kind, slug, extra = _parse_target(ident or "")
    if kind == "书" and slug and extra:
        name, _win, _sec, _off = _split_part(extra)
        return f"书/{slug}/{name}"
    if kind == "笔记" and slug:
        return f"笔记/{slug}"
    return (ident or "").replace("\\", "/").strip()


def _read_recent(ident: str) -> bool:
    """最近 100 条或 24 小时内成功 kb_read 过这个身份吗（先到为准）。"""
    want = _base_ident(ident)
    now = datetime.now(timezone.utc)
    for i, rec in enumerate(reversed(read_calls())):
        if i >= WINDOW_CALLS:
            return False
        try:
            age = (now - datetime.fromisoformat(str(rec.get("ts")))).total_seconds()
        except (TypeError, ValueError):
            return False
        if age > WINDOW_SECONDS:
            return False
        if rec.get("door") == "kb_read" and rec.get("ok") is True:
            got = _ident_of(str(rec.get("target") or ""), rec.get("part"))
            if _base_ident(got) == want:
                return True
    return False


def _gate(md: str) -> str | None:
    """求证闸门：不符就交 fail() 手递，合格返回 None。"""
    title, intro, meta, rest = _fields(md)
    verdict = str(meta.get("verify") or "").strip()
    if verdict not in VERDICTS:
        return fail(
            "写笔记-求证",
            "稿上要写 verify：相符 / 部分不符 / 库中无 / 非事实。",
            "无",
            "在 YAML 抬头补上四选一，再 action=verify。",
        )
    sources = _sources(meta)
    if verdict in ("相符", "部分不符"):
        if not sources:
            return fail(
                "写笔记-求证",
                f"标了「{verdict}」却没列 sources。",
                "无",
                "先 kb_read 依据，把身份写进 sources 再 verify。",
            )
        for ident in sources:
            if not _exists(ident):
                return fail(
                    "写笔记-求证",
                    f"来源身份不存在：{ident}。",
                    "无",
                    "用检索路标上的规范身份，不要编。",
                )
            if not _read_recent(ident):
                return fail(
                    "写笔记-求证",
                    f"没读过就写「{verdict}」：{ident}。",
                    "无",
                    "先用 kb_read 读这个身份，再 action=verify。",
                )
        return None
    if verdict == "库中无":
        if "根据《" in (title + intro + rest):
            return fail(
                "写笔记-求证",
                "标了「库中无」却在稿里写「根据《…》」。",
                "无",
                "拿掉根据句；或先读依据，改标相符 / 部分不符。",
            )
        return None
    for ident in sources:
        if not _exists(ident):
            return fail(
                "写笔记-求证",
                f"来源身份不存在：{ident}。",
                "无",
                "用检索路标上的规范身份，或删掉 sources。",
            )
    return None


def _is_book_target(target: str | None) -> bool:
    if not target:
        return False
    t = target.replace("\\", "/")
    return t.startswith("书/") or "/书/" in t or t.startswith("资料/书")


HEAD_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)
HEAD_PUNCT = re.compile(r"[《》「」\"'：:、．.\s]+")
MAP_HEADS = {"能解决什么", "别名", "依据块", "不解决什么", "章名", "建议从哪读"}


def _norm_heading(s: str) -> str:
    return HEAD_PUNCT.sub("", s or "")


def _split_sections(md: str) -> tuple[str, list[tuple[str, str, str]]]:
    matches = list(HEAD_RE.finditer(md or ""))
    if not matches:
        return md or "", []
    prefix = md[: matches[0].start()]
    secs: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        secs.append((m.group(1), m.group(2).strip(), md[m.end() : end]))
    return prefix, secs


def _conflict_report(rest: str) -> str:
    _prefix, secs = _split_sections(rest or "")
    keys = {_norm_heading(h) for _hs, h, _b in secs if _norm_heading(h)}
    if not keys:
        return ""
    notes = dirs()["notes"]
    if not notes.is_dir():
        return ""
    lines: list[str] = []
    for p in sorted(notes.glob("*.md")):
        _op, osecs = _split_sections(p.read_text(encoding="utf-8"))
        hits = [oh for _hs, oh, _b in osecs if _norm_heading(oh) in keys]
        if hits:
            lines.append(f"- 笔记/{p.stem}：" + "、".join(f"## {h}" for h in hits))
    if not lines:
        return ""
    return "冲突段候选：\n" + "\n".join(lines) + "\n"


def _ensure_note_map(text: str, slug: str, title: str) -> str:
    if re.search(r"^##\s+能解决什么\s*$", text, re.M):
        return text
    _prefix, secs = _split_sections(text)
    heads = [h[:40] for _hs, h, _b in secs if h not in MAP_HEADS][:3]
    solves = heads or [((title or "本条笔记")[:40])]
    ident = f"笔记/{slug}"
    extra = (
        "\n## 能解决什么\n"
        + "\n".join(f"- {s}" for s in solves)
        + "\n\n## 别名\n\n## 依据块\n"
        + "\n".join(f"- {s} → {ident}" for s in solves)
        + "\n"
    )
    return text.rstrip() + "\n" + extra


def _find_same_title_plain(title: str) -> Path | None:
    want = _norm_heading(title)
    if not want:
        return None
    notes = dirs()["notes"]
    if not notes.is_dir():
        return None
    for p in sorted(notes.glob("*.md")):
        old_title, _intro, _meta, rest = _fields(p.read_text(encoding="utf-8"))
        if _norm_heading(old_title) != want:
            continue
        if HEAD_RE.search(rest or ""):
            continue
        return p
    return None


def _overlay_others(skip_stem: str, new_text: str, new_ident: str) -> list[str]:
    _prefix, secs = _split_sections(new_text)
    new_secs = {
        _norm_heading(h): body for _hs, h, body in secs if _norm_heading(h)
    }
    if not new_secs:
        return []
    notes = dirs()["notes"]
    if not notes.is_dir():
        return []
    done: list[str] = []
    for p in sorted(notes.glob("*.md")):
        if p.stem == skip_stem:
            continue
        old = p.read_text(encoding="utf-8")
        opx, osecs = _split_sections(old)
        if not osecs:
            continue
        changed = False
        rebuilt = opx
        for hashes, heading, body in osecs:
            key = _norm_heading(heading)
            rebuilt += f"{hashes} {heading}"
            if key and key in new_secs:
                nb = new_secs[key].lstrip("\n")
                rebuilt += f"\n> 已被 {new_ident} 覆盖\n{nb}"
                if not nb.endswith("\n"):
                    rebuilt += "\n"
                changed = True
            else:
                rebuilt += body if body.startswith("\n") else "\n" + body
        if changed:
            p.write_text(rebuilt, encoding="utf-8")
            done.append(f"笔记/{p.stem}")
    return done


def _render(title: str, intro: str, meta: dict, rest: str) -> str:
    head = dict(meta)
    head["title"] = title
    head["type"] = "笔记"
    head["intro"] = intro
    head.setdefault("tags", [])
    head["generated"] = True
    body = rest if rest.strip() else f"# {title}\n\n{intro}\n"
    return (
        "---\n"
        + yaml.safe_dump(head, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + body.lstrip("\n")
    )


@guarded("kb_write_note")
def write_note(markdown: str, action: str = "preview", target: str | None = None) -> str:
    md = markdown or ""
    action = (action or "preview").strip().lower()
    key = _key(md)
    title, intro, meta, rest = _fields(md)
    sim = _similar(title, intro)

    if action in ("preview", "search"):
        log_call("kb_write_note", True, action="preview", key=key)
        conflicts = _conflict_report(rest)
        extra = ("\n" + conflicts) if conflicts else ""
        return (
            "写笔记预览（还没写入）\n"
            f"标题：{title or '（缺）'}\n"
            "先看类似条目；然后 action=verify 写清 verify（相符 / 部分不符 / 库中无 / 非事实）和 sources，再 action=create 新建，或 action=update 并指定 笔记/<slug>。\n\n"
            + sim
            + extra
        )

    if _is_book_target(target):
        out = fail(
            "写笔记",
            "只能进 资料/笔记/，动不了书。",
            "无",
            "新建不要填书的身份；改旧条用 笔记/<slug>。",
        )
        log_call("kb_write_note", False, action=action, step="护书")
        return out

    if action == "verify":
        out = _gate(md)
        if out:
            log_call("kb_write_note", False, action="verify", key=key, step="求证")
            return out
        log_call("kb_write_note", True, action="verify", key=key)
        return (
            "已求证（还没写入）\n"
            f"结论：{str(meta.get('verify') or '').strip()}\n"
            f"标题：{title or '（缺）'}\n"
            "同一份稿（标题+介绍+正文）可以直接 create 或 update；改了正文要重走 preview 和 verify。\n"
        )

    if not _previewed(key):
        out = fail(
            "写笔记-先搜",
            "不先看类似条目就新建，不允许。",
            "无",
            "先用同一门 action=preview，看完再 verify、create 或 update。",
        )
        log_call("kb_write_note", False, action=action, step="先搜")
        return out + "\n" + sim

    if not _verified(key):
        out = fail(
            "写笔记-求证",
            "不先求证就写入，不允许。",
            "无",
            "对同一份稿先 action=verify，稿上写 verify：相符 / 部分不符 / 库中无 / 非事实。",
        )
        log_call("kb_write_note", False, action=action, step="求证")
        return out

    if not title or not intro:
        out = fail(
            "写笔记-抬头",
            "笔记要有标题和几句介绍，否则以后检索扫不到。",
            "无",
            "补上 YAML 头或 # 标题加一段介绍，再 preview → verify → create。",
        )
        log_call("kb_write_note", False, action=action, step="抬头")
        return out

    out = _gate(md)
    if out:
        log_call("kb_write_note", False, action=action, key=key, step="求证")
        return out

    if action == "create":
        notes = dirs()["notes"]
        notes.mkdir(parents=True, exist_ok=True)
        twin = _find_same_title_plain(title)
        if twin is not None:
            path = twin
            wrote = "已更新"
        else:
            base = slugify(title) or ("n-" + key[:8])
            path = uniquify(notes / f"{base}.md")
            wrote = "已记下"
        ident = f"笔记/{path.stem}"
        text = _ensure_note_map(_render(title, intro, meta, rest), path.stem, title)
        path.write_text(text, encoding="utf-8")
        covered = _overlay_others(path.stem, text, ident)
        invalidate()
        out = f"{wrote}\n身份：{ident}\n路径：资料/笔记/{path.name}\n"
        if covered:
            out += "覆盖：" + "、".join(covered) + "\n"
        out += NOTE_RETRIEVE_HINT
        log_call("kb_write_note", True, action="create", ident=ident)
        return out

    if action == "update":
        ident = (target or "").replace("\\", "/").strip()
        if ident.startswith("资料/"):
            ident = ident[len("资料/") :]
        if not ident.startswith("笔记/"):
            out = fail(
                "写笔记-更新",
                "更新必须点名 笔记/<slug>。",
                "无",
                "先 preview 看类似条目，再带 target=笔记/<slug>。",
            )
            log_call("kb_write_note", False, action="update", step="点名")
            return out
        slug = Path(ident[3:]).stem
        path = dirs()["notes"] / f"{slug}.md"
        if not path.is_file():
            out = fail(
                "写笔记-更新",
                f"没有这条笔记：{slug}。",
                "无",
                "对照路标身份再更新，或改用 create。",
            )
            log_call("kb_write_note", False, action="update", step="点名")
            return out
        note_ident = f"笔记/{slug}"
        text = _ensure_note_map(_render(title, intro, meta, rest), slug, title)
        path.write_text(text, encoding="utf-8")
        covered = _overlay_others(slug, text, note_ident)
        invalidate()
        out = f"已更新\n身份：{note_ident}\n"
        if covered:
            out += "覆盖：" + "、".join(covered) + "\n"
        out += NOTE_RETRIEVE_HINT
        log_call("kb_write_note", True, action="update", ident=note_ident)
        return out

    out = fail(
        "写笔记",
        f"不认识的 action：{action}。",
        "无",
        "用 preview / verify / create / update。",
    )
    log_call("kb_write_note", False, action=action)
    return out


SHORT_BODY = 40
GLYPH_HINTS = (("癿", "的"), ("丌", "不"))
GLYPH_MIN = 3
FIND_CAP = 80
NOTE_RETRIEVE_HINT = (
    "检索与书同一套：kb_search 只回路标，kb_read 点名 笔记/<slug>。\n"
    "入库多一步求证（书没有）。短地图已写在文末；俗称写进 ## 别名。\n"
)


def _note_path(ident: str) -> Path | None:
    t = ident.replace("\\", "/").strip()
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    if t.startswith("笔记/"):
        return dirs()["notes"] / f"{Path(t[3:]).stem}.md"
    return None


def _map_path(ident: str) -> Path | None:
    t = ident.replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    bits = t.split("/")
    if len(bits) == 3 and bits[0] == "书" and bits[2] in ("地图", MAP_FILE):
        return dirs()["books"] / bits[1] / MAP_FILE
    return None


def _book_slug(ident: str) -> str | None:
    t = ident.replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    bits = [b for b in t.split("/") if b]
    if len(bits) == 2 and bits[0] == "书" and bits[1]:
        return bits[1]
    return None


def _touches_book(raw: str) -> bool:
    if _map_path(raw):
        return False
    if _is_book_target(raw):
        return True
    p = Path(raw)
    try:
        resolved = p.resolve()
        books = dirs()["books"].resolve()
        if resolved == books or books in resolved.parents:
            return True
    except OSError:
        pass
    return False


def _targets_of(item: dict) -> list[str]:
    out = []
    if item.get("target"):
        out.append(str(item["target"]))
    if item.get("into"):
        out.append(str(item["into"]))
    for t in item.get("targets") or []:
        out.append(str(t))
    return out


def _chapter_file(ident: str) -> Path | None:
    t = (ident or "").replace("\\", "/").strip().strip("/")
    if t.startswith("资料/"):
        t = t[len("资料/") :]
    if not t.startswith("书/"):
        return None
    bits = t[2:].split("/")
    slug, part = bits[0], "/".join(bits[1:])
    book = dirs()["books"] / slug
    if not part or not book.is_dir():
        return None
    if part in ("导读", "导读.md"):
        p = book / "导读.md"
        return p if p.is_file() else None
    if part in ("地图", MAP_FILE):
        p = book / MAP_FILE
        return p if p.is_file() else None
    for p in sorted(book.glob("*.md")):
        if p.name in ("导读.md", MAP_FILE):
            continue
        with p.open(encoding="utf-8") as f:
            first = f.readline()
        if part in p.name or part in p.stem or part in first:
            return p
    return None


def _replace_files(target: str) -> list[Path] | None:
    slug = _book_slug(target)
    if slug:
        d = dirs()["books"] / slug
        if not d.is_dir():
            return None
        return sorted(p for p in d.glob("*.md") if p.is_file())
    note = _note_path(target)
    if note is not None:
        return [note] if note.is_file() else None
    ch = _chapter_file(target)
    if ch is not None:
        return [ch]
    return None


def _scan() -> str:
    notes_dir = dirs()["notes"]
    files = sorted(notes_dir.glob("*.md")) if notes_dir.is_dir() else []
    flags: list[str] = []
    shelf: list[str] = []
    titles: dict[str, list[str]] = {}
    for p in files:
        text = p.read_text(encoding="utf-8")
        meta, rest = split_frontmatter(text)
        ident = f"笔记/{p.stem}"
        title = str(meta.get("title") or "")
        intro = str(meta.get("intro") or "")
        reasons = []
        if not meta:
            reasons.append("没抬头")
        if not title or not intro:
            reasons.append("缺标题或介绍")
        if len(rest.strip()) < SHORT_BODY:
            reasons.append("太短")
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if meta.get("status") in ("stale", "过期") or "过期" in [str(t) for t in tags]:
            reasons.append("已标过期")
        sources = meta.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        for s in sources:
            s = str(s).strip()
            if s and not ident_exists(s):
                reasons.append(f"sources 死链 {s}")
        if title:
            titles.setdefault(title, []).append(ident)
        shelf.append(f"- 《{title or p.stem}》 身份：{ident}")
        if reasons:
            flags.append(f"- {ident} 《{title or p.stem}》：{'；'.join(reasons)}")
    for title, ids in titles.items():
        if len(ids) > 1:
            flags.append(f"- {', '.join(ids)} 《{title}》：标题重复")
    n_books = 0
    books = dirs()["books"]
    if books.is_dir():
        for guide in sorted(books.glob("*/导读.md")):
            d = guide.parent
            n_books += 1
            ident = f"书/{d.name}/地图"
            unfinished: list[str] = []
            mp = d / MAP_FILE
            if not mp.is_file():
                flags.append(f"- {ident}：缺地图")
                unfinished.append("缺地图")
            else:
                for prob in map_problems(d):
                    flags.append(f"- {ident}：{prob}")
                    unfinished.append(prob)
                if map_thin(d):
                    flags.append(f"- {ident}：未入完 骨架未加厚")
                    unfinished.append("骨架未加厚")
                blocks = [p for p in d.glob("*.md") if p.name not in ("导读.md", MAP_FILE)]
                if blocks and mp.stat().st_mtime < max(p.stat().st_mtime for p in blocks):
                    flags.append(f"- {ident}：早于重切")
                    unfinished.append("早于重切")
            try:
                gmeta, _ = split_frontmatter(guide.read_text(encoding="utf-8"))
            except OSError:
                gmeta = {}
            title = str((gmeta or {}).get("title") or d.name)
            for reason in book_health(d):
                flags.append(f"- 书/{d.name}：《{title}》：{reason}")
                unfinished.append(reason)
            for p in d.glob("*.md"):
                if p.name in ("导读.md", MAP_FILE):
                    continue
                try:
                    body = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                for bad, good in GLYPH_HINTS:
                    n = body.count(bad)
                    if n >= GLYPH_MIN:
                        flags.append(
                            f"- 书/{d.name}/{p.stem}：字形可疑 {bad}×{n}，"
                            f"若实为「{good}」用 replace find={bad} repl={good}"
                        )
            nblocks = sum(
                1
                for p in d.glob("*.md")
                if p.name not in ("导读.md", MAP_FILE)
            )
            status = "入完" if not unfinished else "未入完：" + "；".join(unfinished)
            shelf.append(
                f"- 《{title}》 身份：书/{d.name}  块 {nblocks}  {status}"
            )
    head = (
        f"在架\n书 {n_books} 本，笔记 {len(files)} 条\n"
        + ("\n".join(shelf) + "\n" if shelf else "（空）\n")
    )
    if not flags:
        out = head + "\n问题\n没有可疑项。\n"
    else:
        out = (
            head
            + "\n问题\n"
            + "\n".join(flags)
            + "\n动手请 action=apply 提交 JSON 清单。"
            "笔记 delete/update/merge；地图 update/stale；"
            "replace 改错字；"
            '退整本 {"op":"withdraw","target":"书/<slug>"}。不能退某一章。\n'
        )
    log_call("kb_lint_notes", True, action="scan", n=len(flags))
    return out


def _apply(plan_text: str) -> str:
    if not (plan_text or "").strip():
        out = fail(
            "净化-动手",
            "没有处理清单。",
            "无",
            "先 scan，再交 JSON：[{op, target, ...}]。",
        )
        log_call("kb_lint_notes", False, action="apply", step="清单")
        return out
    try:
        plan = json.loads(plan_text)
    except json.JSONDecodeError as e:
        out = fail("净化-动手", f"清单不是 JSON：{e}", "无", "改成 JSON 数组再交。")
        log_call("kb_lint_notes", False, action="apply", step="清单")
        return out
    if not isinstance(plan, list) or not plan:
        out = fail("净化-动手", "清单要是非空数组。", "无", "先 scan 再交要动的那几条。")
        log_call("kb_lint_notes", False, action="apply", step="清单")
        return out
    for item in plan:
        if not isinstance(item, dict):
            out = fail("净化-动手", "清单项必须是对象。", "库不变", "改 JSON。")
            log_call("kb_lint_notes", False, action="apply", step="清单")
            return out
        op = str(item.get("op") or "").lower()
        if op == "withdraw":
            slug = _book_slug(str(item.get("target") or ""))
            if slug is None:
                out = fail(
                    "净化-动手",
                    "退书只许 书/<slug>。整单拒绝。",
                    "库不变",
                    '用 {"op":"withdraw","target":"书/<slug>"}，不能退某一章。',
                )
                log_call("kb_lint_notes", False, action="apply", step="退书")
                return out
            if not (dirs()["books"] / slug).is_dir():
                out = fail(
                    "净化-动手",
                    f"没有这本书：{slug}。整单拒绝。",
                    "库不变",
                    "对照 scan 清单上的 书/<slug> 再交。",
                )
                log_call("kb_lint_notes", False, action="apply", step="退书")
                return out
            continue
        if op == "replace":
            find = str(item.get("find") or "")
            repl = item.get("repl")
            repl = "" if repl is None else str(repl)
            if not find or find == repl or len(find) > FIND_CAP:
                out = fail(
                    "净化-动手",
                    "replace 要有非空 find、不等于 repl、长度不超过 80。",
                    "库不变",
                    '{"op":"replace","target":"书/<slug>","find":"癿","repl":"的"}',
                )
                log_call("kb_lint_notes", False, action="apply", step="replace")
                return out
            if _replace_files(str(item.get("target") or "")) is None:
                out = fail(
                    "净化-动手",
                    f"replace 找不到目标：{item.get('target')}。",
                    "库不变",
                    "点名 书/<slug>、书/<slug>/<章> 或 笔记/<slug>。",
                )
                log_call("kb_lint_notes", False, action="apply", step="replace")
                return out
            continue
        for raw in _targets_of(item):
            if _touches_book(raw):
                out = fail(
                    "净化-动手",
                    "清单碰到书，整单拒绝。",
                    "库不变",
                    "从清单里拿掉书正文，只处理笔记和地图。退整本用 withdraw。改错字用 replace。",
                )
                log_call("kb_lint_notes", False, action="apply", step="护书")
                return out
            if _note_path(raw) is None and _map_path(raw) is None:
                out = fail(
                    "净化-动手",
                    f"身份不是笔记或地图：{raw}。整单拒绝。",
                    "库不变",
                    "只许 笔记/<slug> 或 书/<slug>/地图。退整本用 withdraw。改错字用 replace。",
                )
                log_call("kb_lint_notes", False, action="apply", step="护书")
                return out
        is_map = _map_path(str(item.get("target") or item.get("into") or "")) is not None
        allowed = ("update", "stale") if is_map else ("delete", "update", "merge")
        if op not in allowed:
            out = fail(
                "净化-动手",
                f"不认识的 op：{op}。整单拒绝。",
                "库不变",
                "笔记 delete/update/merge；地图 update/stale；replace 改错字；整本 withdraw。",
            )
            log_call("kb_lint_notes", False, action="apply", step="op")
            return out
    for item in plan:
        if str(item.get("op") or "").lower() != "update":
            continue
        mp = _map_path(str(item.get("target") or ""))
        if mp is None:
            continue
        md = str(item.get("markdown") or "")
        old = mp.read_text(encoding="utf-8") if mp.is_file() else None
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(md, encoding="utf-8")
        probs = map_problems(mp.parent)
        if old is None:
            mp.unlink(missing_ok=True)
        else:
            mp.write_text(old, encoding="utf-8")
        if probs:
            out = fail(
                "净化-动手",
                "地图不合格：" + "；".join(probs),
                "库不变",
                "先改到身份都存在再 apply。",
            )
            log_call("kb_lint_notes", False, action="apply", step="地图")
            return out
    done: list[str] = []
    for item in plan:
        op = str(item.get("op") or "").lower()
        if op == "withdraw":
            slug = _book_slug(str(item.get("target") or "")) or ""
            try:
                info = withdraw_book(slug)
            except ValueError as e:
                out = fail("净化-动手", str(e), "库不变", "对照 scan 清单再交。")
                log_call("kb_lint_notes", False, action="apply", step="退书")
                return out
            src = info["source"] or "导读未写 source"
            done.append(
                f"已退 书/{info['slug']} 《{info['title']}》；源文件仍在 {src}。要再入走指定入库。"
            )
        elif op == "delete":
            path = _note_path(str(item.get("target") or ""))
            if path and path.is_file():
                path.unlink()
                invalidate()
                done.append(f"删 笔记/{path.stem}")
        elif op == "stale":
            mp = _map_path(str(item.get("target") or ""))
            if mp and mp.is_file():
                meta, rest = split_frontmatter(mp.read_text(encoding="utf-8"))
                meta["stale"] = True
                mp.write_text(
                    "---\n"
                    + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                    + "---\n\n"
                    + rest,
                    encoding="utf-8",
                )
                invalidate()
                done.append(f"标过期 书/{mp.parent.name}/地图")
        elif op == "update":
            mp = _map_path(str(item.get("target") or ""))
            if mp is not None:
                md = str(item.get("markdown") or "")
                old = mp.read_text(encoding="utf-8") if mp.is_file() else None
                mp.parent.mkdir(parents=True, exist_ok=True)
                mp.write_text(md, encoding="utf-8")
                probs = map_problems(mp.parent)
                if probs:
                    if old is None:
                        mp.unlink(missing_ok=True)
                    else:
                        mp.write_text(old, encoding="utf-8")
                    out = fail(
                        "净化-动手",
                        "地图不合格：" + "；".join(probs),
                        "库不变",
                        "先改到身份都存在再 apply。",
                    )
                    log_call("kb_lint_notes", False, action="apply", step="地图")
                    return out
                invalidate()
                done.append(f"改 书/{mp.parent.name}/地图")
                continue
            path = _note_path(str(item.get("target") or ""))
            md = item.get("markdown") or ""
            if path and md:
                path.write_text(str(md), encoding="utf-8")
                invalidate()
                done.append(f"改 笔记/{path.stem}")
        elif op == "replace":
            find = str(item.get("find") or "")
            repl = item.get("repl")
            repl = "" if repl is None else str(repl)
            paths = _replace_files(str(item.get("target") or "")) or []
            n = 0
            for p in paths:
                text = p.read_text(encoding="utf-8")
                c = text.count(find)
                if c:
                    p.write_text(text.replace(find, repl), encoding="utf-8")
                    n += c
            invalidate()
            done.append(f"替换 {item.get('target')} ×{n}")
        elif op == "merge":
            into = _note_path(str(item.get("into") or item.get("target") or ""))
            md = item.get("markdown") or ""
            if into is None:
                continue
            if md:
                into.parent.mkdir(parents=True, exist_ok=True)
                into.write_text(str(md), encoding="utf-8")
            for raw in item.get("targets") or []:
                other = _note_path(str(raw))
                if other and other.is_file() and other != into:
                    other.unlink()
            invalidate()
            done.append(f"合并 → 笔记/{into.stem}")
    out = "净化已执行\n" + "\n".join(f"- {x}" for x in done) + "\n"
    log_call("kb_lint_notes", True, action="apply", n=len(done))
    return out


@guarded("kb_lint_notes")
def lint_notes(action: str = "scan", plan: str | None = None) -> str:
    action = (action or "scan").strip().lower()
    if action == "scan":
        return _scan()
    if action == "apply":
        return _apply(plan or "")
    out = fail(
        "净化",
        f"不认识的 action：{action}。",
        "无",
        "先 scan 出清单，再 apply。",
    )
    log_call("kb_lint_notes", False, action=action)
    return out
