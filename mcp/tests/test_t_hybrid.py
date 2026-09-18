"""段 A 红测 T1–T9、T11–T12（本轮 Spec §7）。

只用假 slug / 假专名。夹具自备，不 import 别的测试模块。
断言只看身份 / 书名 / 栏名 / 建议块，正文 token 不许出现在路标里。
"""
from __future__ import annotations

from pathlib import Path

NO_MAP = "- 量子场论"

# 断栏名用：拼出来避免误伤「地图.md」这类词。
MAP_COL = "仅" + "地图"


def plant_book(
    kb: Path,
    slug: str,
    title: str,
    chapters: list[str],
    bodies: list[str],
    intro: str = "讲义。",
) -> Path:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True, exist_ok=True)
    toc = "\n".join(f"- {c}" for c in chapters)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: {intro}\ntags: []\n"
        f"source: 原始资料归档/{slug}.epub\n---\n\n# {title}\n\n{intro}\n\n## 目录\n{toc}\n",
        encoding="utf-8",
    )
    for i, (c, b) in enumerate(zip(chapters, bodies), 1):
        (d / f"{i:02d}-{c}.md").write_text(f"# {c}\n\n{b}\n", encoding="utf-8")
    return d


def plant_map(
    kb: Path,
    slug: str,
    title: str,
    chapter: str,
    solves: list[str] | None = None,
    not_solves: list[str] | None = None,
    guide: str | None = None,
    aliases: list[str] | None = None,
    chapter_names: list[str] | None = None,
    topics: list[str] | None = None,
) -> Path:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True, exist_ok=True)
    solves = solves if solves is not None else ["怎么问怎么答", "怎么起个头", "怎么收尾"]
    not_solves = not_solves if not_solves else [NO_MAP]
    guide = guide or f"书/{slug}/{chapter}"
    text = (
        f"---\ntitle: {title}\ntype: 地图\nbook: 书/{slug}\ngenerated: true\n---\n\n"
        "## 能解决什么\n"
        + "\n".join(f"- {s}" for s in solves)
        + "\n\n## 不解决什么\n"
        + "\n".join(f"- {s}" for s in not_solves)
        + f"\n\n## 建议从哪读\n- {guide}\n\n## 依据块\n"
        + "\n".join(f"- {s} → {guide}" for s in solves)
        + "\n"
    )
    if chapter_names:
        text += "\n## 章名\n" + "\n".join(f"- {c}" for c in chapter_names) + "\n"
    if aliases:
        text += "\n## 别名\n" + "\n".join(f"- {a}" for a in aliases) + "\n"
    if topics:
        text += "\n## 主题词\n" + "\n".join(f"- {t}" for t in topics) + "\n"
    (d / "地图.md").write_text(text, encoding="utf-8")
    return d


def _fresh() -> None:
    from knowledge_mcp.index import invalidate

    invalidate()


def _search(q: str) -> str:
    _fresh()
    from knowledge_mcp.retrieve import search

    return search(q)


def _mark(book: str) -> str:
    return f"身份：{book}"


def _suggest_ids(out: str) -> list[str]:
    return [ln.strip()[1:].strip() for ln in out.splitlines() if ln.strip().startswith("· ")]


def test_t1_chapter_name_beats_idle_body_change(kb):
    plant_book(kb, "hechao", "核潮讲义", ["核潮分层"], ["分层讲完就到此为止。"])
    plant_book(kb, "xianbian", "闲编纪事", ["卷一 杂记"], ["变化。" * 200])
    out = _search("核潮分层以后局势怎么变化")
    assert _mark("书/hechao") in out
    assert _mark("书/xianbian") not in out
    assert "到此为止" not in out


def test_t2_section_name_beats_idle_fasheng(kb):
    plant_book(
        kb,
        "chaoxun",
        "潮汛纪要",
        ["第一节 起汛", "第二节 潮汛"],
        ["起汛一章。", "第二节正文讲潮势高低。"],
    )
    plant_map(
        kb,
        "chaoxun",
        "潮汛纪要",
        "第二节 潮汛",
        solves=["潮汛是怎么收的", "起汛怎么记", "潮势高低怎么算"],
        chapter_names=["第一节 起汛", "第二节 潮汛"],
    )
    plant_book(kb, "xianfa", "闲法杂抄", ["卷一 杂抄"], ["发生。" * 200])
    plant_map(
        kb,
        "xianfa",
        "闲法杂抄",
        "卷一 杂抄",
        solves=["事故是怎么发生的", "杂抄怎么记", "旧账怎么翻"],
    )
    out = _search("潮汛是怎么发生的")
    assert _mark("书/chaoxun") in out
    pos_want = out.find(_mark("书/chaoxun"))
    pos_idle = out.find(_mark("书/xianfa"))
    assert pos_idle == -1 or pos_want < pos_idle


def test_t3_alias_hits_without_body_alias(kb):
    plant_book(kb, "beichuang", "北窗纪略", ["整风章"], ["整风以后，诸事重新排队。"])
    plant_map(
        kb,
        "beichuang",
        "北窗纪略",
        "整风章",
        chapter_names=["整风章"],
        aliases=["北窗事变 → 书/beichuang/整风章"],
    )
    out = _search("北窗事变以后呢")
    assert _mark("书/beichuang") in out
    assert "重新排队" not in out


def test_t4_latin_df0_empty(kb):
    """Quell 只在导航件「参考文献」里，不进索引，整句空。"""
    plant_book(
        kb,
        "quellref",
        "附录辑",
        ["参考文献"],
        ["Quell 的写法见这一条参考文献。"],
    )
    plant_book(kb, "osnotes", "系统笔记", ["内核章"], ["内核调度怎么写。"])
    out = _search("怎么用 Quell 写操作系统")
    assert _mark("书/quellref") not in out
    assert _mark("书/osnotes") not in out
    assert "没有像的" in out or "0" in out


def test_t5_chapter_beats_idle_footnote(kb):
    plant_book(kb, "jixian", "阶段论稿", ["人格阶段"], ["人格阶段分几步走。"])
    plant_book(
        kb,
        "sanjia",
        "三家杂录",
        ["卷一 杂录"],
        ["杂录若干。\n\n> 约·奎尔森发明热机。"],
    )
    out = _search("奎尔森讲的发展阶段")
    assert _mark("书/jixian") in out
    assert _mark("书/sanjia") not in out
    assert "分几步走" not in out


def test_t6_suggest_named_chapter_not_squeezed(kb):
    plant_book(
        kb,
        "sanjia",
        "三篇合编",
        ["甲论", "乙论", "丙析", "共同点摘记"],
        ["甲论正文。", "乙论正文。", "丙析正文。", "共同点摘记正文。"],
    )
    plant_map(
        kb,
        "sanjia",
        "三篇合编",
        "乙论",
        solves=["甲论讲了什么", "乙论讲了什么", "丙析讲了什么"],
        chapter_names=["甲论", "乙论", "丙析", "共同点摘记"],
    )
    out = _search("甲论乙论丙析有什么共同点")
    assert _mark("书/sanjia") in out
    sug = _suggest_ids(out)
    assert sug, f"没有建议块：\n{out}"
    assert any(s == "书/sanjia/乙论" for s in sug), f"乙论没占住建议块：{sug}"


def test_t7_two_books_same_chapter_both_allowed(kb):
    plant_book(kb, "yiyue-a", "一月潮甲记", ["一月潮"], ["一月潮是怎么起的，甲记有说法。"])
    plant_book(kb, "yiyue-b", "一月潮乙记", ["一月潮"], ["一月潮是怎么起的，乙记另有说法。"])
    out = _search("一月潮是怎么起来的")
    assert _mark("书/yiyue-a") in out
    assert _mark("书/yiyue-b") in out


def test_t8_scan_flags_thin_chapter_coverage(kb):
    names = ["甲论", "乙论", "丙析", "丁议", "戊评", "己述", "庚考", "辛记", "壬录", "癸引"]
    plant_book(kb, "thinmap", "薄图残卷", names, [f"{n}正文。" for n in names])
    plant_map(
        kb,
        "thinmap",
        "薄图残卷",
        "甲论",
        solves=["潮势高低怎么算", "旧账怎么翻", "杂事怎么记"],
    )
    d = kb / "资料" / "书" / "thinmap"
    from knowledge_mcp.index import map_problems
    from knowledge_mcp.notes import lint_notes

    scan = lint_notes("scan")
    probs = map_problems(d)
    flagged = "未入完" in scan or any("未入完" in p or "章名" in p for p in probs)
    assert flagged, f"scan 没标章名覆盖不足：\n{scan}\nproblems={probs}"


def test_t9_landmarks_no_body_column_is_semantic(kb):
    plant_book(kb, "hechao", "核潮讲义", ["卷一"], ["SECRET_T9_BODY 只在这里。"])
    plant_map(
        kb,
        "hechao",
        "核潮讲义",
        "卷一",
        solves=["夜里总睡不着该怎么办", "潮势怎么算", "分层怎么记"],
    )
    out = _search("我夜里总是睡不着该怎么办")
    assert "SECRET_T9_BODY" not in out
    assert _mark("书/hechao") in out
    assert MAP_COL not in out
    assert "仅语义" in out


def test_t11_embed_off_literal_still_works(kb, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_EMBED", "off")
    plant_book(kb, "beichuang", "北窗纪略", ["整风章"], ["整风以后，诸事重新排队。"])
    out = _search("北窗纪略")
    assert not out.startswith("失败")
    assert "北窗纪略" in out


def test_t10_fake_embed_does_not_drop_alias_hit(kb):
    """假嵌入把 B 抬到问句旁边时，不得把别名命中的 A 挤没。"""
    plant_book(
        kb,
        "beichuang",
        "北窗纪略",
        ["整风章", "邻章"],
        ["整风以后，诸事重新排队。", "邻块独白XYZ，跟别名无关。"],
    )
    plant_map(
        kb,
        "beichuang",
        "北窗纪略",
        "整风章",
        chapter_names=["整风章", "邻章"],
        aliases=["北窗事变 → 书/beichuang/整风章"],
    )
    from knowledge_mcp.index import invalidate, set_embedder

    dim = 8
    close = [1.0] + [0.0] * (dim - 1)
    far = [0.0, 1.0] + [0.0] * (dim - 2)

    def fake(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if t == "北窗事变以后呢" or "邻块独白XYZ" in (t or ""):
                out.append(list(close))
            else:
                out.append(list(far))
        return out

    set_embedder(fake)
    try:
        invalidate()
        from knowledge_mcp.retrieve import search

        out = search("北窗事变以后呢")
    finally:
        set_embedder(None)
        invalidate()
    assert _mark("书/beichuang") in out
    sug = _suggest_ids(out)
    assert any(s.endswith("/整风章") for s in sug) or "整风章" in out
    # B 可以在建议里，但不能是唯一命中且 A 消失
    assert "重新排队" not in out


def test_t13_map_solves_generic_verb_does_not_raise_idle(kb):
    """闲书「能解决什么」只共享问句里的高频二字动词，不得进路标。"""
    plant_book(kb, "hechao", "核潮讲义", ["核潮分层"], ["核潮是怎么形成的，分层以后怎么收。"])
    plant_map(
        kb, "hechao", "核潮讲义", "核潮分层",
        solves=["核潮分层以后局势", "潮势怎么算", "分层怎么记"],
        chapter_names=["核潮分层"],
    )
    plant_book(kb, "xianli", "闲利札记", ["卷一"], ["平均利润和生产价格正文。" + "循环。" * 80])
    plant_map(
        kb, "xianli", "闲利札记", "卷一",
        solves=["平均利润和生产价格是怎么形成的", "循环怎么记", "旧账怎么翻"],
    )
    out = _search("核潮是怎么形成的")
    assert _mark("书/hechao") in out
    assert _mark("书/xianli") not in out
    assert "平均利润" not in out


def test_t14_alias_shared_tail_does_not_raise_idle(kb):
    """两个更长专名只共享词尾时，闲书别名不得扩进问句。"""
    plant_book(
        kb, "queersen", "奎尔森札记", ["自卑章"],
        ["自卑感、人际关系和勇气在奎尔森心理学里怎么串。"],
    )
    plant_map(
        kb, "queersen", "奎尔森札记", "自卑章",
        solves=["自卑感是怎么来的", "勇气怎么用", "人际关系怎么办"],
        chapter_names=["自卑章"],
        aliases=["奎尔森心理学 → 书/queersen/自卑章"],
    )
    plant_book(
        kb, "tongshi", "通识讲义", ["总论"],
        ["健康心理学和社会心理学课堂。人际关系练习很多。"],
    )
    plant_map(
        kb, "tongshi", "通识讲义", "总论",
        solves=["课堂怎么上", "通识怎么记", "旧账怎么翻"],
        chapter_names=["总论"],
        aliases=[
            "健康心理学 → 书/tongshi/总论",
            "进化心理学 → 书/tongshi/总论",
        ],
    )
    out = _search("奎尔森心理学里自卑感、人际关系和勇气是怎么串起来的")
    assert _mark("书/queersen") in out
    assert _mark("书/tongshi") not in out


def test_t15_two_char_alias_prefix_expands(kb):
    """2 字别名落在问句片头时能扩；闲书只重复这 2 字进不了。"""
    plant_book(kb, "linchao", "林潮纪要", ["后事"], ["林潮事件以后诸事重新排队。"])
    plant_map(
        kb,
        "linchao",
        "林潮纪要",
        "后事",
        solves=["林潮以后怎么排", "后事怎么记", "潮势怎么算"],
        chapter_names=["后事"],
        aliases=["林潮 → 书/linchao/后事"],
    )
    plant_book(kb, "xianchao", "闲潮札记", ["卷一"], ["林潮。" * 80])
    plant_map(
        kb,
        "xianchao",
        "闲潮札记",
        "卷一",
        solves=["杂事怎么记", "旧账怎么翻", "循环怎么算"],
    )
    out = _search("林潮事件以后呢")
    assert _mark("书/linchao") in out
    assert _mark("书/xianchao") not in out
    assert "重新排队" not in out


def test_t16_missing_han_term_blocks_latin_homograph(kb):
    """汉文技术词全库没有时，文献作者拉丁姓不得单独顶路标。"""
    plant_book(
        kb,
        "shengzhan",
        "生展讲义",
        ["总论"],
        ["资料来源：Quel, J., Zervoulis, K. Child Development.\n循环。" * 20],
    )
    plant_map(
        kb,
        "shengzhan",
        "生展讲义",
        "总论",
        solves=["人格怎么形成", "课堂怎么上", "旧账怎么翻"],
    )
    out = _search("怎么用 Quel 写一个操作系统")
    assert _mark("书/shengzhan") not in out
    assert "没有像的" in out or "0" in out
    assert "循环" not in out


def test_t12_delete_cache_rebuilds(kb):
    plant_book(kb, "hechao", "核潮讲义", ["核潮分层"], ["分层讲完就到此为止。"])
    plant_book(kb, "xianbian", "闲编纪事", ["卷一 杂记"], ["变化。" * 200])
    _search("核潮分层以后局势怎么变化")
    cache = kb / "mcp" / ".kb-index.sqlite"
    for p in [cache, *cache.parent.glob(cache.name + "-*")]:
        if p.is_file():
            p.unlink()
    out = _search("核潮分层以后局势怎么变化")
    assert _mark("书/hechao") in out
    assert _mark("书/xianbian") not in out
    assert "到此为止" not in out
