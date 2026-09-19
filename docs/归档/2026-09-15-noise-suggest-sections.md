# 闲书不出路标 + 建议块 + 节目录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/本轮Spec.md` 让闲书不进路标、建议块贴篇名、块内能点节；题集冻结。

**Architecture:** 不换引擎。`index.py` 查询侧关掉三字窗、片内改 FTS 短语、功能字不拆「目的论」。`retrieve.py` 只在路标层淘汰弱仅字面、按依据块/导读排建议块、阅读认 `#节名`/`@偏移`。两路仍都跑。

**Tech Stack:** Python 3.11、pytest、进程内 SQLite FTS5、零新依赖。

## Global Constraints

- 正本 Markdown；索引只在内存；不落盘；不上向量/jieba/新依赖
- 路标永不回正文；两路都跑；重合由代码标
- 不要把「关系」「分析」当停用词；不要再加生活题/书名过滤
- 单窗 8000 / 5 块 / 24000；`#` 后纯数字仍是窗
- `docs/验收标准.md` Q1–Q14、W1–W20 不许改期望
- 马尾辫 full：最短能用；先复用 `plant_book` / `_plant_map` / `invalidate`
- TDD：先写失败测试，再改生产代码
- 工作目录 `仓库根`；`PYTHONPATH=mcp`；`.venv/Scripts/python.exe -m pytest mcp/tests -q`
- 同一分支：Task A pytest 1–6 全绿后再改阅读做 Task B

---

### Task 1: 字面召回（三字窗 / 短语 / 目的论）

**Files:**
- Modify: `mcp/knowledge_mcp/index.py`（`parse_query`、`_fts_piece`、`query_match`、`_match_gate`；删除 MATCH 路径上的 `_expand_pieces`）
- Test: `mcp/tests/test_index.py`、`mcp/tests/test_retrieve.py`

**Produces:** `query_match` / `_match_gate` 只用 `parse_query` 原片；片内短语；`parse_query("目的论")==["目的论"]`

- [ ] **Step 1: 写失败测试**（追加到现有测试文件，复用 `_plant_book` / `plant_book`）

`mcp/tests/test_index.py`:

```python
def test_parse_query_keeps_mudilun():
    from knowledge_mcp.index import parse_query
    assert parse_query("目的论") == ["目的论"]


def test_trigram_window_does_not_match_far_bigrams(kb):
    _plant_book(
        kb, "mao", "毛泽东选集",
        {"02-讲话.md": "# 讲话\n\n放了三大炮，公社炼钢。" + ("啊" * 200) + "百分之四十随大流。\n"},
    )
    from knowledge_mcp.index import invalidate, search_index
    invalidate()
    hits = search_index("心理学三大流派")
    assert not any(h["book_id"] == "mao" for h in hits)


def test_purpose_theory_hits_host_book(kb):
    _plant_book(kb, "courage", "被讨厌的勇气", {"04-第四夜.md": "# 第四夜\n\n阿德勒的目的论与课题分离。\n"})
    from knowledge_mcp.index import invalidate, search_index
    invalidate()
    hits = search_index("目的论")
    assert any(h["book_id"] == "courage" for h in hits)
```

`mcp/tests/test_retrieve.py`（与检索路标一起钉，可先 assert 该书不出现）:

```python
def test_search_three_schools_does_not_drag_mao(kb):
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["讲话"], ["放了三大炮。" + "啊"*200 + "随大流。"])
    plant_book(kb, "psy", "心理学与生活", "教材。", ["1 生活中的心理学"], ["心理学三大流派行为主义精神分析。"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search
    invalidate()
    out = search("心理学三大流派有什么区别")
    assert "毛泽东选集" not in out
    assert "心理学与生活" in out
```

- [ ] **Step 2: 跑测确认红**  
  `python -m pytest mcp/tests/test_index.py::test_trigram_window_does_not_match_far_bigrams mcp/tests/test_index.py::test_parse_query_keeps_mudilun -q`  
  Expected: FAIL（毛选仍中，或 目的论 被切成 目/论）

- [ ] **Step 3: 最小实现**

`parse_query`：遇到 `FUN_CHARS` 时，若当前 buf 长度为 1、且下一个汉字也是 1 个字就结束或后面还是功能字/非汉字——更简单：**若切开后左侧 buf 是单字、右侧立刻也是单汉字**（看下一个 ch），则把该功能字收入 buf，不 flush。这样「目的论」整段留下。

`_fts_piece`：汉字 len≥2 用 FTS5 短语 `"自卑 卑感"`（连续二字片空格连接，外加双引号），不要 `AND`。

`query_match` / `_match_gate`：`parts = parse_query(q)`，**不要** `_expand_pieces`。可删 `_expand_pieces` 若已无引用。

`search_index` 排序用的 `boost_bits` 改为 `parse_query` 原片，且 **是该书书名子串的语片不参与 name-boost**（书名从该书 `导读.md` 的 title 读；没有就跳过 boost 过滤）。

- [ ] **Step 4: 跑测绿**；再跑全套 `mcp/tests`  
- [ ] **Step 5: Commit** `fix: MATCH 只用原片并改短语邻接`

---

### Task 2: 仅字面淘汰 + 建议块 + 命中分布

**Files:**
- Modify: `mcp/knowledge_mcp/retrieve.py`（`_format_landmarks`、`_why_bits`、`_suggest_lines`）
- Modify: `mcp/knowledge_mcp/index.py`（如需导出 `_df` / 按书查片）
- Test: `mcp/tests/test_retrieve.py`

**Consumes:** Task 1 的原片 MATCH  
**Produces:** 弱仅字面不占 5 格；Q9 建议块含 7 记忆；概要问句建议导读/地图；路标有「命中 N 块」

- [ ] **Step 1: 写失败测试**

```python
def test_literal_only_drops_book_missing_rarest_long(kb):
    plant_book(kb, "adler", "自卑与超越", "阿德勒。", ["第三章 自卑感与优越感"], ["阿德勒说自卑感优越感来自追求。"])
    plant_book(kb, "mao", "毛泽东选集", "著作。", ["讲话"], ["叫做自卑感，越改越卑。没有阿德勒。"])
    _plant_map(kb, "adler", "自卑与超越", ["自卑感是怎么来的"], ["革命"], "第三章 自卑感与优越感")
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search
    invalidate()
    out = search("阿德勒说的自卑感和优越感是怎么来的")
    assert "自卑与超越" in out
    assert "毛泽东选集" not in out


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
    plant_book(kb, "courage", "被讨厌的勇气", "阿德勒。", ["推荐序一 勇气的心理学", "第四夜 要有被讨厌的勇气"], ["序言勇气。", "第四夜正文。"])
    _plant_map(kb, "courage", "被讨厌的勇气", ["总是在意别人是不是讨厌我该怎么办"], ["革命"], "第四夜 要有被讨厌的勇气")
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search
    invalidate()
    out = search("《被讨厌的勇气》大概讲什么")
    assert "被讨厌的勇气" in out
    assert "毛泽东" not in out
    assert "书/courage/导读" in out or "书/courage/地图" in out
    assert out.find("导读") < out.find("推荐序") or "推荐序" not in out


def test_landmark_reports_hit_counts(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章", "第二章"], ["UNIQUE_LIT_TOKEN 甲", "UNIQUE_LIT_TOKEN 乙"])
    from knowledge_mcp.index import invalidate
    from knowledge_mcp.retrieve import search
    invalidate()
    out = search("UNIQUE_LIT_TOKEN")
    assert "命中" in out and "块" in out
    assert "UNIQUE_LIT_TOKEN" not in out.replace("UNIQUE_LIT_TOKEN", "", 0) or "UNIQUE_LIT_TOKEN" not in out
    # 路标无正文：埋的甲乙不能出现
    assert " 甲" not in out and " 乙" not in out
```

（最后一条「无正文」以 `assert "甲" not in out` 即可，token 本身若出现在 why 则 why 只许最长片——本测试用独有英文 token，why 可以含它。改成中文独有句不出现。）

旧测试必须仍绿：`test_quoted_article_keeps_host_book`、`test_pytorch_empty_with_maps`、`test_map_only_life_query`、`test_life_query_keeps_mao_out_even_if_body_has_grams`。

- [ ] **Step 2: 确认红**
- [ ] **Step 3: 最小实现**（只动 `_format_landmarks` 附近）

仅字面淘汰（两路都中 / 仅地图不动）：

1. 在库长片 = `parse_query` 里 len≥3 且 `_df>0` 的原片。≥2 个时，仅字面书必须命中其中 DF 最低的一片（并列取更长）。用 FTS `docs MATCH piece AND book_id=?`，不要全库 AND。
2. 分差：仅字面该书最好 bm25（越小越好）相对**当前路标头名**（both+lit_only 里最好的那本）若 `weak - head > 30` 则丢。单长片问句不因第 1 条丢。
3. 顺序：quoted / life 过滤照旧；然后本淘汰；再截 5 条。

建议块顺序（每本最多 3）：

1. 概要问句（含「大概讲什么」「这本书讲什么」「简介」）：第 1、2 条 `书/<slug>/导读`、`书/<slug>/地图`（文件在才给）；第 3 条可空。
2. 否则地图 `evidence`：左半与问句原文共享 ≥3 字汉字，且这段不是书名子串 → 右半身份最前。`parse_map` 已有 `evidence`。
3. 块名命中问句语片且语片不是书名子串。
4. 其余字面 bm25。

路标加一行 `命中 {n} 块（全库 {m} 块）`，n=该书字面命中块数，m=本次字面命中块总数。why 只用 `parse_query` 原片里最长的那些（不展示三字窗）。

- [ ] **Step 4: 全套 pytest 绿**
- [ ] **Step 5: Commit** `fix: 仅字面淘汰与建议块依据优先`

---

### Task 3: 块内节目录

**Files:**
- Modify: `mcp/knowledge_mcp/retrieve.py`（`_split_part`、`_read_book`、`_neighbors`、`ident_exists` 在 `index.py`）
- Test: `mcp/tests/test_retrieve.py`

**Consumes:** Task 2 路标仍无节清单  
**Produces:** `#短时记忆` / `@偏移` 可读；`#2` 仍是窗；阅读末尾节目录 + 本窗 k/N

- [ ] **Step 1: 写失败测试**

```python
def test_read_section_by_name(kb):
    body = "# 7 记忆\n\n前言若干。\n\n## 短时记忆\n\nSECTION_MARK 短时记忆正文。\n\n## 长时记忆\n\n长时。\n"
    plant_book(kb, "psy", "心理学与生活", "教材。", ["7 记忆"], [body])
    from knowledge_mcp.retrieve import read
    out = read(target="书/psy/7 记忆#短时记忆")
    assert "SECTION_MARK" in out
    assert not out.startswith("失败")
    win2 = read(target="书/psy/7 记忆#2")
    # 短正文只有 1 窗时 #2 夹到末窗，不得把 #短时记忆 当成窗
    named = read(target="书/psy/7 记忆#短时记忆")
    assert "SECTION_MARK" in named


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
```

- [ ] **Step 2: 确认红**
- [ ] **Step 3: 最小实现**

`#` 后纯数字 → 窗（现状）。`#` 后非数字 → 在该块正文里找 ATX 标题，标题文本等于节名（允许含标题符号剥 `#` 后 strip），从该行字符偏移起切 8000。`@数字` → 从该偏移起切 8000。下一窗身份 `@偏移+8000`。找不到节：该项失败交还。

阅读末尾：现有邻块行加上 `本窗 k/N`；再附 `节：标题 @偏移` 若干行（短）。导航件文件名标「不必读」。不进 `kb_search`。

`ident_exists`：剥 `#节名` / `#数字` / `@数字` 后验块文件。

- [ ] **Step 4: 全套 pytest 绿**
- [ ] **Step 5: Commit** `feat: kb_read 按节名和偏移开窗`

---

### Task 4: 真库机械跑题 + 验收记录

**Files:**
- Modify: `检修/验收记录.md`（只追加）
- 不改期望

- [ ] 用 `PYTHONPATH=mcp` 调 `knowledge_mcp.retrieve.search` 跑 Q1–Q14、W1–W16
- [ ] 对照 `docs/本轮Spec.md` §9：Q1/Q5/Q7/Q10 闲书不进；Q9 建议含 7 记忆；Q14 建议含导读或地图；W 组所在书仍在
- [ ] 追加一节到 `检修/验收记录.md`（日期、search_ms、三栏、判定）
- [ ] 记录：本 GUI 须重启 MCP stdio
- [ ] Commit `docs: 追加本轮线上验收记录`

---

## Spec coverage

| Spec | Task |
|---|---|
| §3 三字窗/短语/目的论 | 1 |
| §4 仅字面淘汰 | 2 |
| §5 建议块 | 2 |
| §6 命中分布/why | 2 |
| §7 节目录 | 3 |
| §8 pytest 1–8 | 1–3 |
| §9 真库 | 4 |
| §10 A 先于 B | 任务顺序 |
