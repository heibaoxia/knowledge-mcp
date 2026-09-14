"""Block 2 gates: search landmarks only; read must name a part; cap size."""
from pathlib import Path


def plant_book(
    kb: Path,
    slug: str,
    title: str,
    intro: str,
    chapters: list[str],
    bodies: list[str],
    tags: str = "[心理学]",
) -> None:
    d = kb / "资料" / "书" / slug
    d.mkdir(parents=True)
    toc = "\n".join(f"- {c}" for c in chapters)
    (d / "导读.md").write_text(
        f"---\ntitle: {title}\ntype: 书\nintro: {intro}\ntags: {tags}\n"
        f"source: 原始资料归档/{slug}.epub\n---\n\n# {title}\n\n{intro}\n\n## 目录\n{toc}\n",
        encoding="utf-8",
    )
    for i, (c, b) in enumerate(zip(chapters, bodies), 1):
        (d / f"{i:02d}-{c}.md").write_text(f"# {c}\n\n{b}\n", encoding="utf-8")


def plant_note(kb: Path, slug: str, title: str, intro: str, body: str) -> None:
    (kb / "资料" / "笔记" / f"{slug}.md").write_text(
        f"---\ntitle: {title}\ntype: 笔记\nintro: {intro}\ntags: [感悟]\n"
        f"generated: true\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def test_search_returns_landmarks_without_body(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "讲拖延从哪来。",
        ["第一章 为什么拖"],
        ["SECRET_BODY_TOKEN 这一章很长很长。"],
    )
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert "拖延心理学" in out
    assert "书/delay" in out
    assert "SECRET_BODY_TOKEN" not in out
    assert not out.startswith("失败")


def test_search_body_token_hits_identity_without_leaking_body(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "讲拖延从哪来。",
        ["第一章 为什么拖"],
        ["SECRET_BODY_TOKEN 出现在正文。"],
    )
    from knowledge_mcp.retrieve import search

    out = search("SECRET_BODY_TOKEN")
    assert "拖延心理学" in out
    assert "SECRET_BODY_TOKEN" not in out


def test_search_books_and_notes_together(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["正文"])
    plant_note(kb, "my-delay", "我的拖延对策", "自己用过的办法。", "笔记正文不该出现。")
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert "拖延心理学" in out
    assert "我的拖延对策" in out
    assert "笔记/my-delay" in out
    assert "笔记正文不该出现" not in out


def test_search_empty_is_honest(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["正文"])
    from knowledge_mcp.retrieve import search

    out = search("量子场论")
    assert "拖延心理学" not in out
    assert "没有" in out or "0" in out


def test_search_caps_at_five(kb):
    for i in range(8):
        plant_note(kb, f"n{i}", f"拖延笔记{i}", "关于拖延。", "x")
    from knowledge_mcp.retrieve import search

    out = search("拖延")
    assert out.count("身份：笔记/") <= 5


def test_read_without_identity_refused(kb):
    from knowledge_mcp.retrieve import read

    out = read("", None)
    assert out.startswith("失败")
    assert "卡在哪一步" in out


def test_read_whole_book_refused(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["整章正文ABC"])
    from knowledge_mcp.retrieve import read

    out = read("书/delay", None)
    assert out.startswith("失败")
    assert "整章正文ABC" not in out


def test_read_named_chapter(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "教材。",
        ["第一章 为什么拖", "第二章 怎么改"],
        ["第一章正文AAA", "第二章正文BBB"],
    )
    from knowledge_mcp.retrieve import read

    out = read("书/delay", "第一章 为什么拖")
    assert "第一章正文AAA" in out
    assert "第二章正文BBB" not in out


def test_read_has_char_cap(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["字" * 20000])
    from knowledge_mcp.retrieve import read

    out = read("书/delay", "第一章")
    assert not out.startswith("失败")
    assert len(out) < 12000
    assert "邻块" in out or "截断" in out


def test_read_note_by_id(kb):
    plant_note(kb, "my-delay", "我的拖延对策", "办法。", "只此一段。")
    from knowledge_mcp.retrieve import read

    out = read("笔记/my-delay", None)
    assert "只此一段" in out


def test_search_bigram_hits_two_headers_without_spaces(kb):
    plant_book(kb, "delay", "拖延心理学", "讲拖延从哪来。", ["第一章 为什么拖"], ["正文甲"])
    plant_book(kb, "self", "自我控制", "讲自控从哪来。", ["第一章 怎么忍"], ["正文乙"])
    from knowledge_mcp.retrieve import search

    out = search("拖延心理学与自我控制")
    assert "拖延心理学" in out
    assert "自我控制" in out
    assert not out.startswith("失败")


def test_search_suggests_readable_chapter_identities(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "教材。",
        ["第一章 为什么拖", "第二章 怎么改"],
        ["SECRET_BODY_ONE", "SECRET_BODY_TWO"],
    )
    from knowledge_mcp.retrieve import search

    out = search("为什么拖")
    assert "书/delay" in out
    assert "书/delay/第一章 为什么拖" in out
    assert "书/delay/第二章 怎么改" not in out
    assert "SECRET_BODY_ONE" not in out
    assert "SECRET_BODY_TWO" not in out

    by_title = search("拖延心理学")
    assert "书/delay" in by_title
    assert "SECRET_BODY_ONE" not in by_title
    assert "SECRET_BODY_TWO" not in by_title


def test_read_batch_two_books_at_once(kb):
    plant_book(
        kb,
        "delay",
        "拖延心理学",
        "教材。",
        ["第一章 为什么拖", "第二章 怎么改"],
        ["AAA拖延正文", "BBB拖延另一章"],
    )
    plant_book(
        kb,
        "self",
        "自我控制",
        "教材。",
        ["第一章 怎么忍"],
        ["CCC控制正文"],
    )
    plant_note(kb, "mine", "我的对策", "办法。", "DDD笔记正文")
    from knowledge_mcp.retrieve import search
    from knowledge_mcp.retrieve import read

    out = search("拖延")
    assert "AAA拖延正文" not in out
    assert "CCC控制正文" not in out
    assert "DDD笔记正文" not in out

    batch = read("", None, ["书/delay/第一章 为什么拖", "书/self/第一章 怎么忍"])
    assert not batch.startswith("失败")
    assert "AAA拖延正文" in batch
    assert "CCC控制正文" in batch
    assert "BBB拖延另一章" not in batch

    with_note = read("", None, ["书/delay/第一章 为什么拖", "笔记/mine"])
    assert "AAA拖延正文" in with_note
    assert "DDD笔记正文" in with_note


def test_read_batch_partial_failure_gives_other_blocks(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["AAA拖延正文"])
    plant_book(kb, "self", "自我控制", "教材。", ["第一章 怎么忍"], ["CCC控制正文"])
    from knowledge_mcp.retrieve import read

    out = read("", None, ["书/delay/第一章 为什么拖", "书/ghost/第一章", "书/self/第一章 怎么忍"])
    body = out.split("未读", 1)[0]
    assert "AAA拖延正文" in body
    assert "CCC控制正文" in body
    assert "失败" in body
    assert "卡在哪一步" in body


def test_read_batch_whole_book_identity_rejects_all(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["AAA拖延正文"])
    from knowledge_mcp.retrieve import read

    out = read("", None, ["书/delay"])
    assert out.startswith("失败")
    assert "整本" in out
    assert "AAA拖延正文" not in out

    mixed = read("", None, ["书/delay/第一章 为什么拖", "书/delay"])
    assert mixed.startswith("失败")
    assert "整本" in mixed
    assert "AAA拖延正文" not in mixed


def test_read_batch_without_identity_rejected(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["AAA拖延正文"])
    from knowledge_mcp.retrieve import read

    empty = read("", None, [])
    assert empty.startswith("失败")
    assert "没有身份" in empty
    assert "AAA拖延正文" not in empty

    blank = read("", None, ["书/delay/第一章 为什么拖", ""])
    assert blank.startswith("失败")
    assert "没有身份" in blank
    assert "AAA拖延正文" not in blank


def test_read_batch_total_cap_truncates_and_marks_unread(kb):
    plant_book(
        kb,
        "big",
        "大部头",
        "教材。",
        ["第一章 甲", "第二章 乙", "第三章 丙", "第四章 丁"],
        ["甲" * 8100, "乙" * 8100, "丙" * 8100, "丁" * 8100],
    )
    from knowledge_mcp.retrieve import read

    out = read(
        "",
        None,
        ["书/big/第一章 甲", "书/big/第二章 乙", "书/big/第三章 丙", "书/big/第四章 丁"],
    )
    body = out.split("未读", 1)[0]
    assert "邻块" in body or "截断" in body
    assert "甲" in body
    assert "乙" in body
    assert "丙" * 50 not in body
    assert "丁" * 50 not in body
    assert len(body) < 24000
    assert "未读" in out
    assert "书/big/第三章 丙" in out
    assert "书/big/第四章 丁" in out
    assert body.count("甲") <= 8001
    assert body.count("乙") <= 8001


def test_read_logs_canonical_identity(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["AAA拖延正文"])
    from knowledge_mcp.log import read_calls
    from knowledge_mcp.retrieve import read

    read("书/delay", "第一章 为什么拖")
    rows = [r for r in read_calls() if r.get("door") == "kb_read"]
    assert rows[-1]["ok"] is True
    assert rows[-1]["target"] == "书/delay/第一章 为什么拖"


def test_server_kb_read_accepts_targets(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["AAA拖延正文"])
    from knowledge_mcp.log import read_calls
    from knowledge_mcp.server import kb_read

    raw = getattr(kb_read, "__wrapped__", kb_read)
    out = raw("", None, ["书/delay/第一章 为什么拖"])
    assert "AAA拖延正文" in out
    rows = [r for r in read_calls() if r.get("door") == "kb_read"]
    assert rows[-1]["target"] == "书/delay/第一章 为什么拖"


def test_server_instructions_steer_read():
    from knowledge_mcp.server import mcp

    text = mcp.instructions or ""
    assert "8000" in text
    assert "24000" in text
    assert "够答就停" in text
    assert "续" in text
    assert "kb_search" in text
    assert "资料" in text


def test_search_empty_on_pytorch(kb):
    plant_book(kb, "psy", "心理学与生活", "教材。", ["神经"], ["训练神经网络的章节"])
    from knowledge_mcp.retrieve import search

    out = search("怎么用 PyTorch 训练一个神经网络")
    assert "心理学与生活" not in out
    assert "没有" in out or "0" in out


def test_read_window_hash2_is_not_the_start(kb):
    body = "A" * 9000 + "TAIL_MARK"
    plant_book(kb, "delay", "拖延心理学", "教材。", ["长章"], [body])
    from knowledge_mcp.retrieve import read

    first = read(target="书/delay/长章")
    assert "TAIL_MARK" not in first
    assert "已截断" not in first or "邻块" in first
    second = read(target="书/delay/长章#2")
    assert "TAIL_MARK" in second
    assert "邻块" in second


def test_read_map_by_ident(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章", "第二章"], ["章正文", "另一章"])
    (kb / "资料" / "书" / "delay" / "地图.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 地图\ngenerated: true\n---\n\n地图短文 MAP_ONLY_MARK\n",
        encoding="utf-8",
    )
    from knowledge_mcp.retrieve import read

    out = read("书/delay/地图")
    assert "MAP_ONLY_MARK" in out
    assert not out.startswith("失败")
    chap = read("书/delay/第二章")
    assert "MAP_ONLY_MARK" not in chap
    assert "邻块" in chap
    assert "地图" not in chap.split("邻块")[-1]


def _plant_map(kb, slug, title, solves, not_solves, chapter):
    d = kb / "资料" / "书" / slug
    ids = f"书/{slug}/{chapter}"
    ev = "\n".join(f"- {s} → {ids}" for s in solves)
    (d / "地图.md").write_text(
        f"---\ntitle: {title}\ntype: 地图\nbook: 书/{slug}\ngenerated: true\n---\n\n"
        f"## 能解决什么\n" + "\n".join(f"- {s}" for s in solves) + "\n\n"
        f"## 不解决什么\n" + "\n".join(f"- {s}" for s in not_solves) + "\n\n"
        f"## 建议从哪读\n- {ids}\n\n## 依据块\n{ev}\n",
        encoding="utf-8",
    )


def test_three_columns_overlap_by_book(kb):
    plant_book(kb, "courage", "被讨厌的勇气", "阿德勒。", ["第四夜 要有被讨厌的勇气"], ["正文里写讨厌两个字。"])
    _plant_map(
        kb, "courage", "被讨厌的勇气",
        ["总是在意别人是不是讨厌我该怎么办", "人际关系里总怕被讨厌怎么办", "别人看法和我的事怎么分开"],
        ["怎么训练神经网络"],
        "第四夜 要有被讨厌的勇气",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("讨厌")
    assert "SECRET" not in out
    assert "两路都中" in out
    assert "书/courage" in out
    assert "书/courage/第四夜 要有被讨厌的勇气" in out
    assert "正文里写" not in out


def test_map_only_life_query(kb):
    plant_book(kb, "courage", "被讨厌的勇气", "阿德勒。", ["第三夜 让干涉你生活的人见鬼去"], ["哲人谈话，没有这些口语。"])
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["实践论"], ["实践论正文讲认识。"])
    _plant_map(
        kb, "courage", "被讨厌的勇气",
        ["总是在意别人是不是讨厌我该怎么办", "怕被别人讨厌还想做自己怎么办", "别人干涉我的生活该怎么办"],
        ["革命战争怎么打", "怎么用 PyTorch"],
        "第三夜 让干涉你生活的人见鬼去",
    )
    _plant_map(
        kb, "mao", "毛泽东选集",
        ["矛盾论讲了什么", "实践和认识是什么关系", "怎么分析中国社会各阶级"],
        ["个人怕被讨厌怎么办", "怎么用 PyTorch"],
        "实践论",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    q = "我总是很在意别人是不是讨厌我，该怎么办"
    assert "课题分离" not in q and "阿德勒" not in q
    out = search(q)
    assert "被讨厌的勇气" in out
    assert "毛泽东选集" not in out
    assert "仅地图" in out or "两路都中" in out
    assert "课题分离" not in out


def test_literal_only_column(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章 为什么拖"], ["UNIQUE_LIT_TOKEN 出现在正文。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("UNIQUE_LIT_TOKEN")
    assert "拖延心理学" in out
    assert "仅字面" in out
    assert "两路都中" not in out
    assert "UNIQUE_LIT_TOKEN" not in out


def test_pytorch_empty_with_maps(kb):
    plant_book(kb, "psy", "心理学与生活", "教材。", ["神经"], ["训练神经网络的章节"])
    _plant_map(
        kb, "psy", "心理学与生活",
        ["短时记忆是怎么回事", "心理学三大流派有什么区别", "梦和意识状态怎么解释"],
        ["怎么用 PyTorch 训练一个神经网络"],
        "神经",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("怎么用 PyTorch 训练一个神经网络")
    assert "心理学与生活" not in out
    assert "没有" in out or "0" in out


def test_titled_query_does_not_drag_unrelated_book(kb):
    plant_book(kb, "courage", "被讨厌的勇气", "阿德勒。", ["第四夜 要有被讨厌的勇气"], ["勇气正文"])
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["实践论"], ["也谈勇气与讨厌。"])
    _plant_map(
        kb, "courage", "被讨厌的勇气",
        ["总是在意别人是不是讨厌我该怎么办", "怕被别人讨厌还想做自己怎么办", "别人干涉我的生活该怎么办"],
        ["革命战争怎么打"],
        "第四夜 要有被讨厌的勇气",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("《被讨厌的勇气》大概讲什么")
    assert "被讨厌的勇气" in out
    assert "毛泽东选集" not in out


def test_life_query_keeps_mao_out_even_if_body_has_grams(kb):
    plant_book(kb, "courage", "被讨厌的勇气", "阿德勒。", ["第四夜 要有被讨厌的勇气"], ["哲人谈话。"])
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["实践论"], ["文中有别人讨厌厌我意别很多别人。"])
    _plant_map(
        kb, "courage", "被讨厌的勇气",
        ["总是在意别人是不是讨厌我该怎么办", "怕被别人讨厌还想做自己怎么办", "别人干涉我的生活该怎么办"],
        ["革命战争怎么打"],
        "第四夜 要有被讨厌的勇气",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("我总是很在意别人是不是讨厌我，该怎么办")
    assert "被讨厌的勇气" in out
    assert "毛泽东选集" not in out


def test_life_fallback_still_returns_map(kb):
    plant_book(kb, "courage", "被讨厌的勇气", "介绍。", ["第四夜"], ["完全不相干的哲人对话。"])
    _plant_map(
        kb, "courage", "被讨厌的勇气",
        ["总是在意别人是不是讨厌我该怎么办", "怕被讨厌还想做自己怎么办", "别人的课题我不要扛"],
        ["量子场论"],
        "第四夜",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("我总是很在意别人是不是讨厌我，该怎么办")
    assert "被讨厌的勇气" in out
    assert "仅地图" in out or "两路都中" in out
