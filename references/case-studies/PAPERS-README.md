# Case Studies — Peer Review Knowledge Base

本目录是 MLGG 的**审稿意见知识库**——从 Nature Communications 等期刊的公开 peer review 中提取的结构化审稿证据。

> **与 `papers/` 的关系**：`papers/` 是"我们审别人"（输入 PDF → 产出 metadata + 评分）。本目录是"别人审别人"（Nature Communications 公开审稿意见 → 解析成可检索的知识库），供 MLGG 的 gate 和 self_critique 引用真实审稿案例作为论据。

---

## 目录结构

```
case-studies/
├── PAPERS-README.md                   # 本文件
├── peer-review-kb.json                # 核心知识库：375 条结构化审稿意见（按 gate/dimension/tag 索引）
├── peer-review-kb-stats.json          # KB 统计摘要
├── peer-review-kb-tags.json           # 标签频率表
├── parse_peer_reviews.py              # PDF → 结构化 JSON 的解析脚本
│
├── nature_communications/             # 107 篇 NC 论文的审稿意见
│   ├── INDEX.md                       # 论文索引
│   ├── *.pdf                          # 审稿意见原文 PDF
│   └── parsed/                        # 解析后的结构化数据
│       ├── PR-001.json ... PR-100.json    # 100 篇主论文
│       └── PR-RO-01.json ... PR-RO-07.json  # 7 篇仅有作者回复的论文
│
└── <journal>/<disease>/               # 5 期刊 × 10 疾病领域的论文分析
    └── <author_year>/metadata.json    # 论文元数据（与 papers/ 中的同结构）
```

## 知识库用法

MLGG 在 gate 执行时通过 `_peer_review_retrieval.py` 自动检索相关审稿意见：

```python
from scripts.core._peer_review_retrieval import retrieve_by_gate
concerns = retrieve_by_gate("split_protocol_gate", severity="CRITICAL", limit=3)
# → 返回 3 条真实审稿人对 split 问题的批评，附论文 DOI 和审稿人原文
```

## 数据来源

- Nature Communications 公开 peer review（CC BY 4.0）
- 解析标准：每条意见标注 severity、dimension、gate 映射、作者回复
