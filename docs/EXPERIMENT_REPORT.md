# UB_RG 实验1 报告：倾斜专家流量下的 Dispatch

对应文档：[`UB_RG实验设计.md`](../../../desgin-doc/supernode/UB_RG实验设计.md) §4.2.1  
仿真入口：`scratch/ub_rg-dispatch-experiment.cc`  
原始数据：

- CI 全矩阵：[`sweep_results.csv`](sweep_results.csv)（180 点，全部 deliveryOK）
- Scenario1 全规格 Zipf 补充：[`sweep_results_full_s1.csv`](sweep_results_full_s1.csv)（36 点，全部 deliveryOK）

固定参数：`TopK=8`，`tokenBytes=grainBytes=7168`，`seed=1`，NPU 同步 `Start@t=0`，专家与 NPU 1:1。

---

## 1. 扫描范围

| 维度 | 取值 |
| --- | --- |
| 组网场景 | 1 / 2 / 3 |
| Scheme | `ub_rg` / `ub_unscheduled` |
| BatchSize | 16, 64, 256, 1024, 4096 |
| Zipf S | 0, 0.1, 0.3, 0.5, 0.7, 0.9 |
| Scale | **CI**（主矩阵）；Scenario1 **full**（Zipf 补充） |

完整笛卡尔积在 **CI scale** 上跑满（3×2×5×6 = **180**）。  
Scenario2/3 的 `full`（1024 NPU）× 大 Batch 未跑全矩阵（单点构建与仿真成本过高）；用 Scenario1 `full`（128 NPU）覆盖 Zipf 倾斜效应。

复现：

```bash
python3 scratch/ub_rg_dispatch_exp1_sweep.py
python3 scratch/ub_rg_dispatch_exp1_full_s1_zipf.py
```

---

## 2. 关键结论

### 2.1 CI 规模下 Zipf 参数失效（方法论）

CI 拓扑 `numNpu=8`，实现将 `topK` clamp 为 `N−1=7`，每个 token 几乎发往**全部**远端 NPU → 负载矩阵与 S 无关（全连通均匀）。  
因此 CI 矩阵中 **CCT / 吞吐 / 热点时延随 S 不变**；CI 结果只适合比较 **scheme × batch × scenario**，不能解读倾斜度。

要观测 Zipf，需要 `TopK ≪ N`（本报告用 Scenario1 full：`N=128, TopK=8`）。

### 2.2 UB_RG 相对自由注入的 CCT 优势（CI，S 无关）

以 Scenario1、`zipfS=0.5`（与其它 S 数值相同）为例：

| BatchSize | CCT `ub_rg` (μs) | CCT `ub_unscheduled` (μs) | 比值 unsched/rg |
| ---: | ---: | ---: | ---: |
| 16 | 10.3 | 20.2 | 1.97× |
| 64 | 36.7 | 67.8 | 1.85× |
| 256 | 143.9 | 252.3 | 1.75× |
| 1024 | 566.7 | 1563.9 | 2.76× |
| 4096 | 2247.9 | 7619.4 | 3.39× |

Batch 越大，自由注入相对完成时间恶化越明显（无 ESC 节拍，下行头阻/incast 放大）。

场景 2/3（CI）趋势一致：同 Batch 下 `ub_rg` CCT 均低于 `ub_unscheduled`；Clos（S2）略高于单层（S1），多平面 Clos（S3）介于两者之间。

### 2.3 全规格 Scenario1：Zipf 倾斜主导 CCT 与热点阻塞

`N=128, TopK=8` 时，CCT 随 S 单调上升。Batch=64：

| Zipf S | CCT `ub_rg` (μs) | CCT `ub_unscheduled` (μs) | hot/cold mean 时延比 (`ub_rg`) |
| ---: | ---: | ---: | ---: |
| 0.0 | 14.6 | 39.5 | 1.08 |
| 0.3 | 30.4 | 75.0 | 1.97 |
| 0.5 | 51.1 | 116.6 | 3.32 |
| 0.7 | 81.0 | 210.0 | 5.73 |
| 0.9 | 111.7 | 234.4 | 9.51 |

对应观测点：

1. **吞吐 / 完成时间**：倾斜升高 → CCT 升高、有效 goodput 下降（热点下行成为瓶颈）。
2. **热点 vs 非热点时延**：`hotMeanNs / coldMeanNs` 随 S 从 ~1 升到 ~9+（`ub_rg`，B=64），冷流完成更快、热流拖长步 CCT。
3. **CCT**：全局完成时间由最热专家接收完成决定，与文档 §4.2.1 预期一致。

高倾斜下两方案 CCT 差距会收窄（Batch=256：S=0 时 unsched/rg≈2.73，S=0.9 时≈1.22）——物理下界 `L*·τ_g` 主导，UB_RG 仍系统性更快。

---

## 3. 交付与数据质量

- CI 180/180、`full` S1 36/36：`deliveryOK=1`，`queued==sent==recv`。
- 指标定义见实验 scratch 报告字段：`CCT_*`、`hotMeanNs`/`coldMeanNs`/`*P99Ns`、`aggGoodputGbps`、`sumNpuRxThroughputGbps`。

---

## 4. 后续建议

1. 全矩阵 Zipf 解读请用 `scale=full`（或保证 `TopK ≪ numNpu`）；CI 仅作 scheme/batch/拓扑冒烟。
2. Scenario2/3 full 可按单点抽样（如 B∈{16,64}、S∈{0,0.5,0.9}）扩展，避免 180×1024NPU 全扫。
3. §4.2.2 Combine 与 dispatch–combine 时延尚未建模，本报告仅覆盖 Dispatch CCT。
