---
name: reporter
description: "Generate SQL query reports and create visual charts. Use this skill when the user needs to query a database and present the results as a report, including: sales data statistics, user behavior analysis, business report generation, and business metric queries."
---

# SQL Reporting Skill

Use database tools and charting tools to build SQL query reports according to the user's instructions.

## Workflow

1. Understand the user's instructions and clarify the report requirements and goals
2. Use MySQL tools to generate the correct SQL query
3. Execute the query and obtain the results
4. Use Charts MCP to generate charts
5. Embed the charts into the report using markdown image syntax

## Key Constraints

- The generated SQL query must be correct and efficient, and should avoid full table scans
- The chart generation tool's returned result is not rendered automatically; it must be embedded in the final report using `![description](image URL)` syntax
- Return only report-related conclusions; do not return the raw SQL query

## Allowed Tools

- MySQL tools: execute SQL queries
- Charts MCP: generate visual charts
- Web search tools: supplement background information when necessary
