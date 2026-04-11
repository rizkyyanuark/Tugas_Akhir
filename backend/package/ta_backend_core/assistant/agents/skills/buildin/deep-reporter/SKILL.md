---
name: deep-reporter
description: "Guides the generation of long-form reports that require deep research, such as research reports, industry research, and technical analysis. Use this skill when the goal is to produce a structured, citable, and analytically deep formal report."
---

# Deep Reporting Skill

Use this skill to organize the research and writing process when the user requests a research report, literature review, industry study, technical selection analysis, competitive comparison, topic-specific research report, or any other formal long-form report.

## Use Cases

- Research paper reviews, research progress summaries, and method comparisons
- Technical reports, solution evaluations, and architecture selection analysis
- Industry research, competitor analysis, and policy or market research
- Deep reports compiled from user attachments, knowledge bases, and web sources

## Workflow

1. Clarify the report goal, audience, scope boundaries, output language, and delivery format
2. If the problem is still ambiguous, ask the user to confirm the key scope before starting research
3. Prioritize evidence from user-provided material, knowledge bases, and available tool retrieval results; supplement with external sources only when needed
4. First organize the report outline, then summarize facts, methods, data, viewpoints, and limitations by section
5. Before formal writing, check whether the evidence is sufficient to support the conclusions and avoid merely piling up material
6. Deliver a complete report with clear sections, analytical conclusions, and cited sources, plus tables or images when needed

## Report Requirements

- The report language must match the language of the user's question
- Prefer formal, restrained, and verifiable written expression; avoid conversational language
- The content must be organized around "problem definition -> evidence organization -> comparative analysis -> conclusions and recommendations"
- Sections should be complete; avoid having conclusions without arguments or material dumps without analysis
- When information is insufficient, explicitly state evidence gaps and uncertainty instead of guessing
- When the user asks for a "research report", focus on research background, problem definition, related work/current state, method or solution comparison, experimental or case evidence, limitations, conclusions, and future directions
- When the user asks for a "deep report" without specifying the type, adapt the structure to the topic instead of forcing a research-paper format

## Recommended Structure

Adjust as needed for the task type, but it should usually include most of the following:

1. Title and abstract
2. Background and problem definition
3. Research scope, subjects, and evaluation dimensions
4. Key facts, data, and material organization
5. Section-by-section analysis of methods, solutions, products, or viewpoints
6. Horizontal comparison and tradeoff analysis
7. Risks, limitations, and uncertainties
8. Conclusion
9. Recommendations or next steps
10. Sources

## Citation Rules

- Key conclusions, data, charts, and viewpoints in the report should be tied to sources
- Cite materials using `[title](URL)` or a clearly traceable file path
- Include a separate "Sources" section at the end that summarizes all materials actually cited
- If citing user attachments or knowledge base files, indicate the corresponding file name or path

## Output Constraints

- The final result should be a deliverable report, not an explanation of how it will be written
- Do not expose intermediate reasoning, and do not copy the todo list into the final body
- Unless the user explicitly requests it, do not output raw retrieval logs, raw notes, or long unedited excerpts
