# V07 Findings: 64-Node Cluster Scaling Experiment

**Date**: 2026-03-08
**Baseline**: e44ee8f (V6-final)

## Context

V6-final 的場景有效性討論指出 16 nodes 的叢集不夠 realistic（1 故障 = 6.25% 容量）。
V7 將所有場景改為 64 nodes，同時調整：
- S1: load 90% → 80%
- S3: spike 95% → 85%
- S4/S6: 維持故障節點絕對數（4/2），比例降為 6.25%/3.13%

## V7 結果（64 nodes）

### P99 Latency (ms)

| 場景 | 描述 | no_mitig | adaptive | fixed_iso | fixed_shed | fixed_spec |
|------|------|----------|----------|-----------|------------|------------|
| S1 (10x) | 1n fault, 80% | 29.3 | 29.3 | 29.3 | 29.3 | 29.3 |
| S2 | 1n progressive, 80% | 29.5 | 28.8 | 28.8 | 28.9 | 29.2 |
| S3 | 1n + spike 85% | 29.8 | 28.9 | 28.9 | 28.8 | 29.5 |
| S4 | 4n fault, 80% | **51.1** | **29.8** | **29.8** | **33.3** | **39.4** |
| S5 | 1n fluctuating, 80% | 29.0 | 28.8 | 28.8 | 28.9 | 28.9 |
| S6 | 2n cascade, 85% | 36.1 | 31.3 | 31.5 | 33.1 | 35.8 |
| S7 | 1n recovery, 80% | 29.1 | 28.7 | 28.7 | 28.9 | 28.9 |

### 與 V6 (16 nodes) 比較

| 場景 | V6 no_mitig | V7 no_mitig | V6 adaptive | V7 adaptive |
|------|-------------|-------------|-------------|-------------|
| S2 | 70ms | 29.5ms | 33.8ms | 28.8ms |
| S3 | 80ms | 29.8ms | 209ms ❌ | 28.9ms ✓ |
| S4 | 106ms | 51.1ms | 122ms ❌ | 29.8ms ✓ |
| S5 | 38ms | 29.0ms | 33.6ms | 28.8ms |
| S6 | 152ms | 36.1ms | 80.4ms | 31.3ms |
| S7 | 38ms | 29.1ms | 32.2ms | 28.7ms |

## 核心發現

### 好消息：V6 的兩個問題都解決了

1. **S3 SHED 過度反應消失**：adaptive 從 209ms（比 no_mitig 差 2.6x）→ 28.9ms（略優）
2. **S4 策略反轉為有益**：adaptive 從 122ms（比 no_mitig 差）→ 29.8ms（好 42%）

### 壞消息：故障影響被過度稀釋

- S1/S2/S3/S5/S7 所有策略 P99 都在 28-30ms，差距 <1ms，**無法區分**
- 只有 S4（4 nodes）和 S6（2n cascade + 85% load）有意義的差異
- **沒有任何場景違反 SLO（100ms）**，最高才 51ms

### 根因分析

1. **1/64 = 1.56% 故障比例太低**：健康節點輕鬆吸收
2. **P2C 自然迴避效應**：慢節點佇列長 → P2C 不選它 → 實際接收流量遠低於 1/64
3. **80% 負載有 20% headroom**：足以承受少量容量損失

### M/D/1 模型驗證

排隊論分析精確預測了結果：
- ρ=0.80 時 M/D/1 平均響應 = 30ms（與實驗 ~29ms 吻合）
- P99 > 50ms 需要 ~4 故障節點（S4 的 51.1ms 精確驗證）
- P99 > 100ms 需要 ~8 故障節點

## 結論

V7 證明了「64 nodes + 1 故障節點 + 80% load」的組合讓 P2C 自然迴避就足以處理，
mitigation 策略幾乎無用武之地。需要重新設計實驗參數找到 sweet spot。

詳細的專家分析和改進方向見 `research/expert-discussion-v7.md`。

## Reproducibility

- V7 參數改動 commit: (本次)
- 實驗結果目錄: experiments/results/s1-s7
