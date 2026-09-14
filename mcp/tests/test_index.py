"""进程内语片 FTS：二字片+单字、语片 AND、导航块、零命中。"""
from pathlib import Path


def _plant_book(kb: Path, slug: str, title: str, files: dict[str, str]) -> None:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True)
    toc = "\n".join(f"- {Path(n).stem.split('-', 1)[-1]}" for n in files)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: 介绍。\ntags: []\n"
        f"source: x.epub\n---\n\n# {title}\n\n介绍。\n\n## 目录\n{toc}\n",
        encoding="utf-8",
    )
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")


def test_tokenize_bigrams_and_unigrams():
    from knowledge_mcp.index import tokenize_index

    s = tokenize_index("矛盾论")
    bits = s.split()
    assert "矛盾" in bits
    assert "盾论" in bits
    assert "矛" in bits


def test_parse_query_phrase_not_or_bag():
    from knowledge_mcp.index import parse_query

    parts = parse_query("矛盾论讲了什么，实践和认识是什么关系")
    assert "什么" not in parts
    assert any("矛盾" in p for p in parts)


def test_nav_filename():
    from knowledge_mcp.index import is_nav_name

    assert is_nav_name("01-目 录.md")
    assert is_nav_name("27-参考文献.md")
    assert not is_nav_name("02-第一卷.md")
    assert not is_nav_name("15-7 记忆.md")


def test_search_prefers_phrase_over_relation(kb):
    _plant_book(
        kb,
        "mao",
        "毛泽东选集",
        {"02-实践论.md": "# 实践论\n\n矛盾论讲实践和认识。\n"},
    )
    _plant_book(
        kb,
        "courage",
        "被讨厌的勇气",
        {"09-第二夜.md": "# 第二夜\n\n一切烦恼都来自人际关系。\n"},
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("矛盾论讲了什么关系")
    books = {h["book_id"] for h in hits}
    assert "mao" in books
    assert "courage" not in books


def test_single_char_dream_hits(kb):
    _plant_book(
        kb,
        "adler",
        "自卑与超越",
        {"08-梦.md": "# 梦\n\n这一章讲梦的解释。\n"},
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("梦")
    assert any(h["book_id"] == "adler" for h in hits)


def test_pytorch_is_empty_even_with_train_noise(kb):
    _plant_book(
        kb,
        "psy",
        "心理学与生活",
        {"11-神经.md": "# 神经\n\n训练神经网络的章节。\n"},
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("怎么用 PyTorch 训练一个神经网络")
    assert hits == []


def test_query_with_extra_verb_still_hits_title(kb):
    _plant_book(
        kb,
        "mao",
        "毛泽东选集",
        {"21-矛盾论.md": "# 矛盾论\n\n两种宇宙观。\n"},
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("矛盾论讲了什么")
    assert hits and hits[0]["name"] == "矛盾论"


def test_named_article_ranks_above_body_mentions(kb):
    _plant_book(
        kb,
        "mao",
        "毛泽东选集",
        {
            "21-矛盾论.md": "# 矛盾论\n\n矛盾论正文。\n",
            "30-五四运动.md": "# 五四运动\n\n文中提到矛盾论。\n",
        },
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("矛盾论")
    names = [h["name"] for h in hits]
    assert names[0] == "矛盾论"


def test_nav_body_not_indexed(kb):
    _plant_book(
        kb,
        "mao",
        "毛泽东选集",
        {
            "01-目 录.md": "# 目录\n\n- 矛盾论\n- 实践论\n",
            "02-实践论.md": "# 实践论\n\n实践论正文无目录页那些链接。\n",
        },
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("矛盾论")
    names = [h["name"] for h in hits]
    assert all("目" not in n and "录" not in n for n in names)


def _guide(kb: Path, slug: str, title: str, chapters: list[str]) -> Path:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True)
    toc = "\n".join(f"- {c}" for c in chapters)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: 介绍。\n---\n\n# {title}\n\n## 目录\n{toc}\n",
        encoding="utf-8",
    )
    for i, c in enumerate(chapters, 1):
        (d / f"{i:02d}-{c}.md").write_text(f"# {c}\n\n正文。\n", encoding="utf-8")
    return d


VALID = """---
title: 拖延心理学
type: 地图
book: 书/delay
generated: true
---

## 能解决什么
- 总是拖到截止日期前一晚才动手怎么办
- 明明想改却还是把事情往后推怎么办
- 工作一难就先刷手机该怎么收

## 不解决什么
- 怎么用 PyTorch 训练网络
- 中国社会各阶级怎么划分

## 建议从哪读
- 书/delay/第一章 为什么拖

## 依据块
- 总是拖到截止日期前一晚才动手怎么办 → 书/delay/第一章 为什么拖
- 明明想改却还是把事情往后推怎么办 → 书/delay/第一章 为什么拖
- 工作一难就先刷手机该怎么收 → 书/delay/第一章 为什么拖
"""


def test_parse_and_ok(kb):
    from knowledge_mcp.index import ident_exists, map_problems, parse_map

    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    (d / "地图.md").write_text(VALID, encoding="utf-8")
    assert map_problems(d) == []
    p = parse_map(VALID)
    assert p["title"] == "拖延心理学"
    assert 3 <= len(p["solves"]) <= 8
    assert ident_exists("书/delay/第一章 为什么拖")


def test_missing_map_is_problem(kb):
    from knowledge_mcp.index import map_problems

    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    probs = map_problems(d)
    assert any("缺" in x for x in probs)


def test_dead_ident_is_problem(kb):
    from knowledge_mcp.index import map_problems

    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    bad = VALID.replace("书/delay/第一章 为什么拖", "书/delay/不存在的章")
    (d / "地图.md").write_text(bad, encoding="utf-8")
    probs = map_problems(d)
    assert any("不存在" in x or "死" in x for x in probs)


def test_title_must_match_guide(kb):
    from knowledge_mcp.index import map_problems

    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    (d / "地图.md").write_text(VALID.replace("title: 拖延心理学", "title: 编的书名"), encoding="utf-8")
    assert map_problems(d)


def test_map_file_not_in_literal_index(kb):
    _plant_book(kb, "delay", "拖延心理学", {"01-第一章.md": "# 第一章\n\n只谈拖延。\n"})
    (kb / "资料" / "书" / "delay" / "地图.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 地图\ngenerated: true\n---\n\n"
        "## 能解决什么\n- UNIQUE_MAP_TOKEN 怕被讨厌怎么办\n",
        encoding="utf-8",
    )
    from knowledge_mcp.index import invalidate, search_index

    invalidate()
    hits = search_index("UNIQUE_MAP_TOKEN")
    assert all(h.get("kind") != "书" or "地图" not in h.get("ident", "") for h in hits)
    assert all("UNIQUE_MAP_TOKEN" not in str(h.get("ident")) for h in hits)


def test_search_maps_hits_solves_not_notsolves(kb):
    _plant_book(kb, "courage", "被讨厌的勇气", {"11-第四夜.md": "# 第四夜\n\n对话。\n"})
    (kb / "资料" / "书" / "courage" / "地图.md").write_text(
        "---\ntitle: 被讨厌的勇气\ntype: 地图\nbook: 书/courage\ngenerated: true\n---\n\n"
        "## 能解决什么\n- 总是在意别人是不是讨厌我该怎么办\n"
        "- 怕被别人讨厌怎么办\n- 人际关系里总寻求认可怎么办\n\n"
        "## 不解决什么\n- 怎么用 PyTorch 训练网络\n\n"
        "## 建议从哪读\n- 书/courage/第四夜\n\n"
        "## 依据块\n- 总是在意别人是不是讨厌我该怎么办 → 书/courage/第四夜\n"
        "- 怕被别人讨厌怎么办 → 书/courage/第四夜\n"
        "- 人际关系里总寻求认可怎么办 → 书/courage/第四夜\n",
        encoding="utf-8",
    )
    from knowledge_mcp.index import invalidate, search_index, search_maps

    invalidate()
    assert search_maps("PyTorch") == [] or all("PyTorch" not in str(h) for h in search_maps("PyTorch"))
    hits = search_maps("总是在意别人是不是讨厌我该怎么办")
    assert hits and hits[0]["book_id"] == "courage"
    lit = search_index("讨厌")
    assert all("/地图" not in h["ident"] for h in lit)
