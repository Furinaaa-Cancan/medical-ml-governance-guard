# RAG 路径调查：裁决与决策就绪整改包

> 2026-05-29。10-agent workflow（7 调查 + 1 综合 + 2 整改）产出，已逐条交叉核验。
> 状态：**调查完成，整改未实施**（不 commit / 不 push，等用户拍板）。
> 配套：[RAG_PATH_INVESTIGATION_GOAL.md](RAG_PATH_INVESTIGATION_GOAL.md)。

---

## 裁决：MIXED（高置信度）

| 维度 | 结论 |
|---|---|
| **核心架构（gate 用裸 BM25、hybrid bridge 不接入）** | **DESIGN，有意为之。** 不要把 hybrid 接进 gate。 |
| **文档 / benchmark / 孤儿代码** | **REGRESSION（信任完整性问题），需修。** |

6 个调查角度里 5 个 leans_design；git 考古 + 依赖性能 + 测试意图（你指定加权最高的三项）一致高置信指向 DESIGN。

### 为什么核心是 DESIGN（不是回归）

- **git 考古**：`git log --all -S 'rag_context_for_failure' -- scripts/core/_gate_framework.py` **返回空**。gate 框架历史上从未引用过 bridge。BM25 进 gate 在 `7f664ec`(2026-04-17)，bridge 出生在 `664ee69`(2026-05-16)，晚一个月，且文档里写的是 gate "**可以**调用"（aspirational），从来不是"**正在**调用"。`d0fc5f3`("bring BM25 retriever home") 只换了 import 路径，没换函数。**没有"断开"可言——孤儿态是原生的、设计如此。**
- **依赖/性能**：gate 运行时只依赖 numpy+sklearn+stdlib；`bm25.py` 纯 stdlib，端到端 ~13ms。hybrid 拉 torch(~500MB，requirements-**optional**.txt)，冷进程 SentenceTransformer 初始化 ~12s。gate 是短生命周期 exit-0/2 子进程、无常驻单例，接 hybrid 等于每次失败重付 ~12s + 把 500MB 可选依赖塞进 fail-closed 路径。**保持 BM25 是正确的成本/延迟取舍。**
- **实测行为差异**（真 KB + 真模型，6 组代表性 failure）：A(BM25) vs C(bridge) **top-1 命中 6/6 完全相同**；只有 top-5 尾部洗牌（均重叠 3.33/5）。唯一实质头部变化是 curated 先例注入（MLGG-P01 fit-before-split）。且 C 输出 schema 不同（`_final_score` vs gate 在 `_gate_framework.py:291` 读的 `_retrieval_mode`），**不是 drop-in**。

> 把 "bridge 该接进 gate 却没接 = 回归" 这个框架本身，是个 XY 问题。架构是对的。

### 真正坏掉的（REGRESSION 那一半 = 信任完整性，不是行为）

1. **文档错位（最高杠杆）**
   - `gate_rag_bridge.py:9-13` docstring **谎称** gate 失败时调用 `rag_context_for_failure` 填充 `peer_review_context`——与 `_gate_framework.py:274`（bm25）直接矛盾。
   - `README.md:246` / `README_EN.md:223` 把 bridge 当作 gate 集成入口宣传（假）。`README.md:213/228` 把 gate 喂数据层说成"密集向量 RAG"（实为 BM25 关键词重排）。
   - `docs/ARCHITECTURE.md` 整篇按"bridge 式 gate 路径"写（从未上线），且说模型是 **BGE-large**，而 `config.py:41` = `BAAI/bge-small-en-v1.5`。
   - **陈旧计数**：`ARCHITECTURE.md:27` + `SKILL.md:151` 写"106 篇 / 375 条"，实际 KB = **335 篇（154 篇已抽取）/ 817 条 concern**。
   - ✅ 保留勿动：`SKILL.md:40,44,102` 正确地把 hybrid 限定在 L3 离线路径。

2. **benchmark 测错路径**
   - `harness.py:90` / `run_eval.py:467` 默认 `hybrid`；整个 NCPR 套件（`ncpr_paper_runner.py:343`）**只有 hybrid，无 BM25 开关**。
   - `labeled_precision_at_5.json:10` 把发布的 P@5 钉死在 `hybrid`，且 `:12` 已标注 circularity_warning（标签由 Opus 4.7 自评，同模型族）。
   - **没有任何默认 benchmark 测 gate 实际出货的 BM25 路径。** 用户读 P@5 会高估 gate 失败时拿到的 RAG 质量。`harness.py:39-42` 甚至记录过曾"修复测错路径"却把默认翻向 hybrid，**离出货路径更远了**。
   - 连 `bm25_only` 模式也不是忠实复刻：harness 合成了 query 字符串，而 gate 调用时只给 `gate_name+codes`、无 query_text，且缺 `_gate_framework.py:287-297` 的 severity_fallback 二段重试。

3. **孤儿功能（739 LOC，生产中 100% 死代码，却有真实价值）**
   - `gate_rag_bridge.py` 全模块只被 tests/ 触达；`scripts/rag/__init__.py:19-22` 的引用在 **docstring 示例**里，不是 re-export（`__all__=["rag_query"]`）。
   - `rag_query` 直连 `hybrid_rank`（`query.py:122`），**绕过** bridge 的 curated/off-modality/hedge 全部逻辑。
   - 真实价值被埋没：`_synthesize_query` 的下划线→空格归一化（docstring 称"materially improves dense recall"）——而 eval harness 在 `harness.py:214`/`run_eval.py:83` **重新实现了更弱的 bare join，丢了这个归一化**；`_is_off_modality_query`（应对 W4 0.68-0.73 spurious-BGE）；`_curated_precedent_for`（修 L27 P@5=0.0 盲区）。这些本该惠及离线 `rag_query`（llm_paper_audit）路径，却卡在没人调用的 gate-only 包装里。

---

## 整改计划（优先级排序，**均为预案，未实施**）

### A. 文档说真话（最高杠杆，低风险，可逆）
- `gate_rag_bridge.py:9-13` docstring 改为"本 bridge 当前未接入；gate 走 `bm25.retrieve_for_failure`；本模块面向离线 paper-audit/eval"。
- `README.md:246/213/228` + `README_EN.md:223/194/209`：gate 失败上下文由 BM25 直接生成；dense/hybrid 限定离线 `mlgg rag` 路径。
- `docs/ARCHITECTURE.md`：BGE-large→bge-small（:15,37,49）；"production path" 限定为离线 eval/audit；计数 106/375→335(154)/817。
- `SKILL.md:151`：106/375→335(154)/817。**保留 :40,:44,:102**。
- `CHANGELOG.md:292`：历史条目，加注而非改写。

### B. benchmark 对齐出货路径（双轨）
- **Track A（新增，缺口所在）**：`scripts/rag/evals/gate_path_eval.py`，驱动 `build_report_envelope`/`retrieve_for_failure`（gate_name+codes、无 query_text、含 severity_fallback 二段重试），在 **同一份** `references/benchmark/ncpr_v1_holdout.json` 上打分，输出 `gate_path_precision_at_5_v1.json`，明确标"gate 路径 BM25-only"。
- **Track B/C（现有，重新贴标签）**：harness/run_eval/NCPR 的 hybrid 标为"离线 paper-audit 路径，非 gate 路径"；把 circularity 警告提到表头。
- 修 `bm25_only` 保真缺口；合并 `harness.py:214`+`run_eval.py:83` 的 query 合成为共享 helper。

### C. 孤儿处置（部分被开放问题阻塞）
- **PROMOTE 到 `rag_query`**：`_synthesize_query` 归一化（并替换 eval 里的弱副本）、`_is_off_modality_query`+denylist。
- **待定**：`_curated_precedent_for`（→ 接入 rag_query 还是删？见 Q2）。
- **删除**（除非要做 markdown gate 报告面）：`format_for_gate_report` 等 144 LOC（见 Q1）。
- 同步把 bridge 测试改成断言 promoted 路径或真实 bm25 envelope，停止固化"bridge 是 gate 路径"的错误模型。

---

## 需要你拍板的 4 个开放问题（决定约半数 C 类工作）

1. **是否计划做"gate 报告 markdown 渲染面"**（把 `peer_review_context` 渲成 markdown 进 report.json）？是→保留并接线 `format_for_gate_report`；否→删 ~144 LOC。
2. **curated fit-before-split 先例（MLGG-P01/P04）是否应影响离线 paper-audit**（llm_paper_audit via rag_query）？是→promote；否→删。
3. **benchmark：新增忠实的 BM25 gate-path benchmark（Track A），还是仅给现有 hybrid P@5 重新贴标签？** 你记忆里的 hybrid-benchmark 优先级倾向前者；最小修复是后者。
4. **发布 P@5 的同模型族 circularity（Opus 4.7 自评）现在就处理（人工裁定）还是仅在 METRIC_CONTRACT.md 披露？**

> 约束提醒：repo CLAUDE.md 要求 >3 文件改动 / 改 SKILL.md / 写 references/*.json **须先获批**。故全部预案待批后再批量实施，且实施前 pull+diff（并行 session 防回滚）。
