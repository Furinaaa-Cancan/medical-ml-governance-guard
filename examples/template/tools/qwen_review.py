"""
qwen_review.py — Qwen 辅助代码审查工具

按需调用 Qwen 对指定代码做 MLGG 规则定向检查。
作为 Claude 主审的补充，不替代主流程。

Usage:
    # 检查单个文件的数据泄漏问题
    python3 tools/qwen_review.py --file 03_preprocessing/scripts/preprocess.py --check leakage

    # 检查特征工程是否有未来信息泄漏
    python3 tools/qwen_review.py --file 04_feature_selection/scripts/select_features.py --check temporal

    # 全面审查（所有检查项）
    python3 tools/qwen_review.py --file 05_modeling/scripts/train_models.py --check all

    # 审查多个文件
    python3 tools/qwen_review.py --file 02_splitting/scripts/split.py 03_preprocessing/scripts/preprocess.py --check leakage

    # 附加 config.py 上下文
    python3 tools/qwen_review.py --file 03_preprocessing/scripts/preprocess.py --check encoding --with-config

环境变量:
    DASHSCOPE_API_KEY  — 必须设置（或在 .env 文件中配置）
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def _load_env():
    """Auto-load .env file from project root if it exists."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_env()
DEFAULT_MODEL = os.environ.get("QWEN_MODEL", "qwen3.6-plus")

# ── 检查项定义 ──────────────────────────────────────────

CHECKS = {
    "leakage": {
        "name": "数据泄漏检查",
        "prompt": """检查以下代码是否存在数据泄漏问题。重点关注：
1. fit() / fit_transform() 是否在分割前的完整数据上调用（MLGG-P01）
2. SMOTE / 过采样是否应用到了非训练集数据（MLGG-P02）
3. 全局 dropna / clip / quantile 是否在分割前执行（MLGG-P03）
4. 缺失值填补的统计量是否从训练集以外的数据计算（MLGG-P04）
5. 特征选择是否在完整数据上执行（MLGG-F03）
6. 标签/结局变量是否被作为特征使用（MLGG-F01）""",
    },
    "split": {
        "name": "数据分割检查",
        "prompt": """检查以下代码的数据分割是否正确。重点关注：
1. 是否按患者 ID 分割，确保同一患者不出现在多个集合（MLGG-S01）
2. 如有时序数据，测试集时间是否晚于训练集（MLGG-S02）
3. 是否使用了 stratify 保持正类比例一致
4. 分割比例是否合理（推荐 60/20/20）
5. 是否设置了 random_state（MLGG-R01）""",
    },
    "encoding": {
        "name": "编码合理性检查",
        "prompt": """检查以下代码的特征编码是否正确。重点关注：
1. 名义变量（如 race, gender, ICD 分组）是否使用了 OneHotEncoder（MLGG-P05）
2. 是否错误地对名义变量使用了 OrdinalEncoder / LabelEncoder（引入虚假序数假设）
3. 序数编码是否有经验验证的单调性（不是假设的）
4. 药物变化列（No/Steady/Down/Up）是名义变量，不是序数变量
5. 编码器是否只在训练集上 fit""",
    },
    "temporal": {
        "name": "时序信息泄漏检查",
        "prompt": """检查以下代码是否存在时序信息泄漏。重点关注：
1. 是否定义了预测时间点（MLGG-F05）
2. 是否有预测时间点之后才可获得的特征被使用（MLGG-F02）
3. 入院时特征和出院时特征是否区分对待
4. ICD 诊断码是否来自同次住院且未验证时间先后
5. 用于定义标签的变量是否被作为预测特征""",
    },
    "evaluation": {
        "name": "评估方法检查",
        "prompt": """检查以下代码的模型评估是否严谨。重点关注：
1. 是否报告了完整指标面板：AUROC/AUPRC + Sens/Spec/PPV/NPV/MCC/LR+/LR- + 校准 + Brier + DCA（MLGG-E02）
2. 是否有 95% Bootstrap CI（≥1000 次）（MLGG-E01）
3. 阈值是否在验证集上选择而非测试集（MLGG-M02）
4. 超参调优是否使用了测试集（MLGG-M01）
5. 是否做了概率校准检查（ECE < 0.1）（MLGG-E03）
6. 如用了 class_weight="balanced"，是否做了后校准（MLGG-E05）
7. 是否只用 accuracy 评估不平衡数据""",
    },
    "all": {
        "name": "全面审查",
        "prompt": """作为 Nature Methods / JAMA 级别的审稿人，全面审查以下医学 ML 预测代码。
按以下类别逐项检查：

**数据泄漏**：fit 是否仅在训练集、SMOTE 是否仅在训练集、特征选择范围、标签泄漏
**数据分割**：患者级分割、时序约束、正类比例一致性
**编码**：名义/序数匹配、编码器 fit 范围
**时序安全**：预测时间点定义、未来信息、入院 vs 出院特征
**评估严谨**：指标完整性、CI、阈值来源、校准
**可复现**：random_state、多种子、Pipeline 封装
**公平性**：亚组分析、CI、小样本警告""",
    },
}

SYSTEM_PROMPT = """你是一个严格的医学机器学习方法学审查员，专注于二分类预测模型的代码审查。

输出规则：
1. 只报告你确实在代码中发现的问题，不要猜测代码之外的情况
2. 每个问题按以下格式输出：

[MLGG-xxx] SEVERITY: issue_name
Location: filename:line_number（如能确定）
Problem: 具体描述问题
Fix: 具体修复建议

3. SEVERITY 分三级：CRITICAL（必须修）、WARNING（强烈建议）、INFO（最佳实践）
4. 如果没有发现问题，明确说"未发现问题"
5. 最后给出一个简短总结：发现 N 个 CRITICAL / N 个 WARNING / N 个 INFO
6. 不要输出与代码审查无关的内容，不要客套"""


def call_qwen(code: str, check_prompt: str, api_key: str, context: str = "", model: str = DEFAULT_MODEL) -> str:
    """Call Qwen API with code review prompt."""
    user_content = f"{check_prompt}\n\n"
    if context:
        user_content += f"## 项目配置上下文\n```python\n{context}\n```\n\n"
    user_content += f"## 待审查代码\n```python\n{code}\n```"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
        "enable_thinking": False,
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return f"API Error {e.code}: {body}"
    except Exception as e:
        return f"Error: {e}"


def read_file(path: str) -> str:
    """Read file content with size guard."""
    size = os.path.getsize(path)
    if size > 500_000:
        print(f"WARNING: {path} is {size // 1024}KB, truncating to first 500 lines", file=sys.stderr)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[:500])
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(description="Qwen MLGG code review")
    parser.add_argument("--file", nargs="+", required=True, help="Python file(s) to review")
    parser.add_argument(
        "--check",
        choices=list(CHECKS.keys()),
        default="all",
        help="Check type (default: all)",
    )
    parser.add_argument("--with-config", action="store_true", help="Include config.py as context")
    parser.add_argument("--model", default=None, help=f"Override model (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not set.", file=sys.stderr)
        print("  Option 1: export DASHSCOPE_API_KEY=sk-...", file=sys.stderr)
        print("  Option 2: Create .env file with DASHSCOPE_API_KEY=sk-...", file=sys.stderr)
        sys.exit(1)

    model = args.model or DEFAULT_MODEL

    # Load config context if requested
    context = ""
    if args.with_config:
        config_path = str(PROJECT_ROOT / "config.py")
        if os.path.exists(config_path):
            context = read_file(config_path)

    check = CHECKS[args.check]
    results = []

    for filepath in args.file:
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}", file=sys.stderr)
            continue

        code = read_file(filepath)
        numbered = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(code.splitlines()))

        fname = Path(filepath).name
        print(f"  Reviewing {fname} ...", file=sys.stderr, end=" ", flush=True)
        result = call_qwen(numbered, check["prompt"], api_key, context, model)
        print("done", file=sys.stderr)

        if args.json:
            results.append({"file": filepath, "check": args.check, "result": result})
        else:
            print()
            print(f"  {'=' * 56}")
            print(f"  Qwen Review: {fname}")
            print(f"  Check: {check['name']}")
            print(f"  {'=' * 56}")
            print()
            print(result)
            print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
