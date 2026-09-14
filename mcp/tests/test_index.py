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
