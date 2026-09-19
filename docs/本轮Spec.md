# 本轮 Spec：3.4 操作流程 + 书架 + 正文替换

> 日期：2026-09-19
> 上级：`需求.md`
> 产品代：`3.4.0-dev`
> 分支：`feat/v3.3-productize`（3.3.0 之上）
> **禁止**新开第七扇门。禁止入库调模型。禁止 `delete` 某一章。禁止检索路标带正文。

## 要解决什么

1. Agent 调入库时要自动拿到「代码做了什么 / 你必须做什么」的操作流程。
2. 洁癖维修：字形错字等，经工具改 Markdown，不让 Agent 直接改磁盘。
3. 「库里有什么」：scan 先给书架（含入完状态）。
4. 笔记入库回报讲清：检索与书同一套，入库多求证。

## 不改

切块算法、FTS/RRF、冻结题集、六扇门数量。`withdraw` / 地图 update / 笔记 preview→verify 闸门保持。

## 1. 入库操作流程（代码 ≠ Agent）

每次入库成功（含部分未入完），回报**固定先写**操作流程，再写书单和工作单。

操作流程必须含：代码已做、代码不做、你必做、怎样算入完。工作单正文沿用 3.3。代码仍不代写俗称。

## 2. 书架（挂 scan，不新开门）

`kb_lint_notes scan` 开头固定「在架」，再「问题」。书列出 title、身份、块数、入完|未入完。笔记列出 title、身份。汇总：书 N 本，笔记 M 条。健康的书也列出。入完 = map_problems 空且 map_thin 空且 book_health 空。超长块写成「超长块《块名》约 n 窗」。

## 3. replace（挂净化 apply）

显式 find→repl。target 可以是 书/<slug>（该书全部 md）、书/<slug>/<章>、笔记/<slug>。find 非空且 ≠ repl，长度 ≤ 80。命中 0 次也成功。写盘后 invalidate。仍禁止 delete/update 某一章。scan：块里 癿 或 丌 ≥3 次报字形可疑。

## 4. 笔记入库回报

create/update 成功后写：检索与书同一套；入库多一步求证。索引主路径不改。

## 5. Skill

入库跟操作流程做到入完；库里有什么走 scan 在架；改错字走 replace。

## 完成线

pytest：入库回报含操作流程/代码已做/你必做；scan 含在架；replace 全书与单章；delete 章仍拒；find 空拒绝；写笔记回报含检索与书同一套。

## 6. Skill 发行（CLI，不靠 MCP）

Skill 不能直接出现 `kb_*`。发行形态：同一套 Python 闸门，命令行 `knowledge`。Agent 跑命令；MCP 仍可选。

- `knowledge init|search|read|ingest|note|lint|inspect`
- `KNOWLEDGE_ROOT` 优先；否则 cwd 若已有 `资料/` 或 `原始资料/`
- 入库找不到 convert.py 时，回退本机 `markitdown` 包
- 闸门与 MCP 相同，不新开门
