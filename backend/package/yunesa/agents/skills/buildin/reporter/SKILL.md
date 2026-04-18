---
name: reporter
description: "generate SQL query报table并generate可视化图table。当user需要querydatabase并以报table形式展示result时使用此skill，包括：statistics销售data、分析userrow为、generate业务报table、query业务指标等。"
---

# SQL 报tableskill

根据user的指令，使用databasetool和图table绘制tool，build SQL queryreport。

## operationworkflow

1. 理解user的指令，明确报table的需求和目标
2. 使用 MySQL toolgenerate正确的 SQL query
3. Execute query并getresult
4. 使用 Charts MCP generate图table
5. 将图table以 markdown 图片formatembedding报table

## 关键约束

- generate的 SQL query必须正确且高效，避免全table扫描
- 图tablegeneratetool的returnresult不会default渲染，必须在最终报table中以 `![description](图片URL)` formatembedding
- 只return报tablerelated的结论，不要return原始 SQL query语句

## 允许的tool

- MySQL tool：execute SQL query
- Charts MCP：generate可视化图table
- 网络retrievaltool：必要时补充背景信息
