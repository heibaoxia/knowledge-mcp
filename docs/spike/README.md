# docs/spike/ — 进行中的 Spike

放**本轮还没做完**的稿：本轮 Spec、调研、实现计划。

## 规矩

- `需求.md` 是唯一现行规格。这里的东西是过程稿：不许改规格，不许放宽 `docs/验收标准.md` 的冻结题集（Q1–Q14、W1–W20）。
- 这里只放「进行中」的稿。**没有进行中的稿就空着，不要为了填空造 Spec。**
- 做完（过验收 + 线上题追加 `检修/验收记录.md`）：
  - 本轮 Spec 移到 `docs/归档/`，文件名带日期：`YYYY-MM-DD-本轮Spec-<主题>.md`
  - 对应的实现计划一起移到 `docs/归档/`，同名或加日期前缀
  - spike 里不留空壳，也不留指向归档的残稿
- 下一轮从 `docs/问题.md` 开新 Spike：
  - 一次 Spike 对**一类问题**（见 `AGENTS.md` 的改代码原则），不对着单题
  - **禁止对着单题写补丁 Spec**（「Q9 漏了 7 记忆 → 加一条过滤」这种）
  - 类问题先记在 `docs/问题.md`，开 Spike 时再搬进来

## 已归档的样子

- `docs/归档/2026-09-15-本轮Spec-闲书建议块与节.md` + 计划 `docs/归档/2026-09-15-noise-suggest-sections.md`
- `docs/归档/2026-09-14-本轮Spec-地图两路lint.md` + 计划 `docs/归档/2026-09-14-map-two-path-lint.md`
- `docs/归档/2026-09-13-本轮Spec-自然篇与语片FTS.md` + 计划 `docs/归档/2026-09-13-natural-chunk-fts.md`
