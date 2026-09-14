# 书级地图 + 两路三栏 + lint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 入库必须有合格书级 `地图.md`；`kb_search` 字面+地图两路都跑，路标三栏（两路都中 / 仅字面 / 仅地图），重合由代码按身份算；lint 扫地图死链与重切过期；已有 4 本书补地图；线上记 Q13/Q14。

**Architecture:** 地图解析/校验放进现有 `index.py`（`ingest` 已要 import `invalidate`，不再新开模块）。`index._ensure` 跳过 `地图.md` 当正文块，另插 `kind=地图` 行（ident=`书/<slug>`，body=能解决什么+建议从哪读）。`retrieve.search` 跑 `search_index` + `search_maps`，按书 ident 分三栏，上限 5。lint 仍走 `kb_lint_notes`，apply 允许改 `书/<slug>/地图`，拒绝书正文。无新 MCP 工具、无新文件、无新依赖、不上向量。

**Tech Stack:** Python 3.11、pytest、sqlite3 FTS5 `:memory:`、现有 FastMCP。零新依赖。

## Global Constraints

- 正本永远是 Markdown；索引只在 `:memory:`，不落盘
- 检索只回身份和命中理由，永不回正文；路标总共最多 5 条
- 不上向量 / jieba / 第七个 MCP 工具 / 隐藏游标 / wiki 代替原文
- 单次最多 5 身份、单窗 8000、整次 24000；这些顶本轮不改
- 两路都跑，不平均分，不「先语义再字面」当唯一路径；重合按身份用代码算，不把两份名单丢给 Agent
- 地图是派生物：YAML `type: 地图`、`generated: true`；抬头（书名）来自导读；点名阅读的是原文（Q14 可读地图/导读）
- 字面通道不把 `地图.md` 当正文块；`kb_read 书/<slug>/地图` 可读
- 入库未写出合格地图 → 这本不算入完，回报标明「缺地图」，源文件可已归档
- 拉丁专名两路都无 → 空（Q6 PyTorch）；中文生活题（含「怎么办」「我总是」）两路都弱也要给最像的仅地图，不许装没有
- 问句偏置只改排序：带怎么办/我总是/处境 → 地图栏靠前；否则字面栏靠前。不删通道
- 净化动笔记和地图，不动书正文；不新开第七扇门
- `convert_one` 成功写入后必须 `invalidate()`（补漏，不当新功能）
- 给已有 4 本书补地图时禁止改原文（只新增 `地图.md`）
- 现有约 91–93 项测试保持绿；工作目录 `F:\project\knowledge`；测试：`cd mcp && python -m pytest -q`
- 提交信息用中文短句；不要 `git checkout/reset/stash` 丢别人的改动
- 马尾辫 full：最短能用、不新依赖、不预留抽象

## File map

- Modify: `mcp/knowledge_mcp/index.py` — 解析/校验地图；跳过 `地图.md` 正文；建 `kind=地图` 行；`search_maps`；`latin_blocked`
- Modify: `mcp/knowledge_mcp/ingest.py` — `convert_one` 调 `invalidate()`；回报缺地图
- Modify: `mcp/knowledge_mcp/retrieve.py` — 两路合并三栏；`kb_read` 地图；文件列表排除地图
- Modify: `mcp/knowledge_mcp/notes.py` — scan 地图死链/过期/笔记 sources 死链；apply 可改地图
- Modify: `mcp/knowledge_mcp/server.py` — instructions / `kb_search` / `kb_lint_notes` 说明含三栏与地图
- Test: `mcp/tests/test_index.py`、`test_ingest.py`、`test_retrieve.py`、`test_lint.py`（校验测试放 `test_index.py`，不新开测试文件除非真放不下）
- Content: `资料/书/<slug>/地图.md` × 4（不改其它 md）
- Append: `检修/验收记录.md`

## Interfaces（后续任务只认这些名字）

```python
# index.py（地图函数也放这里，禁止新建 bookmap.py）
MAP_FILE = "地图.md"
SKIP_FILES = frozenset({"导读.md", "地图.md"})

def parse_map(text: str) -> dict:
    # {title, type, book, generated, solves: list[str], not_solves: list[str],
    #  suggest: list[str], evidence: list[str], errors: list[str]}
def ident_exists(ident: str) -> bool: ...
def map_problems(book_dir: Path) -> list[str]: ...
def map_index_text(text: str) -> str:
    # 能解决什么 + 建议从哪读，供 FTS；不含「不解决什么」
def search_index(q: str) -> list[dict]:  # 仅字面；kind in {书,笔记}；不含地图正文
def search_maps(q: str) -> list[dict]:
    # {ident: "书/<slug>", book_id, kind: "书", suggest: list[str], why: list[str], score}
def latin_blocked(q: str) -> bool: ...
def invalidate() -> None: ...

# retrieve.py
def search(query: str) -> str:  # 三栏路标
def read(...):  # part=地图 与 导读 同类
```

路标形状（空栏省略；全局最多 5 条；两路都中优先占名额）：

```text
路标（无正文）
两路都中（优先）：
1. [书] 标题  身份：书/<slug>
   建议块：
   · 书/<slug>/<块>
   字面：含「…」；地图：能解决「…」
仅字面：
2. ...
仅地图：
3. ...
```

重合键：同一 `书/<slug>/<块>` **或** 同一本 `书/<slug>`（实现按 `book_id` 分组：一书字面命中任一块且该书地图命中 → 两路都中）。笔记只有字面。

---

### Task 1: 地图校验 + 入库缺地图 + invalidate + 读地图 + 字面不索引地图

**Files:**
- Modify: `mcp/knowledge_mcp/ingest.py`（`convert_one` 末尾、`ingest_sources` 回报）
- Modify: `mcp/knowledge_mcp/index.py`（解析/校验 + glob 跳过 `地图.md`）
- Modify: `mcp/knowledge_mcp/retrieve.py`（`_read_book` 认地图；章节文件排除地图）
- Test: 追加 `mcp/tests/test_index.py`、`test_ingest.py`、`test_retrieve.py`

**Interfaces:**
- Produces: `parse_map` / `map_problems` / `ident_exists` / `map_index_text`（均在 `index.py`）；`convert_one` 返回多 `map_ok: bool`；`invalidate()` 在成功写入后调用

- [ ] **Step 1: 写失败测试** 追加到 `mcp/tests/test_index.py`

```python
from pathlib import Path

from knowledge_mcp.index import ident_exists, map_problems, parse_map


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
    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    (d / "地图.md").write_text(VALID, encoding="utf-8")
    assert map_problems(d) == []
    p = parse_map(VALID)
    assert p["title"] == "拖延心理学"
    assert 3 <= len(p["solves"]) <= 8
    assert ident_exists("书/delay/第一章 为什么拖")


def test_missing_map_is_problem(kb):
    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    probs = map_problems(d)
    assert any("缺" in x for x in probs)


def test_dead_ident_is_problem(kb):
    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    bad = VALID.replace("书/delay/第一章 为什么拖", "书/delay/不存在的章")
    (d / "地图.md").write_text(bad, encoding="utf-8")
    probs = map_problems(d)
    assert any("不存在" in x or "死" in x for x in probs)


def test_title_must_match_guide(kb):
    d = _guide(kb, "delay", "拖延心理学", ["第一章 为什么拖"])
    (d / "地图.md").write_text(VALID.replace("title: 拖延心理学", "title: 编的书名"), encoding="utf-8")
    assert map_problems(d)
```

追加 `mcp/tests/test_ingest.py`：

```python
def test_inbox_reports_missing_map(kb, monkeypatch):
    _patch_convert(monkeypatch)
    drop_source(kb, "delay.epub")
    from knowledge_mcp.ingest import ingest_inbox

    out = ingest_inbox()
    assert not out.startswith("失败")
    assert "缺地图" in out
    slugs = list((kb / "资料" / "书").iterdir())
    assert slugs and not (slugs[0] / "地图.md").is_file()


def test_convert_one_calls_invalidate(kb, monkeypatch):
    _patch_convert(monkeypatch)
    called = []
    monkeypatch.setattr("knowledge_mcp.ingest.invalidate", lambda: called.append(1))
    src = drop_source(kb, "delay.epub")
    from knowledge_mcp.ingest import convert_one

    convert_one(src)
    assert called
```

追加 `mcp/tests/test_index.py`：

```python
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
```

追加 `mcp/tests/test_retrieve.py`：

```python
def test_read_map_by_ident(kb):
    plant_book(kb, "delay", "拖延心理学", "教材。", ["第一章"], ["章正文"])
    (kb / "资料" / "书" / "delay" / "地图.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 地图\ngenerated: true\n---\n\n地图短文 MAP_ONLY_MARK\n",
        encoding="utf-8",
    )
    from knowledge_mcp.retrieve import read

    out = read("书/delay/地图")
    assert "MAP_ONLY_MARK" in out
    assert not out.startswith("失败")
    chap = read("书/delay/第一章")
    assert "MAP_ONLY_MARK" not in chap
    assert "邻块" in chap
    assert "地图" not in chap.split("邻块")[-1]
```

- [ ] **Step 2: 跑测试确认红**

```
cd mcp && python -m pytest tests/test_index.py::test_parse_and_ok tests/test_index.py::test_missing_map_is_problem tests/test_index.py::test_dead_ident_is_problem tests/test_index.py::test_title_must_match_guide tests/test_ingest.py::test_inbox_reports_missing_map tests/test_ingest.py::test_convert_one_calls_invalidate tests/test_index.py::test_map_file_not_in_literal_index tests/test_retrieve.py::test_read_map_by_ident -q
```

预期：FAIL（无 `parse_map`/`map_problems` 或没有「缺地图」/没调 invalidate / 地图被当块 / 读地图失败）

- [ ] **Step 3: 最小实现**

`index.py` 地图校验要点（不要新建 `bookmap.py`）：

- YAML 必须 `type: 地图`、`generated: true`、`book: 书/<slug>`；`title` 与同目录 `导读.md` 的 title 一致
- 四个 `##` 段：能解决什么 3–8 条每条 ≤40 字；不解决什么 1–5 条；建议从哪读、依据块 均为真实身份
- 每条「能解决什么」在依据块里至少挂一个身份（行里出现该条原文或按顺序 zip 也可；**按行包含 `书/` 身份，且条数 ≥ 能解决什么条数**）
- `ident_exists`：`书/<slug>/导读`、`书/<slug>/地图`、`书/<slug>/<block_name>`、`笔记/<slug>`；块名用 `^\d+-` 剥序号，与 `index._block_name` 相同规则（本文件自备 4 行，避免和 index 循环 import）
- `map_index_text`：只拼「能解决什么」+「建议从哪读」正文

`ingest.convert_one`：文件写完后 `from knowledge_mcp.index import invalidate`（模块顶 `from knowledge_mcp.index import invalidate`），调用 `invalidate()`；返回值加 `map_ok: not map_problems(book_dir)`（此时通常 False）。

`ingest_sources`：成功列表仍可列出导读路径；另写 `缺地图 N 本（源文件已归档，不算入完；补 资料/书/<slug>/地图.md）`。不要把整单改成 `失败` 开头（旧测试 `not out.startswith("失败")`）。

`index._ensure`：`if p.name in ("导读.md", "地图.md"): continue`（本任务先不插地图行）。

`retrieve._read_book`：`name in ("地图", "地图.md")` 与导读同样读文件+窗口；`files` 排除 `导读.md` 与 `地图.md`。

- [ ] **Step 4: 跑本任务测试 + 全套**

```
cd mcp && python -m pytest tests/test_ingest.py tests/test_index.py tests/test_retrieve.py -q
cd mcp && python -m pytest -q
```

预期：全绿

- [ ] **Step 5: Commit** `fix: 书级地图校验，入库缺地图不算入完，索引跳过地图`

---

### Task 2: 两路检索 + 三栏路标

**Files:**
- Modify: `mcp/knowledge_mcp/index.py` — 插 `kind=地图` 行；`search_maps`；`latin_blocked`；`search_index` 过滤 `kind != '地图'`
- Modify: `mcp/knowledge_mcp/retrieve.py` — `search()` 两路合并
- Modify: `mcp/knowledge_mcp/server.py` — instructions 写三栏
- Test: `mcp/tests/test_retrieve.py`、`mcp/tests/test_index.py`

**Interfaces:**
- Consumes: `map_index_text`、`parse_map`、`MAP_FILE`
- Produces: `search_maps`、`latin_blocked`、三栏 `search()`

- [ ] **Step 1: 写失败测试** 追加到 `mcp/tests/test_retrieve.py`

```python
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
    assert "课题分离" not in out  # 路标不靠问句术语；块名第三夜不含该词


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


def test_life_fallback_still_returns_map(kb):
    """字面撞不上、地图 FTS 也弱时，生活题仍给最像仅地图。"""
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
```

追加 `mcp/tests/test_index.py`：

```python
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
    assert all(h.get("kind") != "地图" for h in search_index("讨厌")) or True
    lit = search_index("讨厌")
    assert all("/地图" not in h["ident"] for h in lit)
```

旧测试仍要绿：`test_search_empty_is_honest`（「量子场论」、无地图）必须仍空——**生活题兜底只在问句含「怎么办」或「我总是」且 `latin_blocked` 为假时启用**。不要把所有中文空结果都改成硬凑地图。

- [ ] **Step 2: 跑红**

```
cd mcp && python -m pytest tests/test_retrieve.py::test_three_columns_overlap_by_book tests/test_retrieve.py::test_map_only_life_query tests/test_retrieve.py::test_pytorch_empty_with_maps -q
```

预期：FAIL（无三栏 / 无 `search_maps`）

- [ ] **Step 3: 最小实现**

`index._ensure` 在每本书块循环之后：

```python
mp = guide.parent / "地图.md"
if mp.is_file():
    raw = mp.read_text(encoding="utf-8")
    blob = map_index_text(raw)
    parsed = parse_map(raw)
    suggest = " ".join(parsed.get("suggest") or [])
    con.execute(
        "INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
        (f"书/{slug}", slug, "地图", suggest, tokenize_index(title),
         tokenize_index(suggest), tokenize_index(blob)),
    )
```

`search_index` 的 SELECT 加 `AND kind != '地图'`。

`search_maps`：复制 `search_index` 的 MATCH/`latin` 门，但 `kind = '地图'`；每项 `ident=书/{slug}`，`suggest` 从 `parse_map` 的 suggest 列（label 里存了空格拼的身份，再 `split` 或读文件）。**读文件更稳**：命中后打开该本 `地图.md` 取 suggest。why 用问句语片里出现在 blob 中的前几个。

`latin_blocked(q)`：`parse_query` 里任一 ASCII 语片 `_df==0` → True（与现 `search_index` 拉丁门一致）。

`retrieve.search`：

1. 空问句仍 fail
2. `lit = search_index(q)`（try/except 仍可退化抬头，抬头结果算仅字面）
3. `mp = search_maps(q)`
4. 若两边空：
   - `latin_blocked(q)` → 现有空文案
   - 生活题（`怎么办` 或 `我总是` 在问句里）→ 对每本合格地图，用问句汉字二字片在 `map_index_text` 里计数，取计数 > 0 的最高一本当仅地图；全 0 仍空
   - 其它（如 量子场论）→ 空
5. 按 `book_id`（笔记用笔记 slug）分三集合：两路都中 / 仅字面 / 仅地图
6. 排序：两路都中始终最前；若生活题，接着仅地图再仅字面，否则仅字面再仅地图；栏内保持各路原序
7. 截 5 条；格式见 Interfaces；建议块：字面最多 3 个 ident，仅地图用地图 suggest 最多 3 个（必须是原文身份，不是 `书/slug/地图` 当建议正文）
8. `log_call(..., search_ms=..., both=n, lit=n, map=n)`（`time.perf_counter`）

不要把两路分数加起来再排一个榜。不要输出正文。

`server.py` instructions 加一句：`路标分三栏：两路都中 / 仅字面 / 仅地图。`

- [ ] **Step 4:** `cd mcp && python -m pytest -q` 全绿

- [ ] **Step 5: Commit** `feat: 检索两路并行，路标三栏由代码标重合`

---

### Task 3: lint 地图死链 / 过期；apply 可改地图

**Files:**
- Modify: `mcp/knowledge_mcp/notes.py` — `_scan`、`_apply`、`_touches_book`
- Modify: `mcp/knowledge_mcp/server.py` — `kb_lint_notes` docstring：动笔记和地图，不动书正文
- Test: `mcp/tests/test_lint.py`

**Interfaces:**
- Consumes: `map_problems`、`ident_exists`
- 不新开工具；`op` 笔记仍 `delete/update/merge`；地图 `update`（写 markdown）或 `stale`（YAML `stale: true`）

- [ ] **Step 1: 失败测试** 追加 `mcp/tests/test_lint.py`

```python
def test_scan_flags_map_dead_link(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    (d / "地图.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 地图\nbook: 书/delay\ngenerated: true\n---\n\n"
        "## 能解决什么\n- 总是拖怎么办啊这个问题要短\n- 想改却推后怎么办呢短句\n- 一难就玩手机怎么办短\n\n"
        "## 不解决什么\n- PyTorch\n\n"
        "## 建议从哪读\n- 书/delay/没有这一章\n\n"
        "## 依据块\n- 总是拖怎么办啊这个问题要短 → 书/delay/没有这一章\n"
        "- 想改却推后怎么办呢短句 → 书/delay/没有这一章\n"
        "- 一难就玩手机怎么办短 → 书/delay/没有这一章\n",
        encoding="utf-8",
    )
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "地图" in out
    assert "没有这一章" in out or "死" in out or "不存在" in out


def test_scan_flags_stale_map(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    import time

    (d / "地图.md").write_text(
        "---\ntitle: 拖延心理学\ntype: 地图\nbook: 书/delay\ngenerated: true\n---\n\n"
        "## 能解决什么\n- 总是拖到截止日期前一晚怎么办\n- 明明想改却往后推怎么办\n- 工作一难就刷手机怎么办\n\n"
        "## 不解决什么\n- 怎么用 PyTorch\n\n"
        "## 建议从哪读\n- 书/delay/正文\n\n"
        "## 依据块\n- 总是拖到截止日期前一晚怎么办 → 书/delay/正文\n"
        "- 明明想改却往后推怎么办 → 书/delay/正文\n"
        "- 工作一难就刷手机怎么办 → 书/delay/正文\n",
        encoding="utf-8",
    )
    time.sleep(0.05)
    (d / "正文.md").write_text("原书不可改。又重切了。\n", encoding="utf-8")
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("scan")
    assert "stale" in out.lower() or "过期" in out or "早于" in out or "重切" in out


def test_apply_map_update_does_not_touch_body(kb):
    plant_book(kb)
    d = kb / "资料" / "书" / "delay"
    good = (
        "---\ntitle: 拖延心理学\ntype: 地图\nbook: 书/delay\ngenerated: true\n---\n\n"
        "## 能解决什么\n- 总是拖到截止日期前一晚怎么办\n- 明明想改却往后推怎么办\n- 工作一难就刷手机怎么办\n\n"
        "## 不解决什么\n- 怎么用 PyTorch\n\n"
        "## 建议从哪读\n- 书/delay/正文\n\n"
        "## 依据块\n- 总是拖到截止日期前一晚怎么办 → 书/delay/正文\n"
        "- 明明想改却往后推怎么办 → 书/delay/正文\n"
        "- 工作一难就刷手机怎么办 → 书/delay/正文\n"
    )
    import json
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", json.dumps([{"op": "update", "target": "书/delay/地图", "markdown": good}], ensure_ascii=False))
    assert not out.startswith("失败"), out
    assert "原书不可改" in (d / "正文.md").read_text(encoding="utf-8")
    assert (d / "地图.md").is_file()


def test_apply_chapter_still_rejected(kb):
    plant_book(kb)
    from knowledge_mcp.notes import lint_notes

    out = lint_notes("apply", '[{"op":"delete","target":"书/delay/正文"}]')
    assert out.startswith("失败")
    assert "原书不可改" in (kb / "资料" / "书" / "delay" / "正文.md").read_text(encoding="utf-8")
```

`test_apply_book_rejects_whole_plan` 仍必须绿（`书/delay` 整本拒绝）。

- [ ] **Step 2: 跑红** `cd mcp && python -m pytest tests/test_lint.py -q`

- [ ] **Step 3: 实现**

`_map_ident(raw) -> Path | None`：规范化后匹配 `书/<slug>/地图`。

`_touches_book`：地图身份返回 False；其它 `书/` 仍 True。

`_scan`：原笔记扫描 + 每本 `map_problems` + 若 `地图.md` mtime < 同目录块文件（排除导读/地图）最大 mtime → 标「早于重切」；笔记 YAML `sources` 里 `ident_exists` 为假 → 死链。清单结尾改成「只许笔记和地图，不动书正文」。

`_apply`：目标要么笔记要么地图；`op` 对地图仅 `update`/`stale`。`update` 写入后跑 `map_problems`，有问题则整单拒绝并尽量不留下半份（先写到内存校验，通过再落盘）。成功后 `invalidate()`。`stale`：在 YAML 加 `stale: true`。

- [ ] **Step 4:** `cd mcp && python -m pytest -q` 全绿

- [ ] **Step 5: Commit** `feat: lint 扫地图死链与过期，apply 只许改地图派生`

---

### Task 4: 给已有 4 本书补书级地图（不改原文）

**Files:** 只新增

- `资料/书/book-fe981a7a/地图.md` 被讨厌的勇气
- `资料/书/book-2cde2fad/地图.md` 自卑与超越
- `资料/书/19-psychology-and-life-richard-gerrig-etc/地图.md` 心理学与生活
- `资料/书/1-7/地图.md` 毛泽东选集

**禁止：** 改任何 `导读.md`、章节 md、YAML 书名/章名。

**身份必须真实存在**（`block_name` 剥序号后）：

| slug | 书名（必须与导读 title 逐字相同） | 建议块（至少这些） |
|---|---|---|
| book-fe981a7a | 被讨厌的勇气：“自我启发之父”阿德勒的哲学课 | `第三夜 让干涉你生活的人见鬼去` `第四夜 要有被讨厌的勇气` `第二夜 一切烦恼都来自人际关系` |
| book-2cde2fad | 自卑与超越（西方心理学大师经典译丛） | `第三章 自卑感与优越感` `第四章 早期记忆` `第五章 梦` |
| 19-psychology-and-life-richard-gerrig-etc | （导读 title 全文） | `7 记忆` `5 心理、意识和其他状态` `13 理解人类人格` |
| 1-7 | 毛泽东选集 | `实践论` `矛盾论` `中国社会各阶级的分析` |

被讨厌的勇气「能解决什么」必须含提问者口语，例如「总是在意别人是不是讨厌我该怎么办」，**不要把「课题分离」当唯一表述**（问句侧测试禁止出现该词，地图侧可以在依据里指向第三夜）。毛选「不解决什么」必须含「个人怕被讨厌怎么办」「怎么用 PyTorch」。心理学/自卑不要写 PyTorch 进「能解决什么」。

- [ ] **Step 1: 测试** `mcp/tests/test_real_maps.py`（跳过若目录不存在，方便无书环境；本仓库有书应执行）

```python
from pathlib import Path
import pytest
from knowledge_mcp.index import map_problems
from knowledge_mcp.paths import repo_root

BOOKS = [
    "book-fe981a7a",
    "book-2cde2fad",
    "19-psychology-and-life-richard-gerrig-etc",
    "1-7",
]

@pytest.mark.parametrize("slug", BOOKS)
def test_real_book_map_ok(slug):
    d = repo_root() / "资料" / "书" / slug
    if not d.is_dir():
        pytest.skip("no book")
    assert map_problems(d) == []
```

另：本仓库下用 `KNOWLEDGE_ROOT` 不指向 tmp 时，

```python
def test_q13_query_hits_courage_not_mao():
    # 仅当四本都在 repo_root 且本测试未设 KNOWLEDGE_ROOT 到 tmp
    ...
```

不要在 `kb` fixture 测试里打真库。Q13 真库检索放到 Task 5。本任务 `test_real_book_map_ok` 用 `repo_root()`，conftest 的 `kb` 会 setenv——**不要依赖 `kb` fixture**，该测试无 `kb` 参数。

- [ ] **Step 2: 跑红**（无地图文件）

- [ ] **Step 3: 写四份 `地图.md`**，每份 `map_problems==[]`。写完用 Python 扫一次身份。标题从各书 `导读.md` 复制，不要改导读。

被讨厌的勇气「能解决什么」示例（可微调但必须能被二字片碰到「讨厌」「别人」）：

- 总是在意别人是不是讨厌我该怎么办
- 怕被别人讨厌还想做自己怎么办
- 别人看我不顺眼时要不要改自己
- 人际关系里总寻求认可怎么办
- 别人的课题和我的课题怎么分开

- [ ] **Step 4:** `cd mcp && python -m pytest -q` 全绿

- [ ] **Step 5: Commit** `docs: 四本书级地图（派生，不改原文）`

---

### Task 5: 全套闸门 + 线上 Q13/Q14 验收记录

**Files:**
- Append only: `检修/验收记录.md`
- 不改 `docs/验收标准.md` 期望

- [ ] **Step 1:** `cd mcp && python -m pytest -q` 必须全绿。记下 passed 数。

- [ ] **Step 2: 真库检索**（不要设 `KNOWLEDGE_ROOT`；cwd 任意，代码 `repo_root()` 指向仓库）

```
cd mcp && python -c "
from knowledge_mcp.index import invalidate
from knowledge_mcp.retrieve import search, read
import time
invalidate()
q13='我总是很在意别人是不是讨厌我，该怎么办'
assert '课题分离' not in q13 and '阿德勒' not in q13
t=time.perf_counter(); s13=search(q13); ms13=int((time.perf_counter()-t)*1000)
q14='《被讨厌的勇气》大概讲什么'
t=time.perf_counter(); s14=search(q14); ms14=int((time.perf_counter()-t)*1000)
print('---Q13---', ms13, len(s13)); print(s13)
print('---Q14---', ms14, len(s14)); print(s14)
"
```

然后按路标 **最多读 2 块**：Q13 读建议块 1 个原文；Q14 **只读** `书/book-fe981a7a/导读` 或 `书/book-fe981a7a/地图` 之一，禁止读五夜全文。

判定：

- Q13：路标含被讨厌的勇气；不含毛泽东选集；问句未出现课题分离/阿德勒
- Q14：读块 ≤2 且含导读或地图；路标无正文
- Q6：再搜一次「怎么用 PyTorch 训练一个神经网络」必须空

- [ ] **Step 3: 追加** `检修/验收记录.md`（不覆盖基线）一节：

```
## 2026-09-14 第 1 轮（地图+三栏）

| 题 | 路标字 | search_ms | 读块 | 读总字 | 轮次 | 都中/仅字/仅地图 | 判定 |
|---|---|---|---|---|---|---|---|
| Q13 |  |  |  |  |  |  |  |
| Q14 |  |  |  |  |  |  |  |
| Q6  |  |  | 0 | 0 | 1 |  | 必须空 |
```

若某条未过：判定写「差在哪」，**不许改** `docs/验收标准.md`。

- [ ] **Step 4: Commit** `docs: 追加 Q13/Q14 验收记录`

---

## Spec coverage

| Spec | Task |
|---|---|
| §3 书级地图四段、YAML、身份真实、缺地图不算入完 | 1, 4 |
| `kb_read` 地图、字面不把地图当正文 | 1–2 |
| §4 两路都跑、三栏、重合代码算、建议块是原文、问句偏置、Q6 空、生活题不空 | 2, 5 |
| §5 lint 死链/过期、不动书正文、不新开门 | 3 |
| §6 验收记录字段 | 5 |
| §7 Q13/Q14 | 4–5 |
| `convert_one` invalidate | 1 |
| 篇级地图 | **不做** |
| 向量/第七工具/改原文 | **不做** |

## 不要做

- 新平级 MCP 工具写地图
- 用 LLM 在 `convert_one` 里自动编地图（本轮由校验+缺地图回报+人工/Agent 落 `地图.md`）
- 改 `search_index` 为「先地图后字面」单通道
- 让 Agent 对两份名单
- 把「量子场论」这类非生活中文空查询改成硬凑
