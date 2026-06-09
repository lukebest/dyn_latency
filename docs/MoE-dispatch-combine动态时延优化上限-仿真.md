# MoE Dispatch/Combine 动态时延优化上限 — 仿真分析

> **范围**：单分组交换机、16 端侧节点、全链路 200 Gbps 拓扑下，MoE EP dispatch/combine 的**网络动态时延**上限分析。
> **方法学**：对齐 [`SHMEM-POP技术分档.md`](./SHMEM-POP技术分档.md) §1.12（Oracle Fabric 理论上限 vs 待评方案）与 [`DeepSeek-V4-MoE通信完整流程.md`](./DeepSeek-V4-MoE通信完整流程.md) §5 流量模型。
> **代码**：仓库根 `dynlat/` + `run.py`（离散事件仿真，可复现，见末节）。

---

## 1 结论速览（TL;DR）

在「1 交换机 + 16 节点 + 200 Gbps」拓扑下，对 DeepSeek‑V4‑Pro 单层 MoE（EP=16、batch=32、top‑6、FP8 dispatch 7 KB / BF16 combine 14 KB per token‑expert）做事件级仿真，得到三条核心结论：

1. **incast 是硬墙，且不可优化。** 热点专家把大量 token 汇聚到单一 rank，使该 rank 的 **单条 200 Gbps 链路串行化**成为时延下界。dispatch 受**入向下行链路**约束、combine 受**出向上行链路**约束。该「incast 串行时延」占端到端网络时延的 **绝大部分**（rho_h=0.5 时 dispatch ≈ 370 µs、combine ≈ 740 µs），任何调度都无法突破。

2. **关键路径（T_slow / makespan）上可优化的动态时延上限很小。** 基线（无协同的 kernel‑direct）相对 incast 下界仅高出 **约 5–8%**（dispatch 31 µs / combine 21 µs @ rho_h=0.5）。**这就是关键路径上动态时延优化的理论上限。** SHMEM‑POP 把它压到距下界 **< 1 µs（≈ O(RTT)）**，**吃掉了 95–99% 的可优化空间**。

3. **真正大块的可优化动态时延藏在「拥塞扩散」里（非关键路径）。** 基线缺少接收端配速 + VoQ 隔离，热点流的队头阻塞（HOL）+ 反压会把**冷 rank（非热点）**的完成时间从其自身下界 **~33 µs 抬高到 ~130 µs（约 4×）**。SHMEM‑POP 的 (src,dst) VoQ 隔离 + ESC 信用配速把冷 rank 拉回 Oracle 水平。这部分对 p50/均值/抖动影响巨大，但因为 T_slow 由热点 rank 决定，它**不进关键路径**。

> 一句话：**网络动态时延 = 不可优化的 incast 串行（大头）+ 可优化的拥塞排队（小头，在关键路径上 5–8%）。SHMEM‑POP 把关键路径做到距「纯 incast 下界」<1 µs，并消除对冷流的拥塞扩散。**

---

## 2 拓扑与物理参数

| 项 | 取值 |
|----|------|
| 拓扑 | 1 个分组交换机；16 端侧节点全连接（星形，任意节点对 1 hop） |
| 平面数 P | 1（多平面作为敏感性参数，见 §6） |
| 链路带宽 | 每条 200 Gbps = 25 GB/s（上行 node→sw、下行 sw→node 各一条） |
| 交换结构 | 非阻塞 crossbar、输出排队 |
| 单链路传播 d_prop | 100 ns |
| 交换流水线 L_sw | 300 ns |
| chunk / credit 粒度 | 4 KB（SHMEM‑POP §1.8 `pull_credit_size`） |
| RTT（POP 往返） | 1.0 µs（平台标定；用于 Push 预算与信用 BDP=25 KB） |

**时延分解**：单包跨空网的**静态时延** = 序列化×2 + 传播×2 + 交换 ≈ 0.8 µs（与负载无关，不可由调度优化）。**动态时延** = 实测 makespan − 静态 = **incast 串行 + 排队拥塞**。

---

## 3 业务/流量模型（MoE EP）

- EP=R=16 = 节点数；384 routed experts，每 rank 本地 24 个；top‑6；每 rank batch=32 token。
- **dispatch**：token 激活 FP8，每 token‑expert ≈ 7 KB（H=7168）；矩阵 `M_disp[i][j]` = rank i 路由到「位于 rank j 的专家」的 token‑expert 数 × 7 KB。
- **combine**：专家输出 BF16，每 token‑expert ≈ 14 KB；`M_comb[j][i] = M_disp 计数[i][j] × 14 KB`（反向、字节×2）。
- **热点（incast）**：4 个热点专家落在单一 hot rank（rank 0），吸收占比 ρ_h 的路由命中。ρ_h ∈ {0, 0.3, 0.5, 0.7}，对应 hot rank 实际入向份额 7%/31%/45%/56%。
- 总量：dispatch ≈ 20.7 MB、combine ≈ 41.4 MB（整个 EP 域单层单步）。

---

## 4 三个对比方案（同拓扑、同物理参数）

| 方案 | 源端排队 | 交换缓存 | 接收端配速 | Push | 含义 |
|------|----------|----------|------------|------|------|
| **Oracle**（S0） | 每目的 VoQ | ∞、零丢包、无反压 | — | — | **理论下界**，给出纯 incast 串行 floor |
| **Baseline**（S2，kernel‑direct） | 单 FIFO（HOL） | 浅缓存（64 KB/口）、丢包+重传（RTO=5 µs） | 无（开环 blast） | — | 无 IOD 协同的对照基线 |
| **SHMEM‑POP**（S1） | 每 (src,dst) VoQ 隔离 | 有限、CBFC 无丢包 | ESC 信用窗 = BDP（25 KB） | +1×RTT 元数据 | 主评方案 |

- **incast floor（解析）** = `max(busiest_uplink_bytes, busiest_downlink_bytes) / (200 Gbps × P) + 静态`。Oracle 仿真值与该解析式吻合（互为校验）。
- **关键路径动态时延优化上限（headroom）** = `makespan(Baseline) − floor`。
- **SHMEM‑POP 到下界的 gap** = `makespan(SHMEM‑POP) − floor`。

---

## 5 结果

### 5.1 时延分解（关键路径 makespan，ρ_h=0.5）

![decomp](../results/decomp.png)

橙色「incast 串行」是不可优化的硬墙（占绝对大头）；红色「congestion excess」是基线相对下界的多余排队——**这就是关键路径上动态时延可优化的全部空间**，SHMEM‑POP 几乎完全消除它。

| 阶段 | incast floor（不可优化） | Baseline makespan | SHMEM‑POP makespan | 优化上限(headroom) | POP gap→floor | POP 吃掉占比 |
|------|------|------|------|------|------|------|
| **dispatch** | **370.2 µs** | 401.7 µs | 371.8 µs | **30.8 µs** | **0.84 µs** | **97.3%** |
| **combine** | **740.3 µs** | 761.7 µs | 742.0 µs | **20.6 µs** | **0.84 µs** | **95.9%** |

> 关键路径上：动态时延的可优化上限只有 **~5–8%**（其余是 incast 硬墙）；SHMEM‑POP 把网络做到距「只有 incast 影响的理论下界」**仅 0.84 µs（≈ O(RTT)）**。

### 5.2 拥塞扩散（非关键路径，dispatch，ρ_h=0.5）

![perrank](../results/perrank.png)

- **热点 rank 0**：三方案都贴在 incast floor（≈371 µs）——硬墙，谁都打不破。
- **冷 rank 1–15**：Oracle/SHMEM‑POP ≈ 33 µs（各自小下界）；**Baseline 被抬到 ~130 µs（≈4×）**——这是 HOL + 反压造成的拥塞扩散，是 SHMEM‑POP（VoQ 隔离 + 信用配速）真正消除的大块动态时延。

每 rank 平均 dispatch 完成时间：Oracle 55 µs → Baseline 151 µs → SHMEM‑POP 54 µs。

### 5.3 热点强度扫描

![sweep](../results/sweep.png)

| ρ_h | hot share | dispatch floor / base / pop (µs) | combine floor / base / pop (µs) |
|----|----|----|----|
| 0.0 | 7% | 60 / 135 / 61 | 120 / 247 / 120 |
| 0.3 | 31% | 257 / 286 / 258 | 513 / 534 / 514 |
| 0.5 | 45% | 371 / 402 / 372 | 741 / 762 / 742 |
| 0.7 | 56% | 466 / 480 / 466 | 930 / 959 / 931 |

- floor 随热点强度线性上升（incast 越强，硬墙越高），**SHMEM‑POP 始终贴墙（gap < 1 µs）**。
- 即便 ρ_h=0（均匀 all‑to‑all），基线均值仍是 Oracle 的 ~2.3×：**拥塞扩散并不依赖热点存在，无协同的开环注入本身就劣化动态时延。**

---

## 6 解读与边界

- **为什么关键路径 headroom 这么小？** 单台非阻塞输出排队交换机里，只要瓶颈链路（热点 rank 的那条 200 G）保持满负荷，makespan ≈ floor，与丢包/重传/调度顺序基本无关——瓶颈链路就是物理上限。这从仿真上**证实了用户的判断：incast 部分不可优化。**
- **combine 的可优化空间更小**：combine 的 incast 在热点 rank 的**出向上行链路**（单口串行 ~20 MB），FIFO/VoQ 只改变各接收 rank 谁先谁后，makespan 由该单口决定 → 几乎纯硬墙。
- **多平面（P>1）能降低 floor**：热点 rank 有 P 条下行/上行 → incast 串行 /= P。这是**降低 incast 硬墙的唯一物理手段**（multi‑rail），调度类优化（SHMEM‑POP）只能逼近当前 P 的下界、不能替代加平面。代码已参数化 `n_planes`。
- **SHMEM‑POP 的价值定位**（与 §1.7 一致）：①关键路径逼近 incast 下界（gap≈O(RTT)）；②消除对冷流/受害流的拥塞扩散（p50、均值、抖动 3–4× 改善）；③Push≤1 RTT 反压、SM 占用趋零。**它不改变 incast 硬墙，但把「硬墙之上的全部排队拥塞」基本清零。**

**建模假设（影响绝对值，不改变结论）**：交换为输出排队非阻塞；baseline 用浅缓存+丢包重传近似无协同 incast，SHMEM‑POP/Oracle 为 CBFC 无丢包；专家计算（τ_wave）此处不计入「纯网络动态时延」，端到端含计算的流水线另议（计算通常更大且可与通信 wave 重叠）。RTT、缓存深度、RTO、chunk 均可在 `dynlat/scenarios.py` 调整。

---

## 7 复现

```bash
cd /home/luke/dyn_latency
pip install -r requirements.txt
python3 run.py            # 打印表格，生成 results/{summary.json,decomp.png,sweep.png,perrank.png}
```

代码结构：

| 文件 | 作用 |
|------|------|
| `dynlat/engine.py` | 离散事件内核（事件堆） |
| `dynlat/fabric.py` | 链路/交换模型：输出排队、有限/无限缓存、无损反压、VoQ vs FIFO‑HOL、接收端信用配速、丢包重传 |
| `dynlat/workload.py` | MoE 路由抽样（热点）→ dispatch/combine 字节矩阵 |
| `dynlat/scenarios.py` | Oracle/Baseline/SHMEM‑POP 配置 + 解析 incast floor + 单阶段 runner |
| `run.py` | 扫描 ρ_h、出表、出图、写 `summary.json` |

---

*动态低时延 · MoE incast 上限分析 · 对齐 SHMEM‑POP §1.12 方法学*
