# MoE Dispatch/Combine 仿真 — 测试激励（Test Stimulus）详细说明

> 本文档详细描述 `dynlat/` 离散事件仿真所施加的**测试激励**：即注入网络的流量内容、注入时机、分块/分平面方式、各方案激励差异，以及实验扫描的激励参数空间。
> 关联代码：[`dynlat/workload.py`](../dynlat/workload.py)（流量生成）、[`dynlat/scenarios.py`](../dynlat/scenarios.py)（流转换/注入配置）、[`dynlat/fabric.py`](../dynlat/fabric.py)（分块/分平面注入）、[`run.py`](../run.py)（扫描驱动）。

---

## 1 激励总览

一次仿真的「激励」由三层构成：

| 层 | 内容 | 代码位置 |
|----|------|----------|
| **流量内容** | MoE 路由抽样 → `dispatch`/`combine` 的 (src→dst) 字节矩阵 `M[i][j]` | `workload.py::draw_routing` |
| **流定义** | 把矩阵每个非零元转成一条 `Flow(src,dst,nbytes,start,plane)` | `scenarios.py::run_phase` |
| **注入时序/分块** | 每条 flow 切成 4 KB chunk，按注入纪律在 `start` 时刻进入源端队列 | `fabric.py::_split / _make_ready` |

仿真是**单层单步、单 phase** 的：dispatch 与 combine 分别作为两个独立 phase 各跑一次（互不重叠），每个 phase 注入一整批流量后运行到全部交付完成。

---

## 2 业务模型参数（DeepSeek-V4-Pro MoE）

激励的物理量来自 `MoEConfig`（`workload.py:18-32`），对齐 `DeepSeek-V4-MoE通信完整流程` §3/§5.2：

| 参数 | 符号 | 默认值 | 含义 |
|------|------|--------|------|
| EP 宽度 / 节点数 | `n_ranks` (R=N) | 16（扫描 16/64/128） | 专家并行域 = 端侧节点数 |
| 总路由专家数 | `experts` | 384 | 全域 routed experts |
| 每 rank 本地专家 | `experts_per_rank` | 384/N（N=16→24） | 连续块放置 `expert_to_rank` |
| top-k 路由 | `top_k` | 6 | 每 token 选 6 个不同专家 |
| 每 rank batch | `batch` | 32 token | Decode/chat 场景 |
| 隐藏维 | `hidden` (H) | 7168 | — |
| dispatch 载荷 | `dispatch_bytes_per_te` | 7168 B (≈7 KB) | FP8 激活，每 token-expert |
| combine 载荷 | `combine_bytes_per_te` | 14336 B (≈14 KB) | BF16 输出，每 token-expert（2×dispatch） |
| 热点专家数 | `hot_experts` | 4 | 落在单一 hot rank |
| 热点强度 | `rho_h` | 0.5（扫描 0/0.3/0.5/0.7） | 路由命中热点的概率偏置 |
| 热点 rank | `hot_rank` | 0 | incast 汇聚点 |
| 随机种子 | `seed` | 0 | 决定性可复现 |

> 注：N=128 时 `experts_per_rank` = 3 < `hot_experts` = 4，`draw_routing` 会自动把热点专家数截断到本地容量（`min(hot_base+hot_experts, hot_base+epr)`，`workload.py:73`）。

---

## 3 流量生成：路由抽样算法

核心在 `draw_routing`（`workload.py:65-92`），逐 rank、逐 token 抽样 top-k 专家，带热点偏置：

```text
for src in 每个 rank R:
    for _ in batch(=32) 个 token:
        chosen = ∅
        while |chosen| < top_k(=6):
            以概率 rho_h:  从 4 个热点专家中均匀选 1 个     # incast 偏置
            否则:          从全部 384 个专家中均匀选 1 个    # 背景均匀流量
            chosen.add(e)              # 集合去重，保证 top-k 个不同专家
        for e in chosen:
            dst = expert_to_rank[e]    # 专家所在 rank
            count[src, dst] += 1       # 累加 token-expert 计数
```

要点：
- **热点机制**：每次抽专家以概率 `rho_h` 强制落入 hot rank 的 4 个热点专家，形成 many-to-one 的 incast 汇聚。
- **去重**：top-k 用集合保证 6 个不同专家（`guard` 上限 1000 防死循环）。
- **背景流量**：`(1-rho_h)` 概率下均匀打散到全部专家 → 全 all-to-all 背景。
- **输出**：`count[i][j]` = rank i 路由到「位于 rank j 的专家」的 token-expert 计数矩阵 [R×R]。

### 实测热点份额（hot share）

`rho_h` 是抽样概率，真实的入向份额 `hot_share`（hot rank 实际收到的 token-expert 占比，`run.py:29-31`）略低：

| `rho_h` | 实测 hot share |
|---------|---------------|
| 0.0 | 7%（≈1/16 均匀基线） |
| 0.3 | 31% |
| 0.5 | 45% |
| 0.7 | 56% |

---

## 4 流量内容：dispatch / combine 字节矩阵

由 `count` 矩阵派生两个 phase 的字节矩阵（`workload.py:44-53`）：

| Phase | 矩阵 | 公式 | 物理含义 |
|-------|------|------|----------|
| **dispatch** | `M_disp[i][j]` | `count[i][j] × 7168 B` | rank i 把 FP8 激活发往 rank j 的专家 |
| **combine** | `M_comb[j][i]` | `count[i][j]ᵀ × 14336 B` | rank j 的专家把 BF16 结果回传 rank i |

- **对角线置零**（`np.fill_diagonal`）：本地专家命中不走网络。
- **combine 是 dispatch 的转置 × 2 倍字节**：方向相反、载荷翻倍 → combine 的 incast floor 恰为 dispatch 的 2 倍。

### 总流量规模（N=16, ρ_h=0.5）

- dispatch ≈ **20.7 MB**
- combine ≈ **41.4 MB**

（整个 EP 域单层单步；总量随 N 近似线性增长。）

---

## 5 流定义与注入时序

### 5.1 流定义

`run_phase`（`scenarios.py`）把字节矩阵每个非零元转成一条 flow：

```python
for i in range(N):
    for j in range(N):
        b = M[i, j]
        if b <= 0: continue
        flows.append(Flow(src=i, dst=j, nbytes=b, start=push, plane=...))
```

### 5.2 分块（chunking）

每条 flow 在 `_split`（`fabric.py:108-125`）按 `chunk_bytes = 4096 B`（= SHMEM-POP `pull_credit_size`）切成 chunk，向上取整；最后一个 chunk 可能不足 4 KB。

### 5.3 注入时序（open-loop）

- **所有 chunk 在 `t = flow.start` 时刻同时进入源端队列**（`_make_ready`，`fabric.py:127-133`）——即一次性灌入的开环（blast）激励，不做应用层节流。
- 此后能否真正发出，取决于各方案的源端纪律（FIFO/VoQ）与流控（缓存/信用）。

### 5.4 分平面（per-chunk striping，ideal multi-rail）

多平面时，chunk 按序号轮流分配到 P 个平面（`fabric.py:121`）：

```python
chunk.plane = s % n_planes   # s = chunk 序号
```

这是**理想 multi-rail 条带**：单条 flow 的字节被均匀摊到 P 条 200 Gbps 链路，给出 P 平面的理想下界（incast floor ∝ 1/P）。

---

## 6 各方案的激励差异

三个对比方案**共享完全相同的流量矩阵与 chunk 序列**，差异仅在注入纪律与流控（这正是公平对照的关键）：

| 方案 | 注入起点 `start` | 源端排队 | 流控 | 激励语义 |
|------|-----------------|----------|------|----------|
| **Oracle** | 0 | per-dst VoQ | 无限缓存、无反压 | 理想注入，给 incast 下界 |
| **Baseline** | 0 | 单 FIFO（HOL） | 有限缓存 + 无损 CBFC 反压 | 无协同开环 blast |
| **SHMEM-POP** | **+1×RTT**（push 元数据） | per-(src,dst) VoQ | 有限缓存 + 接收端信用窗（BDP） | 协同注入：先 push 后受信用配速 |

> 唯一的「时序激励差异」是 SHMEM-POP 的所有 flow `start = RTT`（1 µs），模拟 1×RTT 的 push 元数据预交换；Oracle/Baseline 从 t=0 注入。流量内容（字节矩阵、chunk 划分）三方案逐字节一致。

物理参数（`base_phys`，`scenarios.py:49-53`）三方案共享：

| 参数 | 值 |
|------|----|
| 链路带宽 | 200 Gbps = 25 GB/s |
| chunk | 4096 B |
| 单跳传播 d_prop | 100 ns |
| 交换流水线 L_sw | 300 ns |
| RTT | 1.0 µs（BDP = 25 KB） |

---

## 7 激励参数扫描空间（实验 A–D）

`run.py::main` 施加四组激励扫描：

| 实验 | 扫描变量 | 固定参数 | 缓存模式 | 目的 |
|------|----------|----------|----------|------|
| **A 热点扫描** | ρ_h ∈ {0, 0.3, 0.5, 0.7} | N=16, P=1 | fixed 128 KB | incast 强度敏感性 |
| **B 多平面** | P ∈ {1, 2, 4, 8} | N=16, ρ_h=0.5 | fixed 128 KB | floor ∝ 1/P 下界 |
| **C 节点扩展** | N ∈ {16, 64, 128} | P=1, ρ_h=0.5 | fixed 128 KB | floor ∝ N 规模化 |
| **D P×N 网格** | P×N（4×3=12 点） | ρ_h=0.5 | **matched**（随 (P,N) 扇入） | 缓存匹配下界 |

每个扫描点对 dispatch 和 combine 各跑一遍，每个 phase 跑 Oracle/Baseline/SHMEM-POP 三方案。总仿真次数 = (4+4+3+12) × 2 phase × 3 方案 = **138 次单 phase 仿真**。

---

## 8 决定性与可复现性

- 所有随机性来自单一 `np.random.default_rng(seed=0)`（`workload.py:66`）——**固定种子 → 激励完全可复现**。
- 同一 (N, ρ_h, seed) 必产生逐字节相同的流量矩阵；不同方案/平面数在同一矩阵上对照。
- 复现命令：

```bash
cd /home/luke/dyn_latency
python3 run.py    # 重新生成 results/summary.json 与全部 PNG
```

---

## 9 激励的关键特征小结

1. **incast 主导**：热点专家（4 个）集中在单 rank，配合 `rho_h` 偏置形成 many-to-one 汇聚——这是激励的核心压力源。
2. **开环 blast**：所有 chunk 在 `start` 时刻一次性就绪，最大化暴露排队/反压/拥塞扩散。
3. **dispatch/combine 不对称**：combine 字节翻倍且方向转置，单独构成更重的 incast。
4. **三方案同激励**：流量内容逐字节一致，仅注入纪律/流控/push 时序不同，保证对照公平。
5. **参数化扫描**：ρ_h（强度）、P（平面）、N（规模）、buffer（缓存）四维独立可调。

---

*MoE incast 上限分析 · 测试激励说明 · 对齐 SHMEM-POP §1.12 与 DeepSeek-V4-MoE §5*
