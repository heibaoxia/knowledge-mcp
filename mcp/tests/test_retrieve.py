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

    # 本轮改为「仅字面必须命中问句自己的最长原片」后，两个长片不等长时
    # 只留最长那条：「拖延心理学」五字压过「自我控制」四字。
    # 这条不是「无空格问句能不能命中抬头」，而是路标只认最长的那条证据。
    out = search("拖延心理学与自我控制")
    assert "拖延心理学" in out
    assert "书/delay" in out
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


def test_read_section_by_name(kb):
    body = "# 7 记忆\n\n前言若干。\n\n## 短时记忆\n\nSECTION_MARK 短时记忆正文。\n\n## 长时记忆\n\n长时。\n"
    plant_book(kb, "psy", "心理学与生活", "教材。", ["7 记忆"], [body])
    from knowledge_mcp.retrieve import read

    out = read(target="书/psy/7 记忆#短时记忆")
    assert "SECTION_MARK" in out
    assert not out.startswith("失败")


def test_read_section_missing_fails_that_item(kb):
    plant_book(kb, "psy", "心理学与生活", "教材。", ["7 记忆"], ["# 7 记忆\n\n无小节。\n"])
    from knowledge_mcp.retrieve import read

    out = read(target="书/psy/7 记忆#不存在的节")
    assert out.startswith("失败") or "找不到" in out


def test_read_reports_window_index(kb):
    plant_book(kb, "delay", "拖延", "教材。", ["长章"], ["A" * 9000 + "TAIL"])
    from knowledge_mcp.retrieve import read

    out = read(target="书/delay/长章")
    assert "1/" in out and "窗" in out


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
    assert "仅语义" in out or "两路都中" in out
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


def test_quoted_article_keeps_host_book(kb):
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["实践论"], ["认识的两次飞跃。"])
    plant_book(kb, "psy", "心理学与生活", "教材。", ["记忆"], ["短时记忆。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("《实践论》说认识要经过哪两次飞跃")
    assert "毛泽东选集" in out
    assert "心理学与生活" not in out


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


def test_search_three_schools_does_not_drag_mao(kb):
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["讲话"], ["放了三大炮。" + "啊" * 200 + "随大流。"])
    plant_book(kb, "psy", "心理学与生活", "教材。", ["1 生活中的心理学"], ["心理学三大流派行为主义精神分析。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("心理学三大流派有什么区别")
    assert "毛泽东选集" not in out
    assert "心理学与生活" in out


def test_literal_only_drops_book_missing_rarest_long(kb):
    plant_book(kb, "adler", "自卑与超越", "阿德勒。", ["第三章 自卑感与优越感"], ["阿德勒说自卑感优越感来自追求。"])
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["讲话"], ["叫做自卑感，越改越卑。没有那个专名。"])
    _plant_map(kb, "adler", "自卑与超越", ["自卑感是怎么来的"], ["革命"], "第三章 自卑感与优越感")
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("阿德勒说的自卑感和优越感是怎么来的")
    assert "自卑与超越" in out
    assert "毛泽东选集" not in out


def test_literal_only_drops_high_df_book_missing_longest_term(kb):
    # S1：问句有长专名「课题分离术」，也有公共片「分析」（len=2，不成长片）。
    # 闲书只重复「分析」，命不中长专名，不许占仅字面格。
    plant_book(
        kb, "topic", "课题分离术入门", "讲课题分离术。",
        ["第一章 课题分离术"], ["课题分离术讲的是分清谁的事。"],
    )
    plant_book(kb, "noise", "杂谈语录", "随笔。", ["第一章 闲话"], ["分析" * 200])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("「课题分离术」和「分析」")
    assert "课题分离术入门" in out
    assert "杂谈语录" not in out


def test_literal_only_drops_high_df_book_missing_df0_longest(kb):
    # S2：问句里公共片本身也够长（「公共词」len=3），闲书只重复它、拿不出
    # 更长的那条原片 → 不许占仅字面格。期望书正文有长专名（字面）+
    # 地图也含长专名（地图）→ 两路都中，不受这条闸影响。
    plant_book(
        kb, "heavy", "成分考札记", "乡里旧账。",
        ["第一章 阶级成分考"], ["阶级成分考讲的是公共词在乡里的用法。"],
    )
    _plant_map(
        kb, "heavy", "成分考札记",
        ["阶级成分考是怎么做的", "公共词在乡里怎么用", "编成分表的老规矩"],
        ["外国法案怎么读"],
        "第一章 阶级成分考",
    )
    plant_book(kb, "chatty", "茶桌闲话", "闲谈。", ["第一章 闲话一则"], ["公共词" * 200])
    _plant_map(
        kb, "chatty", "茶桌闲话",
        ["怎么记流水账", "茶怎么泡", "闲话怎么聊"],
        ["汇编语言"],
        "第一章 闲话一则",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("阶级成分考、公共词")
    assert "成分考札记" in out
    assert "茶桌闲话" not in out


def test_map_column_ignores_single_char_piece(kb):
    # S3：地图侧不许只靠 len<3 的残片入栏。
    # parse_query("弗洛伊德怎么看") 推演（index.py parse_query 逐字走）：
    #   全程 HAN 无标点 → buf 攒成 "弗洛伊德怎么看"；FUN_WORDS 里的「怎么」
    #   被 replace 成空格 → "弗洛伊德 看"；两块都不是 FUN_WORDS、也不是
    #   全由 FUN_CHARS 组成 → parts = ["弗洛伊德", "看"]。
    #   「看」len=1 是残片，「弗洛伊德」len=4 是最长片。
    # 现实现下闲书进不了地图栏（_match_gate 拿最长片当 gate），
    # 本测钉的是别把它改成靠残片入栏。
    plant_book(
        kb, "doc", "解梦札记", "讲梦。",
        ["第一章 梦的做法"], ["讲梦的做法，没有这些术语。"],
    )
    _plant_map(
        kb, "doc", "解梦札记",
        ["弗洛伊德解释梦的做法", "梦和记忆的关系", "睡前念头从哪来"],
        ["量子场论"],
        "第一章 梦的做法",
    )
    plant_book(kb, "glance", "街边张望", "闲看。", ["第一章 闲坐"], ["讲院子里的旧事。"])
    _plant_map(kb, "glance", "街边张望", ["看"], ["量子场论"], "第一章 闲坐")
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("弗洛伊德怎么看")
    assert "解梦札记" in out
    assert "街边张望" not in out


def test_life_query_keeps_map_only_long_piece(kb):
    # S4：生活口吻问句没有术语，长片（意别人 / 不是讨厌我）只在期望书地图里，
    # 正文一个口语片都没有 → 仍要能靠仅语义进路标。
    plant_book(kb, "life", "生活的问法", "对话。", ["第一章 对话"], ["哲人对话，没有这些口语。"])
    _plant_map(
        kb, "life", "生活的问法",
        ["总是在意别人是不是讨厌我该怎么办", "怕被讨厌还想做自己怎么办", "别人的事和我的事怎么分开"],
        ["量子场论"],
        "第一章 对话",
    )
    plant_book(kb, "aside", "旁枝别记", "杂事。", ["第一章 杂事"], ["讲些杂事。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("我总是很在意别人是不是讨厌我，该怎么办")
    assert "生活的问法" in out
    assert "仅语义" in out or "两路都中" in out


def test_literal_only_keeps_book_with_single_long_piece(kb):
    # S5：问句只有一条长片时，正文含它的书必须留在仅字面（最长片门槛不许误伤）。
    plant_book(kb, "memo", "记忆札记", "讲义。", ["第一章 早期经验"], ["早期记忆影响人格。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("早期记忆")
    assert "记忆札记" in out
    assert "仅字面" in out


def test_single_term_literal_still_lands(kb):
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["论持久战"], ["游击战是必要的。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("游击战")
    assert "毛泽东选集" in out


def test_suggest_uses_map_evidence_not_title_boost(kb):
    plant_book(
        kb, "psy", "心理学与生活", "教材。",
        ["1 生活中的心理学", "7 记忆"],
        ["生活中的心理学导论。", "短时记忆是记忆的一种。短时记忆。" * 20],
    )
    _plant_map(
        kb, "psy", "心理学与生活",
        ["短时记忆是怎么讲的、怎么记才记得住", "心理学三大流派有什么区别"],
        ["怎么用 PyTorch"],
        "7 记忆",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("《心理学与生活》里短时记忆是怎么讲的")
    assert "心理学与生活" in out
    assert "7 记忆" in out
    pos7 = out.find("7 记忆")
    pos1 = out.find("1 生活中的心理学")
    assert pos7 != -1
    assert pos1 == -1 or pos7 < pos1


def test_overview_query_suggests_guide_or_map(kb):
    plant_book(
        kb, "courage", "被讨厌的勇气", "阿德勒。",
        ["推荐序一 勇气的心理学", "第四夜 要有被讨厌的勇气"],
        ["序言勇气。", "第四夜正文。"],
    )
    _plant_map(kb, "courage", "被讨厌的勇气", ["总是在意别人是不是讨厌我该怎么办"], ["革命"], "第四夜 要有被讨厌的勇气")
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("《被讨厌的勇气》大概讲什么")
    assert "被讨厌的勇气" in out
    assert "书/courage/导读" in out or "书/courage/地图" in out


def test_landmark_reports_hit_counts(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章", "第二章"], ["UNIQUE_LIT_TOKEN 甲块", "UNIQUE_LIT_TOKEN 乙块"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("UNIQUE_LIT_TOKEN")
    assert "命中" in out and "块" in out
    assert "甲块" not in out and "乙块" not in out


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
    assert "仅语义" in out or "两路都中" in out


def test_glued_missing_piece_falls_back_to_edge_substring(kb):
    # S6：长片整串 DF=0，只剥两边，闲书不得占格。
    plant_book(
        kb, "core", "核素分层入门", "讲核素分层。",
        ["第一章 核素分层"], ["核素分层是把层次分开的办法。"],
    )
    plant_book(kb, "noise", "杂谈语录", "随笔。", ["第一章 闲话"], ["分析" * 200])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("核素分层里讲了什么")
    assert "核素分层入门" in out
    assert "杂谈语录" not in out


def test_quoted_title_is_an_extra_piece(kb):
    # S7：书名含功能字「被/的」，问句用《》。闲书地图里有「大概讲」。
    plant_book(
        kb, "night", "被夜航的对照", "对照。",
        ["第一章 对照"], ["对照的正文，没有大概讲三个字。"],
    )
    _plant_map(
        kb, "night", "被夜航的对照",
        ["夜航时怎么对照航路", "对照录能解决什么疑惑", "夜里看航标怎么办"],
        ["量子场论"],
        "第一章 对照",
    )
    plant_book(kb, "decoy", "别本札记", "闲。", ["第一章"], ["别的正文。"])
    _plant_map(
        kb, "decoy", "别本札记",
        ["这本书大概讲过别的事", "札记怎么写", "闲话怎么聊"],
        ["量子场论"],
        "第一章",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("《被夜航的对照》大概讲什么")
    assert "被夜航的对照" in out
    assert "书/night/导读" in out or "书/night/地图" in out


def test_nav_block_name_is_not_a_literal_hit(kb):
    # S8：导航件块名不进字面。
    plant_book(kb, "idx", "核素札记", "札记。", ["索引"], ["这篇按设计不进索引正文。核素札记补充句。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("索引")
    assert "书/idx/索引" not in out


def test_image_shell_book_stays_out_of_literal(kb):
    # S9：无正文扫描壳不进仅字面/两路都中。
    imgs = "\n".join(f"![](p-{i}.jpg)" for i in range(30))
    plant_book(kb, "shell", "镜中残页", "扫描。", ["正文"], [imgs])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("镜中残页里写了什么")
    assert "仅字面" not in out or "镜中残页" not in out
    assert "两路都中" not in out or "镜中残页" not in out


def test_aboutness_drops_body_only_proper_name(kb):
    # S10：闲书正文大写专名，地图/章名/书名都不讲问句的主题片。
    plant_book(
        kb, "tide", "潮汐札记", "讲潮。",
        ["潮"], ["潮怎么解释。潮汐核素也写在正文里。"],
    )
    _plant_map(
        kb, "tide", "潮汐札记",
        ["潮怎么解释", "潮和睡眠有什么关系", "夜里的潮从哪来"],
        ["量子场论"],
        "潮",
    )
    plant_book(
        kb, "aside", "街边对照", "闲谈。",
        ["第一章 闲坐"], ["潮汐核素" * 40],
    )
    _plant_map(
        kb, "aside", "街边对照",
        ["怎么记流水账", "茶怎么泡", "闲话怎么聊"],
        ["量子场论"],
        "第一章 闲坐",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("潮是怎么被解释的，潮汐核素怎么看")
    assert "潮汐札记" in out
    assert "街边对照" not in out


def test_aboutness_keeps_two_topical_books(kb):
    # S11：一本靠章名、一本靠地图，都得留。
    plant_book(
        kb, "alpha", "核素回忆", "回忆。",
        ["早期核素"], ["早期核素写在章里。"],
    )
    _plant_map(
        kb, "alpha", "核素回忆",
        ["早期核素是怎么来的", "小时候的核素怎么记", "核素和性格"],
        ["量子场论"],
        "早期核素",
    )
    plant_book(
        kb, "beta", "人格讲义", "讲义。",
        ["第一章 人格"], ["早期核素影响人格。早期核素。"],
    )
    _plant_map(
        kb, "beta", "人格讲义",
        ["人格是怎么形成的", "早期核素怎么进人格", "记忆和人格"],
        ["量子场论"],
        "第一章 人格",
    )
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("早期核素怎么影响一个人的人格")
    assert "核素回忆" in out
    assert "人格讲义" in out


def test_aboutness_does_not_drop_lone_body_term(kb):
    # S12：短词只在正文、结果集没有 aboutness 对照 → 仍回捞。
    plant_book(kb, "side", "核素边注", "边注。", ["第一章"], ["横向核素出现在正文。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search

    invalidate()
    out = search("横向核素")
    assert "核素边注" in out
    assert "仅字面" in out
