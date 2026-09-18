---
name: knowledge
description: 本机资料室。用户说「用知识库」「查库里的书」「资料室」、要按自己的书回答、或往库里丢 PDF/EPUB 时使用。先 kb_search 再 kb_read。没点名不要调 kb_*。
---

# 知识库

闸门是本机 MCP `knowledge`（工具名 `kb_*`），不是这篇说明书。机器 id：`knowledge`。

## 何时开门

用户点名知识库 / 资料室 / 查库里的书，或明确要按入库的书来答。没点名：不要调 `kb_*`，当普通聊天。

若工具列表里没有 `kb_search`：告诉用户在本 Harness 启用 MCP `knowledge`（命令指向仓库 venv 的 `knowledge-mcp`，工作目录 `F:\project\knowledge`），不要假装查过。

## 怎么用

1. `kb_search` 问一句人话。只回路标：哪几本书、建议读哪几块、三栏（两路都中 / 仅字面 / 仅语义）。**没有正文。**
2. 从建议块里点名 `kb_read`，身份形如 `书/<slug>/<章>`。一次最多 5 块；一块约 8000 字；一整次约 24000 字。太长用 `章名#2` 翻下一窗。
3. 够答就停。不要按目录通读，不要直接打开 `资料/` 文件夹灌全文。
4. 库里没有就说没有。负样本（库里没有的技术栈）应为空，不要硬凑。

## 其它门（人点名才用）

- 丢书：人把 PDF/EPUB/MOBI 放进 `原始资料/`，再 `kb_ingest_inbox` 或 `kb_ingest_files`。缺地图时按回报编地图，走 `kb_lint_notes apply`。
- 写笔记：`preview` → `verify` → `create`/`update`。说相符必须先成功 `kb_read` 过依据。
- 退书：`kb_lint_notes` 先 scan，再 apply `withdraw`，点名 `书/<slug>`。不要删某一章。

## 不要做

- 没点名就调用资料室
- 把路标当正文、或编造库里没有的内容
- 为了「只留一本」把相关的第二本书藏起来
