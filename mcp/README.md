# Knowledge Skill（代码包）

给 Agent 用的本机资料室。**默认入口是命令 `knowledge`**，不必配 MCP。规格见仓库根 `需求.md`。MCP（`knowledge-mcp`）仍可用，闸门同一套。

六扇门：检索（+阅读）、收件箱入库、指定入库、写笔记、净化、自检。正本是 Markdown，不用数据库。

## 安装（仓库根目录）

官方 PyPI 若 SSL 失败，用清华镜像：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -U pip wheel -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
.venv/Scripts/python -m pip install -e ./mcp -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

入库转换走本机的 markitdown 脚本，程序按这个顺序找：
环境变量 `KNOWLEDGE_MARKITDOWN` → `~/.claude/skills/markitdown/scripts/convert.py` → `.markitdown/convert.py`。
找不到会明确报错并列出找过哪些位置。venv 里也要有 `markitdown`。

测试：

```bash
.venv/Scripts/python -m pytest mcp/tests -q
```

Skill 用法（推荐）：

```bash
export KNOWLEDGE_ROOT=/path/to/library   # Windows: set KNOWLEDGE_ROOT=D:\library
knowledge init
knowledge ingest
knowledge lint scan
knowledge search 你想了解什么
```

把仓库里 `skills/knowledge/` 拷到 Agent 的 skills 根。

MCP 启动（stdio，可选）：

```bash
.venv/Scripts/knowledge-mcp
```

工作目录必须是资料室根（有 `原始资料/`、`资料/` 的那个目录），或设 `KNOWLEDGE_ROOT`。

## 在 Agent 里接这个 MCP

命令指向 venv 里的入口，**cwd 设成仓库根**。stdio。

Claude Desktop / Cursor / 其它 MCP 客户端，配置形状如下（按客户端字段名微调）：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "knowledge-mcp",
      "args": [],
      "cwd": "/path/to/library"
    }
  }
}
```

如果客户端没有 cwd，用 python -m knowledge_mcp.server，工作目录仍是资料室根。

接上之后 Agent 开场就能看见：

| 工具 | 干什么 |
|---|---|
| `kb_search` | 只回路标（含建议块），无正文。两路都跑，三栏：两路都中 / 仅字面 / 仅语义。最多 5 条。`query` / `q` 都行 |
| `kb_read` | 单块：`target` + `part`；多块：`targets` 字符串列表（`书/<slug>/<章>`、`笔记/<slug>`）。最多 5 块、单块 8000 字、整次 24000 字。超长用 `章名#2`；可 `#节名` / `@偏移`。缺一块其它照给；整本或没身份整单拒绝 |
| `kb_ingest_inbox` | 收件箱里全部 PDF/EPUB/MOBI。写六段骨架地图；薄地图未入完，回报附编地图工作单 |
| `kb_ingest_files` | 只转给出的**文件路径**，不是书名。同样要加厚才算入完 |
| `kb_write_note` | 先 `action=preview`（含冲突段候选），再 `verify`（相符 / 部分不符 / 库中无 / 非事实），再 `create` / `update`。相符 / 部分不符必须先成功 `kb_read` 过 `sources`。写入补短地图、覆盖同名标题段 |
| `kb_lint_notes` | `scan` 先在架再问题；`apply`：笔记删改合并，地图 update 可新建，`replace` 改错字，整本 `withdraw`；delete 某一章拒绝 |
| `kb_inspect` | 最近调用/失败；`proposal` 只写入 `检修/提案/` |

人把书丢进 `原始资料/`，对 Agent 说用这个库即可。不要让 Agent 直接打开 `资料/` 灌全文。
