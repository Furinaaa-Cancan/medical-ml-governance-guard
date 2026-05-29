# GOAL: 厘清并解决 RAG 检索路径的"双轨分叉"问题

> 创建于 2026-05-29。本文件是一个**可长期跑、可复算、可恢复**的目标定义。
> 任何 session（含并行 session）接手时，读本文件即可知道全貌与进度。

## 0. 一句话问题

生产环境中 **33 个 gate 的报告**（`peer_review_context` 字段）走的是**裸 BM25**
（`_gate_framework.build_report_envelope` → `scripts.rag.retrieval.bm25.retrieve_for_failure`，
见 `_gate_framework.py:274`）。

而那个精致的 **hybrid 检索 + 全部对冲逻辑**
（`scripts/core/gate_rag_bridge.py:rag_context_for_failure` → `hybrid.hybrid_rank`：
dense BGE 语义 + BM25 + tag + severity 融合，外加 curated 先例注入、off-modality 对冲、
weak-match / low-confidence 对冲）**只被 `tests/` 调用，没有任何生产调用点**。

git log 里 W4–W9 的一连串提交（curated MLGG-P01 先例 `c8e651c`、off-modality denylist
`bb5cbaa`、low-confidence hedge `39f5a81`、weak-match hedge）全部落在 `gate_rag_bridge`，
即**在生产里一行都没生效**。

## 1. 已核验的事实（不是 agent 总结，是直接读码 + 跑命令得到）

- `_gate_framework.py:272-300`：gate 出 failure/warning 时，直接 `from scripts.rag.retrieval.bm25 import retrieve_for_failure`，两段式（failures-first → 必要时补 warnings）。**全程不碰 dense / hybrid / bridge。**
- `gate_rag_bridge.rag_context_for_failure(` 的真实调用点：仅 `tests/test_rag_regression.py`（3 处）。生产代码零调用。`scripts/rag/__init__.py:19` 只是重导出。
- `rag_query`（`query.py:122` → `hybrid_rank`）的生产调用方：`scripts/review/llm_paper_audit.py`、`scripts/review/peer_review_lookup.py`、`scripts/rag/evals/*`。**这是 hybrid 真正运行的地方（离线 paper 审稿 / eval），不是 gate。**
- 依赖事实：`sentence-transformers>=2.2`（拉 torch ~500MB）在 **requirements-optional.txt**；gate 运行时依赖（requirements.txt）只有 numpy + scikit-learn。`bm25` 纯 stdlib。`embeddings.get_model()` 懒加载。
- KB 实际是 **817 条 concern**（`peer-review-kb.json` 的 concern_id 计数），不是文档/记忆里写的 375。
- 不存在 `feature_timing_gate`（早前 agent 幻觉）；时序检查在 `feature_lineage_gate` / onboarding。

## 2. 初步假设（待 workflow 证实，不得假设为真）

**VERDICT 倾向：DESIGN（有意为之）而非 REGRESSION。** 理由：gate 必须只靠 base 依赖
（无 torch）运行、fail-closed、每 gate 独立子进程；把 hybrid 接进每次 envelope 构建会让
gate 依赖一个 500MB 可选包，torch 缺失时还会退化。BM25 永远可用，符合 gate 哲学。

但**真正待解决的问题**因此变成三条，而非"把 bridge 接进 gate"：
1. **文档/心智模型错位**：文档（及之前 agent、可能还有项目记忆）暗示 gate 用 hybrid。实际没有。
2. **benchmark 可能测错路径**：hybrid benchmark 若测的是 `rag_query`/bridge（B/C），但宣称的是
   "gate 同行评审质量"，则与实际出货路径（A 裸 BM25）脱节，数字无效。
3. **孤儿功能**：bridge 里 curated 先例 / off-modality / 对冲，若连离线 `rag_query` 都不经过 bridge，
   则这些功能除测试外全无生产效果——该迁到 `rag_query`、接进 gate、还是删除？需定夺。

## 3. 本次 workflow 要交付的（决策就绪包，不做不可逆改动）

- [ ] **VERDICT**：DESIGN vs REGRESSION + 置信度 + 决定性证据（git 考古 + 依赖 + 测试意图三方交叉）
- [ ] **A-vs-C 行为差异**：对代表性 gate failure code，量化 BM25(A) 与 bridge(C) 返回结果的实质差异
- [ ] **文档错位清单**：哪些文件哪些行声称 gate 用 hybrid，需如何更正（含本仓库 ARCHITECTURE/SKILL/README/CHANGELOG + 用户记忆 375→817）
- [ ] **benchmark 靶向审计**：evals/* 各自测的是哪条路径；现有 P@5 数字代表什么；如何重新标注/重定向使其测"真正出货的路径"
- [ ] **孤儿功能去向建议**：bridge 每项能力的生产效果现状 + 迁移/接线/删除建议
- [ ] **两分支整改预案**（均以 plan/diff 形式，写入本仓库 worktree 或文档，**不 commit 不 push**）：
  - 若 DESIGN：文档更正 + benchmark 重定向 + 孤儿功能去向 + （可选）"懒加载 hybrid 仅在 gate 失败时、torch 缺失自动回落 BM25" 的设计草图
  - 若 REGRESSION：把 bridge 安全接回 `_gate_framework` 的精确 diff + 风险评估 + 回归测试清单

## 4. 约束（硬性）

- **不 commit、不 push、不做不可逆改动。** 所有产出是报告 + 预案 + diff 草案，留给用户审批。
- 并行 session 风险：本仓库常有并发 session，Edit 可能被静默回滚。任何文件改动需隔离 / 留痕。
- 引用必须 file:line 可复算；不接受未经现场核验的行号。

## 5. 进度日志

- 2026-05-29：完成脊柱测绘 + 双轨分叉的直接核验；写下本 goal；启动 10-agent 后台 workflow 做证实与整改预案。
- 2026-05-29（晚）：workflow 完成。**裁决 = MIXED（高置信）**：核心架构 DESIGN（gate 用裸 BM25 是有意为之，**不要**把 hybrid 接进 gate）；文档/benchmark/孤儿代码 REGRESSION。git 考古证实 bridge 从未接入 gate（`git log -S` 返回空），孤儿态是原生的。完整裁决 + 证据 + 整改预案见 **RAG_PATH_FINDINGS.md**。
  - 交付齐：VERDICT、A-vs-C 行为差异（top-1 6/6 相同，仅尾部洗牌 + curated 先例）、文档错位清单、benchmark 靶向审计（双轨设计）、孤儿处置建议、两分支整改预案。
  - **未实施任何改动**（守住 §4 约束）。下一步阻塞在 4 个开放问题（见 FINDINGS §开放问题）+ 用户审批（repo CLAUDE.md 要求 >3 文件/SKILL.md/references 须先获批）。
  - 已修正记忆：375→817 / 106→335(154)；hybrid-benchmark 优先级补充"benchmark 测的是 hybrid 离线路径，非 gate 出货的 BM25 路径"。
