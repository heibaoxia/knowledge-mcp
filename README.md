# Knowledge Skill

给 Agent 用的本机资料室。正本是 Markdown。不是给人点的笔记软件，不是 RAG。

仓库：https://github.com/heibaoxia/knowledge-mcp  
这是**引擎**（命令 `knowledge`，MCP 可选）。给人点的入口 Skill 会另开瘦仓库。

## 别人怎么用（打开就能跑）

需要 Python 3.11+。

```bash
git clone https://github.com/heibaoxia/knowledge-mcp.git
cd knowledge-mcp
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -e ./mcp
# Unix:
.venv/bin/python -m pip install -e ./mcp
```

建自己的库目录（不要和代码仓库混也可以）：

```bash
export KNOWLEDGE_ROOT=/path/to/my-library   # Windows: set KNOWLEDGE_ROOT=D:\library
knowledge init
```

把 PDF / EPUB / MOBI 放进 `$KNOWLEDGE_ROOT/原始资料/`，然后：

```bash
knowledge ingest
knowledge lint scan          # 在架 = 库里有什么
knowledge search 你想了解什么
knowledge read 书/<slug>/<章>
```

把 `skills/knowledge/` 拷到本机 Skill 目录（Claude Code / Codex / 其它 Agent 的 skills 根）。Agent 会跑上面这些命令，不需要再配 MCP。

可选：语义检索去硅基流动开 Key，环境变量 `KNOWLEDGE_EMBED_KEY`。没有 Key 也能搜，字面检索照常，向量走本地哈希兜底。

可选 MCP：`knowledge-mcp`（stdio），配置见 `mcp/README.md`。和 CLI 是同一套闸门。

## 依赖（pip 已写进 mcp/pyproject.toml）

- Python ≥ 3.11
- `pyyaml`、`markitdown`、`fastmcp`（MCP 入口用）

入库优先用本机 markitdown 脚本；没有脚本就用已安装的 `markitdown` 包。

## 六件事

| 命令 | 干什么 |
|---|---|
| `knowledge search` | 只回路标，无正文 |
| `knowledge read` | 点名读块 |
| `knowledge ingest` | 收书、切块、骨架地图 + 操作流程 |
| `knowledge note` | 笔记：preview → verify → 写入 |
| `knowledge lint` | 书架 / 加厚地图 / replace 改错字 / 退书 |
| `knowledge inspect` | 自检，不改源码 |

闸门在代码里：检索不带正文、书不能按章删、入库骨架不算入完。

## 许可

MIT，见 `LICENSE`。
