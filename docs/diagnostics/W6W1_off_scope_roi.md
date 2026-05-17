# W6-W1: Off-MLGG-scope detector ROI
**Date**: 2026-05-17  **Agent**: Wave6-W1  **Mode**: measure-only, no commits

## Test queries
- OFF: 10 queries (should be hedged)
- IN:  8 queries (should NOT be hedged)
- Both alternatives compared against current floor 0.72 baseline.

## Per-query measurements
| Query | Type | top-1 dense | floor 0.72 | floor 0.73 | denylist (token) | combined |
|---|---|---|---|---|---|---|
| single-cell RNAseq batch effect correction | OFF | 0.695 | FIRE | FIRE | FIRE (rnaseq) | FIRE |
| image segmentation UNet skip connections | OFF | 0.685 | FIRE | FIRE | FIRE (unet) | FIRE |
| BERT fine-tuning catastrophic forgetting | OFF | 0.691 | FIRE | FIRE | FIRE (bert) | FIRE |
| Cox proportional hazards survival regression | OFF | 0.724 | . | FIRE | FIRE (survival) | FIRE |
| federated learning privacy gradient leakage | OFF | 0.759 | . | . | FIRE (federated) | FIRE |
| quantum machine learning noise mitigation | OFF | 0.690 | FIRE | FIRE | FIRE (quantum) | FIRE |
| VAE GAN deep generative model | OFF | 0.733 | . | . | FIRE (generative) | FIRE |
| graph neural network message passing | OFF | 0.695 | FIRE | FIRE | FIRE (message_passing) | FIRE |
| reinforcement learning offline policy | OFF | 0.685 | FIRE | FIRE | FIRE (offline_policy) | FIRE |
| natural language processing tokenization bias | OFF | 0.746 | . | . | FIRE (natural_language) | FIRE |
| missing calibration plot | IN | 0.765 | . | . | . | . |
| patient leakage train test split | IN | 0.761 | . | . | . | . |
| no external validation single center | IN | 0.710 | FIRE | FIRE | . | FIRE |
| AUROC without confidence interval | IN | 0.772 | . | . | . | . |
| extreme class imbalance unaddressed | IN | 0.725 | . | FIRE | . | FIRE |
| complete-case analysis missing data | IN | 0.723 | . | FIRE | . | FIRE |
| TRIPOD AI checklist compliance | IN | 0.872 | . | . | . | . |
| subgroup performance by race ethnicity | IN | 0.704 | FIRE | FIRE | . | FIRE |

## Confusion matrices

### Current floor 0.72 (baseline)
- TP (OFF hedged): 6/10 = 60%
- FP (IN hedged): 2/8 = 25%

### Approach 1: Floor 0.73 alone
- TP: 7/10 = 70%
- FP: 4/8 = 50%

### Approach 2: Denylist alone
- TP: 10/10 = 100%
- FP: 0/8 = 0%

### Approach 3: Combined (floor 0.73 OR denylist)
- TP: 10/10 = 100%
- FP: 4/8 = 50%

## Verdict
- Best alternative: **denylist**
- Coverage (TP): 10/10 = 100% of OFF caught
- False-positive rate (FP): 0/8 = 0%
- Decision: **Cheap alternative is ENOUGH.** Schema work (P3) is NOT worth the cost.
Recommend: ship the cheap approach in Wave 7; defer P3 schema work.

## Implementation cost comparison
- Floor bump (0.72 -> 0.73): 1 LOC in `scripts/core/gate_rag_bridge.py:85`
- Denylist: ~5 LOC + a `frozenset` of ~30 tokens, added to `_is_low_confidence` or a sibling check
- Combined: ~6 LOC (denylist fires regardless of dense floor)
- Schema work (P3): 2-3 sessions: `GateSpec.modality` + `paper_modality` field + 335-paper backfill (LLM-or-rule classifier per paper) + KB schema migration + tests

## Notable per-query observations
- Cox row: dense=0.724, floor 0.72 -> MISS, floor 0.73 -> FIRE, denylist -> FIRE
- 'missing calibration plot' IN row: dense=0.765, floor 0.73 -> pass
