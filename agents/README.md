# MLGG Agent Architecture

## Role Separation

MLGG 使用多 agent 分工协作，每个 agent 做它最擅长的事。

### Claude Code (Interactive CLI)

**职责**: 代码审计 + 全流程执行

只有 Claude Code 有文件系统、命令执行、git 等工具权限。以下任务**仅限 Claude Code**：

| 能力 | 命令 |
|------|------|
| 静态 lint 扫描 (28 条 AST 规则) | `mlgg lint check <file> --format json` |
| 项目级量化审计 (10 维 100 分) | `audit_external_project.py --project-dir <dir>` |
| 完整审计报告 (TRIPOD+AI/PROBAST+AI) | `generate_audit_report.py --project-dir <dir>` |
| 临床语义审查 (Lint 抓不到的问题) | 读代码 + 理解特征时间线/定义变量泄漏 |
| 33 gate 执行 | `mlgg strict --project-dir <dir>` |
| 9 阶段全流程 (`/mlgg`) | 观察 → 推断 → 行动 |

入口: `.claude/commands/mlgg.md` + `CLAUDE.md`

### API Agents (Text-Only, No Tools)

**职责**: 论文分析 — 不需要执行代码，只需要文本推理

yaml 配置在 `agents/` 目录下，供外部编排器或 `export_review_prompt.py` 生成的 prompt 使用。

| 角色 | 配置文件 | 适用场景 |
|------|---------|---------|
| Paper Reviewer | `reviewer.yaml` | 给定论文 metadata → 12 维量化评审 |
| Metadata Extractor | `extractor.yaml` | 给定论文文本/PDF 内容 → 结构化 metadata.json |

每个 yaml agent 支持 3 个 provider（Anthropic / Google / OpenAI），用户按 API key 可用性选择。

## 为什么这么分

| 原则 | 解释 |
|------|------|
| **能力匹配** | 代码审计需要文件读写 + 命令执行，API agent 做不到 |
| **成本效率** | 论文分析是纯文本推理，用 Gemini Flash 或 Sonnet 即可，不需要 Opus |
| **可批量** | 论文分析可以并发调 API 批量处理 172 篇；代码审计是交互式的 |
| **安全边界** | 代码审计中的 prompt injection 防御需要工具级权限控制 |

## 使用方式

```bash
# Claude Code: 代码审计
# （在 Claude Code CLI 中）
/mlgg          # 全流程
# 或直接命令
python3 scripts/orchestration/mlgg.py lint check <file.py>
python3 scripts/orchestration/mlgg.py audit --project-dir <dir>

# API Agent: 生成可移植的 review prompt
python3 scripts/reporting/export_review_prompt.py --level standard --journal nature_medicine
# 输出粘贴到任意 LLM，或由编排器使用 yaml 配置调 API
```
