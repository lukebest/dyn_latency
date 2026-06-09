# MoE Dispatch/Combine 动态时延优化上限 — 仿真分析

> **范围**：单分组交换机、16/64/128 端侧节点、全链路 200 Gbps、**多平面 P∈{1,2,4,8}**、**全程无损 CBFC** 拓扑下，MoE EP dispatch/combine 的**网络动态时延**上限分析。
> **方法学**：对齐 [`SHMEM-POP技术分档.md`](./SHMEM-POP技术分档.md) §1.12（Oracle Fabric 理论上限 vs 待评方案）与 [`DeepSeek-V4-MoE通信完整流程.md`](./DeepSeek-V4-MoE通信完整流程.md) §5 流量模型。
> **代码**：仓库根 `dynlat/` + `run.py`（离散事件仿真，可复现，见末节）。

---

## 1 结论速览（TL;DR）

在「1 交换机 + 16 节点 + 200 Gbps」拓扑下，对 DeepSeek‑V4‑Pro 单层 MoE（EP=16、batch=32、top‑6、FP8 dispatch 7 KB / BF16 combine 14 KB per token‑expert）做事件级仿真，得到三条核心结论：

1. **incast 是硬墙，且不可优化。** 热点专家把大量 token 汇聚到单一 rank，使该 rank 的 **单条 200 Gbps 链路串行化**成为时延下界。dispatch 受**入向下行链路**约束、combine 受**出向上行链路**约束。该「incast 串行时延」占端到端网络时延的 **绝大部分**（rho_h=0.5 时 dispatch ≈ 370 µs、combine ≈ 740 µs），任何调度都无法突破。

2. **关键路径（T_slow / makespan）上可优化的动态时延上限很小。** 基线（无协同 kernel‑direct，同样跑无损 CBFC fabric）相对 incast 下界仅高出 **约 4–8%**（dispatch 24.6 µs / combine 29.0 µs @ rho_h=0.5）。**这就是关键路径上动态时延优化的理论上限。** SHMEM‑POP 把它压到距下界 **< 1.1 µs（≈ O(RTT)）**，**吃掉了 95–97% 的可优化空间**。

3. **真正大块的可优化动态时延藏在「拥塞扩散」里（非关键路径），且无损 CBFC 下更严重。** 基线缺少接收端配速 + VoQ 隔离，热点输出口缓存填满后 **CBFC 反压 + 单 FIFO 队头阻塞（HOL）** 让**冷 rank（非热点）**的完成时间从自身下界 **~34 µs 被顶到 ~380 µs（约 11×，几乎全员等到热点流排空）**。SHMEM‑POP 的 (src,dst) VoQ 隔离 + ESC 信用配速把冷 rank 拉回 Oracle 水平（~33 µs）。这部分对 p50/均值/抖动影响巨大，但因为 T_slow 由热点 rank 决定，它**不进关键路径**。

4. **多平面是降低 incast 硬墙的唯一物理手段：floor ∝ 1/P。** P=1→8 时 dispatch floor 从 371 µs 降到 47 µs（×1/8）；SHMEM‑POP 在每个 P 都贴着下界（gap≈O(RTT)）。

5. **单交换机下 incast 硬墙随 EP 规模线性恶化：floor ∝ N。** N=16/64/128 时 dispatch floor = 371 / 1426 / 2572 µs；SHMEM‑POP gap 恒为 0.84 µs，与规模无关。**规模越大越需要靠加平面而非靠调度来压 incast。**

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
| **Baseline**（S2，kernel‑direct） | 单 FIFO（HOL） | 有限（128 KB/口）、**无损 CBFC 反压、零丢包** | 无（开环 blast） | — | 无 IOD 协同的对照基线（同 fabric） |
| **SHMEM‑POP**（S1） | 每 (src,dst) VoQ 隔离 | 有限（128 KB/口）、**无损 CBFC** | ESC 信用窗 = BDP（25 KB） | +1×RTT 元数据 | 主评方案 |

> **全程无损 CBFC**：三方案共用同一无丢包链路级反压 fabric；差异只在 **IOD/源端协同**（VoQ 隔离 + 接收端信用配速 vs 开环 FIFO）。多平面采用 **逐 chunk 跨平面条带（ideal multi‑rail）**，给出 P 平面的理想下界。

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
| **dispatch** | **371.0 µs** | 395.5 µs | 371.8 µs | **24.6 µs** | **0.84 µs** | **96.6%** |
| **combine** | **741.1 µs** | 770.2 µs | 742.1 µs | **29.0 µs** | **1.01 µs** | **96.5%** |

> 关键路径上：动态时延的可优化上限只有 **~5–8%**（其余是 incast 硬墙）；SHMEM‑POP 把网络做到距「只有 incast 影响的理论下界」**仅 0.84 µs（≈ O(RTT)）**。

### 5.2 拥塞扩散（非关键路径，dispatch，ρ_h=0.5）

![perrank](../results/perrank.png)

- **热点 rank 0**：三方案都贴在 incast floor（≈371 µs）——硬墙，谁都打不破。
- **冷 rank 1–15**：Oracle/SHMEM‑POP ≈ 33 µs（各自小下界）；**Baseline 被顶到 ~380 µs（≈11×）**——无损 CBFC 下，热点输出口缓存填满后链路级反压回压所有喂热点的源，FIFO 队头阻塞使其后的冷 token 全部等待，几乎全员排到热点流排空。这是 SHMEM‑POP（VoQ 隔离 + 信用配速）真正消除的大块动态时延。

每 rank 平均 dispatch 完成时间：Oracle 55 µs → **Baseline 380 µs** → SHMEM‑POP 54 µs（冷 rank 均值 34 → 380 → 33 µs）。

### 5.3 热点强度扫描

![sweep](../results/sweep.png)

| ρ_h | hot share | dispatch floor / base / pop (µs) | combine floor / base / pop (µs) |
|----|----|----|----|
| 0.0 | 7% | 60.2 / 105.9 / 61.0 | 119.5 / 217.7 / 120.5 |
| 0.3 | 31% | 256.9 / 288.1 / 257.7 | 512.9 / 551.4 / 513.9 |
| 0.5 | 45% | 371.0 / 395.5 / 371.8 | 741.1 / 770.2 / 742.1 |
| 0.7 | 56% | 465.6 / 484.1 / 466.4 | 930.4 / 952.5 / 931.4 |

- floor 随热点强度线性上升（incast 越强，硬墙越高），**SHMEM‑POP 始终贴墙（gap < 1.1 µs）**。
- 即便 ρ_h=0（均匀 all‑to‑all），基线 makespan 仍为 floor 的 ~1.8×、且冷流均值大幅抬升：**拥塞扩散并不依赖热点存在，无协同的开环注入本身就劣化动态时延。**

### 5.4 多平面 P∈{1,2,4,8} 下界对比（N=16, ρ_h=0.5）

![plane](../results/plane_sweep.png)

逐 chunk 跨平面条带（ideal multi‑rail）后，热点 rank 的入向/出向被 P 条 200 G 分摊，**incast floor ∝ 1/P**：

| P | dispatch floor / base / pop (µs) | combine floor / base / pop (µs) |
|---|----|----|
| 1 | 371.0 / 395.5 / 371.8 | 741.1 / 770.2 / 742.1 |
| 2 | 185.9 / 195.7 / 187.4 | 371.0 / 390.8 / 372.8 |
| 4 | 93.4 / 98.3 / 95.1 | 185.9 / 193.0 / 187.5 |
| 8 | 47.1 / 48.4 / 49.1 | 93.4 / 97.1 / 95.2 |

- **floor 每翻倍平面数减半**（371→186→93→47），这是降低 incast 硬墙的**唯一物理手段**；调度类优化只能逼近当前 P 的下界。
- SHMEM‑POP 在每个 P 都贴着下界（gap≈O(RTT)，绝对值 0.8–2.0 µs）；P 越大，基线的可优化 headroom 绝对值越小（拥塞总量被平面摊薄）。

### 5.5 端侧节点数 N∈{16,64,128} 扩展（P=1, ρ_h=0.5）

![node](../results/node_sweep.png)

EP=N 增大时，token‑expert 总量 ∝ N，热点 rank 在单交换机单链路上的 incast 串行 **∝ N**：

| N (=EP) | dispatch floor / base / pop (µs) | combine floor / base / pop (µs) |
|---|----|----|
| 16 | 371.0 / 395.5 / 371.8 | 741.1 / 770.2 / 742.1 |
| 64 | 1426.4 / 1452.2 / 1427.2 | 2852.0 / 2881.6 / 2852.8 |
| 128 | 2571.8 / 2601.7 / 2572.7 | 5142.9 / 5162.7 / 5143.7 |

- **单交换机下 incast 硬墙随规模线性恶化**（N=128 时 combine floor 已达 ~5.1 ms）；这是把整个 EP 域塞进一台交换机的物理代价。
- SHMEM‑POP gap **恒为 0.84 µs，与 N 无关**；基线 headroom 维持 ~26–30 µs（占比随 N 增大而摊薄）。
- 结论：**规模化要靠加平面（§5.4，floor/P）而非调度来压 incast**；调度（SHMEM‑POP）负责把「硬墙之上的拥塞」清零并保护冷流。

---

## 6 解读与边界

- **为什么关键路径 headroom 这么小？** 单台非阻塞输出排队交换机里，只要瓶颈链路（热点 rank 的那条 200 G）保持满负荷，makespan ≈ floor，与调度顺序基本无关——瓶颈链路就是物理上限。这从仿真上**证实了用户的判断：incast 部分不可优化。**
- **combine 的可优化空间更小**：combine 的 incast 在热点 rank 的**出向上行链路**（单口串行），FIFO/VoQ 只改变各接收 rank 谁先谁后，makespan 由该单口决定 → 几乎纯硬墙。
- **无损 CBFC 下基线对冷流更毒**：无丢包反压让队头阻塞演化成「拥塞树」——喂热点的源被回压，FIFO 后续的冷 token 全等热点排空，冷 rank 完成时间被顶到 ≈热点 floor（§5.2，~11×）。VoQ 隔离 + 接收端信用配速是消除它的关键。
- **多平面（P>1）降低 floor**：热点 rank 有 P 条下行/上行 → incast 串行 /=P（§5.4）。这是**降低 incast 硬墙的唯一物理手段**（multi‑rail），调度类优化（SHMEM‑POP）只能逼近当前 P 的下界、不能替代加平面。
- **规模（N）放大 incast 硬墙**：单交换机下 floor∝N（§5.5），N=128 时已达毫秒级；规模化必须靠加平面，而非靠调度。
- **SHMEM‑POP 的价值定位**（与 §1.7 一致）：①关键路径逼近 incast 下界（gap≈O(RTT)，与 N 无关）；②消除对冷流/受害流的拥塞扩散（均值、抖动 ~11× 改善）；③Push≤1 RTT 反压、SM 占用趋零。**它不改变 incast 硬墙，但把「硬墙之上的全部排队拥塞」基本清零。**

**建模假设（影响绝对值，不改变结论）**：交换为输出排队非阻塞；**三方案全程无损 CBFC（零丢包链路级反压）**，差异仅在 IOD/源端协同（VoQ 隔离 + 接收端信用配速 vs 开环 FIFO）；多平面采用逐 chunk 跨平面条带（ideal multi‑rail，给出 P 平面理想下界）；专家计算（τ_wave）此处不计入「纯网络动态时延」，端到端含计算的流水线另议（计算通常更大且可与通信 wave 重叠）。RTT、缓存深度、平面数、节点数、chunk、热点形态均可在 `dynlat/scenarios.py` / `workload.py` 调整。

---

## 7 复现

```bash
cd /home/luke/dyn_latency
pip install -r requirements.txt
python3 run.py   # 出表 + results/{summary.json,decomp,sweep,perrank,plane_sweep,node_sweep}.png
```

实验组：A 热点扫描（N=16,P=1，ρ_h∈{0,0.3,0.5,0.7}）；B 多平面（N=16,ρ_h=0.5，P∈{1,2,4,8}）；C 节点扩展（P=1,ρ_h=0.5，N∈{16,64,128}）。

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
