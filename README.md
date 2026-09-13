# ziliaoshi

一个专门为 Agent 提供专业知识的 MCP，可以自己打造这资料库。

本机知识库：Markdown 当正本，通过 MCP 暴露六扇门 —— 检索、阅读、入库、写笔记、净化、自检。
不给人的笔记软件用，不做 RAG，不把向量库当正本。

## 怎么用

1. 把 PDF / EPUB / MOBI 丢进 `原始资料/`
2. 让 Agent 调「收件箱入库」，源文件转成 Markdown 进 `资料/书/<slug>/`，原件归档
3. 之后 Agent 只靠抬头检索、点名才读正文；书入库后不改

## 文档

- 现行规格：`需求.md`
- 白话步骤：`docs/功能流程.md`
- 写代码前先读：`AGENTS.md`
- **怎么接到 Agent**：`mcp/README.md`

## 许可

MIT，见 `LICENSE`。
