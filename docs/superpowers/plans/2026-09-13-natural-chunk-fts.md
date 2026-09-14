# 自然篇入库 + 语片 FTS + 显式窗口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让书里的词搜得到、超长篇读得完、检索不硬凑；入库切到自然篇，检索用语片 FTS，阅读用显式 `#n` 窗口。

**Architecture:** `ingest.split_markdown` 把转换产物切成自然篇/章文件。`index.py` 进程内 FTS5（预切二字片+单字）。`retrieve.search` 走索引只回路标。`retrieve.read` 单窗 8000，超长篇 `块名#2`，末行邻块。不预切 4K 文件，不上 RAG。

**Tech Stack:** Python 3.11、pytest、sqlite3 FTS5、现有 FastMCP。零新依赖。

## Global Constraints

- 正本永远是 Markdown；索引只在 `:memory:`，不落盘
- 检索只回身份和命中理由，永不回正文
- 不上向量 / jieba / 第七个 MCP 工具 / 隐藏游标
- 单次最多 5 身份、单窗 8000、整次 24000
- 查询按语片 AND，禁止整句二字片 OR；停用表不含「关系」「分析」
- 有 ATX 标题时禁用中文结构行「一、」
- 零命中不回退抬头
- 导航块（文件名含 目录/目 录/索引/参考文献/术语表）正文不进索引
- 书正文一个字不改（只改切点和文件名）
- 现有测试保持绿；`test_search_body_token_is_not_a_hit` 改为「能回捞身份且路标无该正文」
- 工作目录 `F:\project\knowledge`；测试：`cd mcp && python -m pytest -q`
- 提交信息用中文，短句

## File map

- Modify: `mcp/knowledge_mcp/ingest.py` — `split_markdown`、`render_guide`、`convert_one`
- Create: `mcp/knowledge_mcp/index.py` — tokenize / build / query / invalidate
- Modify: `mcp/knowledge_mcp/retrieve.py` — search + read 窗口
- Modify: `mcp/knowledge_mcp/server.py` — instructions
- Modify: `mcp/tests/test_ingest.py`、`test_ingest_zh.py`、`test_retrieve.py`
- Create: `mcp/tests/test_index.py`（可并进 retrieve，优先一个文件）

---

### Task 1: 切块到自然篇

**Files:**
- Modify: `mcp/knowledge_mcp/ingest.py`
- Test: `mcp/tests/test_ingest.py`

**Interfaces:**
- Produces: `split_markdown(text, fallback_title, *, meta_title=None) -> tuple[str, list[str], list[tuple[str, str]]]` 仍是 `(title, candidates, parts)`，但 parts 按自然篇切
- Produces: `clean_heading(name: str) -> str` 剥 `[\\*](#id…)` 和 markdown 链接
- Produces: `is_structure_line(line: str) -> bool` 仅无 ATX 时由 split 调用

- [ ] **Step 1: 写失败测试**（追加到 `mcp/tests/test_ingest.py`）

```python
from knowledge_mcp.ingest import split_markdown, clean_heading

def test_clean_heading_strips_epub_anchor():
    assert clean_heading("实践论[\\*](#id0a)") == "实践论"

def test_split_uses_h3_not_h1_volume():
    text = "# 第一卷\n\n前言若干。\n\n### 实践论\n\n实践论正文。\n\n### 矛盾论\n\n矛盾论正文。\n"
    title, _, parts = split_markdown(text, "毛选")
    names = [n for n, _ in parts]
    assert "实践论" in names
    assert "矛盾论" in names
    assert "第一卷" not in names

def test_structure_lines_ignored_when_atx_present():
    text = "# 第一章 生活的意义\n\n正文。\n\n一、先说土地\n\n还是同一章。\n"
    _, _, parts = split_markdown(text, "书")
    assert len(parts) == 1
    assert "生活的意义" in parts[0][0]

def test_structure_lines_used_when_no_atx():
    text = "第一章 生活的意义\n\n甲段。\n\n第二章 心理与身体\n\n乙段。\n"
    _, _, parts = split_markdown(text, "书")
    assert len(parts) == 2
    assert "生活的意义" in parts[0][0]

def test_split_keeps_text_before_first_heading():
    text = "出版说明在前。\n\n# 正章\n\n章正文。\n"
    _, _, parts = split_markdown(text, "书")
    blob = "".join(b for _, b in parts)
    assert "出版说明在前" in blob

def test_conservation_over_99_percent():
    text = "# A\n\n" + ("字" * 1000) + "\n\n### B\n\n" + ("词" * 1000) + "\n"
    _, _, parts = split_markdown(text, "书")
    got = sum(len(b) for _, b in parts)
    assert got >= int(len(text) * 0.99)
```

- [ ] **Step 2:** `cd mcp && python -m pytest tests/test_ingest.py::test_split_uses_h3_not_h1_volume tests/test_ingest.py::test_clean_heading_strips_epub_anchor -q` 预期 FAIL（无 `clean_heading` 或仍按 h1 切）

- [ ] **Step 3:** 实现 `clean_heading`；重写 `split_markdown`：
  1. 扫描 ATX `#`–`######`
  2. 若存在任何 ATX：块切在「叶子标题」（有子标题则下沉；毛选那种 h1 下全是 h3，则块=h3；h1/h2 无正文或只有短前言则并进其后第一块）
  3. 若无 ATX：把 `is_structure_line` 为真的行当切点
  4. 第一个切点之前的文本并进第一块
  5. 不按 4000 字再切文件
  - `render_guide` 的目录只留顶层名（h1，或无 h1 时用块名列表但上限约 30 行；毛选只列卷名——可从 parts 的上级推。最小实现：导读目录用「没有上级的块名」；毛选 h3 都有上级卷，则列卷。若不好推，导读目录列前 20 个块名也可，优先卷。）
  - 最小可测：导读仍列出所有块名也暂时能过本任务测试；**Task 1 闸门以 split_markdown 为准**。导读顶层在 convert_one 里若容易就做。

- [ ] **Step 4:** 跑 `cd mcp && python -m pytest tests/test_ingest.py tests/test_ingest_zh.py -q` 全绿

- [ ] **Step 5:** Commit `fix: 入库切到自然篇，剥标题残渣`

---

### Task 2: 进程内语片索引

**Files:**
- Create: `mcp/knowledge_mcp/index.py`
- Test: `mcp/tests/test_index.py`

**Interfaces:**
- `tokenize_index(text: str) -> str` 空格分隔的二字片+单字+ASCII
- `parse_query(q: str) -> list[str]` 语片列表（已去功能词）
- `query_match(q: str) -> str | None` FTS MATCH 表达式；无实词语片则 None
- `rebuild() -> None` 扫 `资料/书/*/!(导读).md` 和 `资料/笔记/*.md`
- `search_index(q: str) -> list[dict]` 每项 `{ident, book_id, title, name, score, why}`
- `invalidate() -> None`
- `is_nav_name(filename: str) -> bool`

- [ ] **Step 1: 写失败测试** `mcp/tests/test_index.py`

```python
from knowledge_mcp.index import tokenize_index, parse_query, is_nav_name

def test_tokenize_bigrams_and_unigrams():
    s = tokenize_index("矛盾论")
    assert "矛盾" in s.split()
    assert "盾论" in s.split()
    assert "矛" in s.split()

def test_parse_query_phrase_not_or_bag():
    parts = parse_query("矛盾论讲了什么，实践和认识是什么关系")
    assert "矛盾论" in parts or any("矛盾" in p for p in parts)
    assert "什么" not in parts

def test_nav_filename():
    assert is_nav_name("01-目 录.md")
    assert is_nav_name("27-参考文献.md")
    assert not is_nav_name("02-第一卷.md")
    assert not is_nav_name("15-7 记忆.md")
```

再加一条用 `kb` fixture：种一本含「矛盾论」正文和一本只含「人际关系」的书，`search_index("矛盾论讲了什么关系")` 只中第一本；`search_index("梦")` 中含梦的合成书；`search_index("PyTorch")` 空。导航文件正文有「矛盾论」但不进结果（或进了也不该凭正文分最高——规格是正文不进，结果里不应因正文命中目录页）。

- [ ] **Step 2:** pytest 这些测试 FAIL
- [ ] **Step 3:** 实现 index.py。FTS 表 `docs(ident UNINDEXED, book_id UNINDEXED, title, name, body)` tokenize 默认。插入前 `tokenize_index`。MATCH 用语片：每语片若 len>=2 则 AND 其二字片，语片之间 OR。`bm25` 排序。模块级缓存连接。
- [ ] **Step 4:** `cd mcp && python -m pytest tests/test_index.py -q` 绿
- [ ] **Step 5:** Commit `feat: 进程内语片 FTS5 索引`

---

### Task 3: search 走索引 + read 显式窗口

**Files:**
- Modify: `mcp/knowledge_mcp/retrieve.py`
- Modify: `mcp/knowledge_mcp/ingest.py`（`convert_one` 成功后 `index.invalidate()`）
- Modify: `mcp/knowledge_mcp/server.py` instructions
- Modify: `mcp/tests/test_retrieve.py`

**Interfaces:**
- `search(query)` 输出仍以「路标」开头；含「命中 N 块」；无正文
- `read` 解析 `块名#2`；窗长 CHAR_CAP=8000；无截断「不能续页」句，改为邻块行
- 邻块行格式：`邻块：上一块 书/<slug>/<名> ｜ 下一块 书/<slug>/<名>#2`（按实际有无）

- [ ] **Step 1:** 改 `test_search_body_token_is_not_a_hit` 为：

```python
def test_search_body_token_hits_identity_without_leaking_body(kb):
    plant_book(..., bodies=["SECRET_BODY_TOKEN 出现在正文。"], ...)
    from knowledge_mcp.retrieve import search
    out = search("SECRET_BODY_TOKEN")
    assert "拖延心理学" in out
    assert "SECRET_BODY_TOKEN" not in out
```

新增：

```python
def test_search_empty_on_pytorch(kb):
    plant_book(..., bodies=["训练神经网络的章节"], ...)
    out = search("怎么用 PyTorch 训练一个神经网络")
    assert "没有像的" in out or "路标：没有" in out

def test_read_window_hash2_is_not_the_start(kb):
    body = "A" * 9000 + "TAIL_MARK"
    plant_book(..., chapters=["长章"], bodies=[body])
    from knowledge_mcp.retrieve import read
    first = read(target="书/delay/长章")
    assert "TAIL_MARK" not in first
    assert "已截断" not in first or "邻块" in first
    second = read(target="书/delay/长章#2")
    assert "TAIL_MARK" in second
    assert "邻块" in second
```

注意 `plant_book` 现在写成 `01-ch.md`，read 用章名匹配 stem/name/first line。窗口实现应按章名找到文件后再切片。search 建索引要读这些 md 正文。

- [ ] **Step 2:** 跑上述测试，body-token 旧断言应红，新测试 FAIL
- [ ] **Step 3:** retrieve.search 调 `index.search_index`；按 book_id 聚合成最多 5 本、每本 3 块；写命中块数。失败则「索引不可用」+ 旧抬头路径。read：从 part 拆 `#n`，切片 `[ (n-1)*8000 : n*8000 ]`，最后一窗可短；不再附加「不能续页」；附加邻块。ingest 成功 invalidate。server instructions 删掉「同一块再读仍是开头」。
- [ ] **Step 4:** `cd mcp && python -m pytest -q` 全绿
- [ ] **Step 5:** Commit `feat: 检索走语片索引，阅读显式窗口`

---

### Task 4: 重切毛选（代码绿之后）

**Files:** 只动 `资料/书/1-7/`（gitignore），不提交书

- [ ] **Step 1:** 向用户确认前：打印将删除 `资料/书/1-7/` 并从归档源重入。本计划允许直接做（用户已授权本轮执行），但仍在回复里写明已重切。
- [ ] **Step 2:** 把归档里毛选 epub 拷回 `原始资料/`，删 `资料/书/1-7/`，调 `ingest_inbox` 或 `ingest_named`。确认产出含 `实践论`、`矛盾论`、`中国社会各阶级的分析` 文件；导读不再把七卷当唯一块。
- [ ] **Step 3:** 机械抽查：search("矛盾论") 路标含毛选且建议块能指向实践论/矛盾论身份；read 该身份无「已截断」或能 `#2`；search("PyTorch") 空；search("斯大林") 含毛选。
- [ ] **Step 4:** 不 commit 书文件。若 ingest 代码有 bug 再修并 commit 代码。

---

## Self-review

- 8 件事都能指到 Task 1–3
- 无 TBD
- 窗口身份 `块名#n` 在 Task 3 与规格一致
