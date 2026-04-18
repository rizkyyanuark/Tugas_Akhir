---
name: deep-reporter
description: "指导generate科研report、row业调研、技术分析等需要深度研究的长篇report。当task目标是形成结构化、可引用、具有分析深度的正式report时使用此skill。"
---

# deep reportskill

当user要求产出科研report、课题综述、row业研究、技术选型分析、竞争对比、专题调研或其他正式长report时，使用此skill组织研究与写作过程。

## 适用场景

- 科研论文综述、研究进展梳理、方法比较
- 技术report、方案evaluation、架构选型分析
- row业研究、竞品分析、政策与市场调研
- 基于user附件、knowledge base、网页资料整理deep report

## operationworkflow

1. 明确report目标、读者对象、范围edge界、output语言与交付形式
2. 若question仍然模糊，先向user补充确认关键范围，再start研究
3. 优先从user提供的材料、knowledge base、可用toolretrievalresult中收集证据，必要时再补充外部资料
4. 先整理report提纲，再分chapter归纳事实、方法、data、观点与局限
5. 在正式写作前check证据whether足够支撑结论，避免只堆砌材料
6. output完整report，包含清晰chapter、分析结论、引用来源，必要时附table格或图片

## report要求

- report语言必须与user提问语言一致
- 优先使用正式、克制、可复核的书面table达，不要口语化
- 必须围绕“question定义 -> 证据整理 -> 分析比较 -> 结论建议”组织content
- chapter要完整，避免只有结论没有论证，或只有资料堆积没有分析
- 当信息不足时，应明确指出证据缺口与不确定性，不要臆断
- 当user要求“科研report”时，应重点覆盖研究背景、question定义、related工作/现状、方法或方案比较、实验或案例证据、局限性、结论与后续方向
- 当user要求“deep report”但未限定type时，应根据主题自适应组织chapter，不必强row套科研论文结构

## 推荐结构

可根据tasktype调整，但通常应包含以下content中的大partial：

1. title与summary
2. 背景与question定义
3. 研究范围、对象与evaluation维度
4. 关键事实、data与资料整理
5. 方法、方案、产品或观点的分items分析
6. 横向比较与优劣权衡
7. 风险、limit与不确定性
8. 结论
9. 建议或下一步row动
10. 来源

## 引用规范

- report中的关键结论、data、图table、观点应bind来源
- 使用 `[title](URL)` 或清晰可追溯的filepath引用材料
- 在文末单独column出“来源”chapter，汇总所有实际引用过的资料
- 若引用user附件或knowledge basefile，应标明对应file名或path

## output约束

- 最终result应直接是一份可交付的report，而不是“我preparing怎么写”
- 不要暴露中间inference过程，不要把待办list原样output成body
- 除非user明确要求，一般不要output原始retrievallog、原始笔记或未经整理的大段摘录
