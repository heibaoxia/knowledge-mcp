---
name: knowledge
description: Use when the user asks to use their local knowledge library, 资料室, 知识库, search books they ingested, ingest PDF/EPUB, or list what is in the library. Prefer the knowledge CLI. Do not open 资料/ and dump full text.
---

# Knowledge Skill

本机资料室。正本是 Markdown。闸门是命令 `knowledge`（同一套代码也可走 MCP `kb_*`，二选一）。

## 何时开门

用户点名知识库 / 资料室 / 查库里的书 / 往库里丢书。没点名：当普通聊天。

若 `knowledge` 不在 PATH：让用户 `pip install -e ./mcp`，并设置 `KNOWLEDGE_ROOT` 为资料室目录。不要假装查过。

## 命令

在资料室目录执行，或先 `export KNOWLEDGE_ROOT=...`：

1. `knowledge search <一句话>` — 只回路标，无正文。先搜再读。
2. `knowledge read 书/<slug>/<章>` — 一次可多个身份。单窗 8000，整次 24000。超长用 `章名#2`。
3. `knowledge ingest` — 收件箱 `原始资料/`。有路径则只转那些文件。
4. `knowledge lint scan` — **在架**（库里有什么）+ 问题。
5. `knowledge note preview|verify|create|update --file note.md`
6. `knowledge lint apply --plan '[{"op":"replace","target":"书/<slug>","find":"癿","repl":"的"}]'`
7. `knowledge inspect`

够答就停。不要按目录通读，不要打开 `资料/` 灌全文。

## 入库

回报里有操作流程：代码已做切块和骨架地图；你必做加厚（读者问法 + ≥3 别名），走 `knowledge lint apply` 更新 `书/<slug>/地图`。骨架不算入完。

## 写笔记

`preview` → `verify` → `create`/`update`。相符必须先 `knowledge read` 过依据。检索与书同一套，入库多求证。

## 不要做

- 没点名就开资料室
- 把路标当正文，或编造库里没有的内容
- 入库只写骨架就报入完
- 不经 `lint apply` 直接改 `资料/` 里的书
- 为了「只留一本」把相关的第二本书藏起来
