# UB_RG 网络仿真报告
> **可信性状态：实现证据存在，性能结论未验证。** 行为级结果仅作为网络机制假设；方案间路由、path delay、jitter 与 barrier 混杂尚未消除，逐包性能矩阵也未通过完成守恒与跨引擎校验。绝对硬件时延与完整POP硅片实现不得据此下结论；Exp3 GEMV 为标定服务模型。详见[UB_RG仿真可信性评估报告](./UB_RG仿真可信性评估报告.html)。
## 0. 通信微架构总览

下图概括本仿真**已建模的通信微架构**与**未建模的计算微架构**。随后表格给出上图各模块对应的关键代码位置。

![UB_RG 通信微架构](./ub_rg_figures/ub_rg_microarchitecture.png)

## 0.1 微架构关键代码证据索引

下表把上图中的模块直接映射到仓库文件位置；阅读结果前应先能定位这些实现。

| 微架构模块 | 证据 | 文件与位置 |
|---|---|---|
| 行为级常量 / grain / 端口速率 | τ_g、50 GB/s、hop 时延 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:29-36` |
| Zipf / TopK → grain | 负载与专家路由 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:260-351` |
| Spray / RG / POP phase | 三方案排队与授权 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:438-738` |
| S4 / iSLIP / 启动偏差 / GEMV | PathClass、SimulateIsLip、start-skew、ComputeGemvUs | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc` |
| 行为级 CCT / König | 指标与 summary | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:520-538, 730-812, 886-921` |
| 逐包拓扑 / S3 路由过滤 | Leaf–Spine 与 FIB | `gen_ub_rg_topo.py:47-181`（S3：`144-180`） |
| 逐包 token / scheduler map | 工作负载与挂接 | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:117-407` |
| phase / completion / watchdog | 计时与收尾 | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:439-742` |
| POP completion overlay | 非完整 Push/Pull | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:589-608, 878-887` |
| REQ pacing | 50 µs 控制注入 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-sender-agent.cc:113-181` |
| GNT → WQE / Jetty / TP | 数据注入 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-sender-agent.cc:227-376` |
| RR / credit / stale reclaim | 目的侧调度 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-scheduler.cc:93-341` |
| LOCAL / GLOBAL SYNC | 同步协议 | `protocol/ub-rg-scheduler.cc:374-409`；`protocol/ub-rg-sender-agent.cc:379-426` |
| 首 MTU 入队归还 credit | credit 语义 | `ns-3-ub/src/unified-bus/model/ub-switch.cc:453-490` |
| RG 末跳拦截 | REQ/DATA 转发 | `ns-3-ub/src/unified-bus/model/ub-switch.cc:1184-1258` |
| schedulerId 仅 6 bit | SYNC id 折叠 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-header.cc:227-236` |
| runner 矩阵 | 任务与跳过 | `run_ub_rg_experiments.py:18-145, 211-277, 340-403` |

## 0.2 主要实验结论
> 结论适用于场景1/4；Exp1/2 为网络子系统；Exp3 含 Zipf×batch GEMV straggler。
- **配置包输出差异**：Exp1 三方案共有参数格中，POP/RG 平均为 **1.010×**，Spray/RG 平均为 **1.149×**。这是当前配置包的联合差异；plane、path delay、jitter 和 barrier 尚未统一，不能把比值单独归因于目的侧配速。
- **POP 启动开销会被负载摊薄**：batch=16 时 POP/RG=**1.017×**，batch=256 时为 **1.002×**；结果符合“多一次 one-way 启动、稳态节拍与 RG 相同”的模型预期。
- **瓶颈下界**：CCT/König 中位数为 ub_rg=1.126、ub_rg_pop=1.134、packet_spray=1.340、islip=1.068；它证明输出符合当前方程，但不是排除混杂后的硬件性能验证。
- **拓扑范围**：主矩阵为场景1（Clos+iSLIP）与场景4（Sparse CLOS 512P）。
- **Exp3**：端到端含 GEMV；`gemv_us` 随 Zipf 热点与 batch 变化。
## 1. 实验概述
本报告对应 [UB_RG实验设计.md](./UB_RG实验设计.md) §4.2.1–§4.2.3，在 `ns-3-ub` 中用自包含行为级仿真器 `scratch/ub_rg-dispatch-experiment.cc` 对比 **UB_RG（request/grant）**、**UB_RG_POP（SHMEM-POP）** 与 **Packet Spray（自由注入）**。结构对齐参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html)：组网 → 方案差异 → 扫参结果。
### 1.1 仿真环境、微架构抽象与 CCT 口径

| 项目 | 配置 / 抽象 |
|---|---|
| 执行主机 | Linux 6.17.0-40-generic（x86_64） |
| 工具链 | Python 3.12.3；g++ 13.3.0；CMake 3.28.3；ns-3.44 optimized build |
| 当前报告引擎 | `behavioral`；grain 级行为离散事件模型：不逐包执行完整协议栈，而以串行化服务器、FIFO、固定传播/流水时延和控制 RTT 表示网络。 |
| 并行方式 | 单次仿真保持单线程确定性；参数点由 Python `ProcessPoolExecutor` 并行 |
| 端点模型 | 每个 NPU 对应一个网络端点/专家；每 token 的每个 TopK 路由项形成一个 7 KB grain |
| 网络接口 | 每 NPU 8 个 400 Gbit/s 上联；有效 50 GB/s/端口；τ_g=7168/50e9≈143.36 ns |
| 交换结构 | 50 ns/跳传播 + 150 ns/跳流水；场景1 单层 Clos；场景4 Sparse CLOS（PFM/SW-S/SW-a-b） |
| 启动偏差 | 各 NPU 起点 ~U(0,skew)，skew∈(2, 4, 8) µs |
| 负载生成 | TopK=8；Zipf S；主矩阵 seed=1；Exp3 PDF 每格 96 seeds |

#### 微架构模型边界

- **已建模的是通信微架构**：NPU 端口串行化、8 平面选路、Spray 目的出口/两层 Clos 中段队列、RG nominal 授权节拍、POP 的启动时延/PullCredit，以及 BSP 屏障常量。
- **因果比较尚未闭环**：Spray 与 RG 同时改变 plane 映射、path delay 公式、jitter 和固定 barrier；当前比值是配置包差异，不能单独归因于目的侧准入。
- **计算侧（Exp3）**：`gemv_us = max_e N_e·τ_tok`（均匀 Zipf、batch=256 时约 80µs/专家）；`e2e_us = dispatch_cct + gemv_us + combine_cct`。
- **未建模**：完整 SM/HBM/cache、专家算力异构；iSLIP 为行为级 VOQ 匹配。
- 主矩阵为 **场景1 + 场景4**（已去掉场景2/3）。

#### CCT 的准确口径

- Exp1/2：`cct_us` / `step_us` = 网络阶段（含启动偏差）+ barrier。
- Exp3：`cct_us` = 网络往返；`gemv_us` / `e2e_us` / `step_us(=e2e+barriers)` 含 Zipf×batch GEMV。

### 1.2 组网方案

对齐 [UB_RG实验设计.md](./UB_RG实验设计.md) 与 [场景4_Sparse_CLOS_512P_设计说明.md](./场景4_Sparse_CLOS_512P_设计说明.md)；本报告由 行为级引擎（`ub_rg-dispatch-experiment`） 驱动。

> 主矩阵仅跑场景1与场景4；场景4 行为级按 Sparse CLOS 路径类（PFM / SW-S / SW-a-b）建模。

| 场景 | 拓扑 | NPU | 交换 | 备注 |
|---|---|---:|---|---|
| 1 | 单层 Clos | 128 | 8 × SW128 | 8×400G；2 跳；另含 iSLIP 调度对照 |
| 4 | Sparse CLOS | 512 | 32 × SW128 | 8 Cluster×64 Server；15×400G（7 PFM+8 上联）；唯一路径 |

组网差异要点：

- **跳数 / RTT**：场景1 RTT_rg≈0.6µs；场景4 典型 SW≈0.8µs，同机 PFM 更短。
- **瓶颈**：场景1 目的侧平面下行；场景4 跨 Cluster SW 下行与 PFM 争用。
- **调度**：场景1 含 `islip`；场景4 为 `ub_rg` / `ub_rg_pop` / `packet_spray`。

### 1.3 网络方案与实现差异

| 方案 | Scheme | 语义 |
|---|---|---|
| §2.1 | `packet_spray` | 自由注入 / Packet Spray 基线（参考报告中的 `ub_unscheduled`） |
| §2.2 | `ub_rg` | 标准 Request-Grant：目的侧按 1 grain/τ_g 授权 |
| §2.3 | `ub_rg_pop` | SHMEM-POP：Push 元数据 → ESC → PullGrant → 远端读 Pull |

主 KPI：CCT / step（µs）；辅 KPI：hot/cold p99、吞吐、CCT/König。机制对照如下（以本仓库仿真为准，POP 为近似模型，非完整 supernode `UbRgPopEsc` 模块）。

#### 角色关系

| 对象 | 形态 | 角色 |
|---|---|---|
| `ub_request_grant.md` / 设计 | 文档 | 交换机侧分布式 REQ/GNT：每 τ_g 每出口 ≤1、路径钉扎、cursor/SYNC |
| `ub_rg` | 仿真 scheme | 主协议的落地：目的侧授权节奏 + 源侧 FCFS；行为级折叠控制面为 RTT；逐包走真实 REQ/GNT/SYNC |
| `ub_rg_pop` | 仿真 scheme | [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md) 的假设模型：行为级为 RG + startup + PullCredit；逐包为 RG 路径 + completion 计时 overlay |
| `packet_spray` | 仿真 scheme | 无授权准入；源上联自由注入；目的/中段 FIFO；分析阶段叠软件屏障 |
| `islip` | 仿真 scheme | 场景1：每平面 VOQ iSLIP 匹配（每 τ_g 多轮 request/grant/accept） |

> **对齐的核心（设计 ↔ ub_rg）：** grain 量化、τ_g、每平面 ≤1 授权、Clos/MpClos 钉扎。
> **POP 相对 RG：** 稳态 König 渐近相同；startup = RTT_rg + oneWay（≈1.5×）；小 batch 略慢，大负载/高偏斜时 pop≈rg。
> **Spray 相对 RG：** 无目的侧节拍 → 热点队列放大，CCT/p99 与软件屏障更重。

#### 三方机制对照

| 维度 | `packet_spray` | `ub_rg` | `ub_rg_pop`（本仓库） |
|---|---|---|---|
| 调度 / 准入 | 无；源侧自由注入 | 目的侧 GNT 节奏（1/τ_g/egress） | 同 RG；多一次 Push 单向 |
| 控制通道 | 无控制面握手 | REQ → GNT → DATA（逐包真实报文；行为级折叠为 RTT） | 行为级用 `rtt_pop` 近似；逐包未发送 Push/Pull 报文，只在 RG completion 上叠 startup |
| 注入准入 | 仅源端口串行 | GNT 到才发，无预支库存 | 行为级有 `C_pop=⌈rtt_pop/τ_g⌉+margin`；逐包与 RG 使用相同 credit |
| 冷启动 | 0（立即发） | 付一次 RTT_rg | 付 RTT_rg + oneWay（Push→Grant→Pull） |
| ESC / 节拍 | 无 | 每 τ_g 每 egress ≤1 grain | 同左（König 渐近对齐 RG） |
| 数据路径 | 源序 RR 洒平面；两层含 spine→leaf 队列 | RG 平面钉扎；近零队列（σ 抖动） | 同 RG 钉扎 |
| 屏障 | 软件屏障（更重） | BSP cursor 屏障（轻） | 同 `ub_rg` |
| 实现入口 | `UsePacketSpray=true` | `Scheme::UbRg` / RG scheduler active | `Scheme::UbRgPop`；逐包复用 RG transport并在统计时追加 one-way |

#### 实验可读差异（期望趋势）

| 维度 | `ub_rg` | `ub_rg_pop` | `packet_spray` |
|---|---|---|---|
| 首包 / 小 batch | 付 RTT_rg | 略高于 RG（多 oneWay） | 常介于二者之间或更差（无节拍） |
| 大 batch / 高偏斜 | CCT 贴 König | pop/rg → 1（同节拍） | spray/rg ≫ 1，hot p99 放大 |
| 冷流隔离 | 好（按需授权） | 接近 RG | 差（热点占满下行） |
| 两层 Clos | 中段压力可控 | 偶发略差于 RG | 中段 FIFO 放大更明显 |

CLI：`--scheme=ub_rg|ub_rg_pop|packet_spray|islip`；`--start-skew-us=2|4|8`。
### 1.4 模型假设与简化
- 端口 400Gbps（有效 50GB/s），grain = 7KB，τ_g ≈ 143.36 ns
- 链路建模为串行化服务器 + FIFO；交换机直通 150 ns/跳，传播 50 ns/跳
- UB_RG：目的侧按 1 grain/τ_g 授权节奏 + 源端口 FCFS
- UB_RG_POP：同目的侧节奏；startup = RTT_rg + oneWay（Push→Grant→Pull）；PullCredit 窗口保稳态流水（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）
- Packet Spray：自由注入；软件屏障在分析阶段叠加
- 场景4 按 Sparse CLOS 路径类建模；场景1 另跑 iSLIP
- 启动偏差：每 NPU ~U(0,skew)，skew∈{2,4,8}µs
- Exp3：GEMV = max 专家 token 数 × τ_tok
- 专家与 NPU 1:1；TopK=8
### 1.5 参数矩阵（裁剪）
| 实验 | mode | 场景 | Batch | Zipf S | EP | 启动偏差 | 调度 |
|---|---|---|---|---|---|---|---|
| 1 Dispatch | dispatch | 1,4 | 16,256 | 0,0.3,0.7,0.9 | full | 2/4/8 µs | S1:+islip |
| 2 Combine | combine | 同实验1 | 同左 | 同左 | full | 同左 | 同左 |
| 3 Roundtrip+GEMV | roundtrip | 1→{32,64,128}; 4→{128,256,512} | 256 | 同左 | 上列 | 同左 | 同左 |
| 3 PDF | roundtrip | 同上 | 16,64,256 | 同左 | 每格 96 seeds | skew=4µs | 同左 |

引擎：**behavioral**；成功汇总运行数：**24780**。原始结果：`results/ub_rg/`。
> 上表对齐当前 runner：仅场景1+4；含启动偏差与场景1 iSLIP；Exp3 输出 gemv_us/e2e_us。旧场景2/3 结果请忽略。
## 2. 实验1：倾斜专家流量下的 Dispatch
### 2.1 场景1
**batch=256 对比表**

```
        cct_us                                hot_p99                                lat_p99                                step_us                                throughput_GBs
scheme   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop          islip packet_spray     ub_rg ub_rg_pop
zipf_s
0.0      58.37        83.61   48.94     49.24   39.63        76.68   44.14     44.44   35.48        69.56   36.96     37.26   58.77        85.61   49.34     49.64       32205.56     22486.45  38470.35  38235.06
0.3     116.81       154.15  117.46    117.76   99.89       136.66  103.04    103.34   38.06        97.17   40.55     40.85  117.21       156.15  117.86    118.16       16086.60     12192.19  16000.39  15959.61
0.7     333.71       368.00  331.27    331.57  302.89       336.70  305.80    306.10   87.75       245.32   90.84     91.14  334.11       370.00  331.67    331.97        5630.75      5106.13   5672.44   5667.31
0.9     460.44       494.86  451.54    451.84  423.31       456.07  426.29    426.59  147.77       342.04  150.98    151.28  460.84       496.86  451.94    452.24        4080.96      3797.12   4161.56   4158.79
```
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk2.png)
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk4.png)
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_sk8.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_sk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_sk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_sk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_sk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_sk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_sk8.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_sk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_sk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_sk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_sk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_sk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_sk8.png)
![exp1_dispatch_s1_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s1_hotcold_p99_vs_s.png)
![exp1_dispatch_s1_step_vs_batch.png](../results/ub_rg/figures/exp1_dispatch_s1_step_vs_batch.png)
![exp1_dispatch_s1_throughput_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s1_throughput_vs_s.png)
### 2.4 场景4
**batch=256 对比表**

```
             cct_us                         hot_p99                        lat_p99                        step_us                    throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray    ub_rg ub_rg_pop   packet_spray      ub_rg  ub_rg_pop
zipf_s
0.0           88.11    60.95     61.35        76.40   48.39     48.79        73.57   45.49     45.89        91.11    61.75     62.15       85328.79  123439.30  122632.94
0.3          214.93   198.42    198.82       166.67  117.61    118.01        97.91   67.47     67.87       217.93   199.22    199.62       34973.50   37884.93   37808.69
0.7          886.72   942.98    943.38       438.02  415.61    416.01       434.35  415.49    415.89       889.72   943.78    944.18        8476.49    7970.75    7967.37
0.9         1498.48  1618.92   1619.32       892.94  899.09    899.49       905.13  898.82    899.22      1501.48  1619.72   1620.12        5015.87    4642.73    4641.58
```
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk2.png)
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk4.png)
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_sk8.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_sk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_sk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_sk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_sk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_sk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_sk8.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_sk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_sk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_sk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_sk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_sk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_sk8.png)
![exp1_dispatch_s4_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s4_hotcold_p99_vs_s.png)
![exp1_dispatch_s4_step_vs_batch.png](../results/ub_rg/figures/exp1_dispatch_s4_step_vs_batch.png)
![exp1_dispatch_s4_throughput_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s4_throughput_vs_s.png)
## 3. 实验2：倾斜专家流量下的 Combine
### 3.1 场景1
**batch=256 对比表**

```
        cct_us                                hot_p99                                lat_p99                                step_us                                throughput_GBs
scheme   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop          islip packet_spray     ub_rg ub_rg_pop
zipf_s
0.0      56.07        78.75   47.81     48.11   46.28        43.26   43.40     43.70   35.09        65.48   36.02     36.32   56.47        80.75   48.21     48.51       33540.37     23869.66  39353.21  39107.18
0.3     111.07       147.42  117.31    117.61  102.76       113.45  103.51    103.81   38.39       131.65   39.68     39.98  111.47       149.42  117.71    118.01       16920.63     12747.50  16021.19  15980.31
0.7     321.67       356.30  331.16    331.46  305.47       323.75  306.12    306.42   90.24       335.37   91.25     91.55  322.07       358.30  331.56    331.86        5841.69      5273.92   5674.20   5669.06
0.9     446.82       480.73  450.27    450.57  426.18       449.19  426.75    427.05  150.55       457.65  151.61    151.91  447.22       482.73  450.67    450.97        4205.41      3908.75   4173.23   4170.45
```
![exp2_combine_s1_bar_step_vs_batch_s0.3_sk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.3_sk2.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_sk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_sk2.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_sk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_sk4.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_sk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_sk8.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_sk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_sk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_sk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_sk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_sk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_sk8.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_sk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_sk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_sk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_sk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_sk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_sk8.png)
![exp2_combine_s1_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp2_combine_s1_hotcold_p99_vs_s.png)
![exp2_combine_s1_step_vs_batch.png](../results/ub_rg/figures/exp2_combine_s1_step_vs_batch.png)
![exp2_combine_s1_throughput_vs_s.png](../results/ub_rg/figures/exp2_combine_s1_throughput_vs_s.png)
### 3.4 场景4
**batch=256 对比表**

```
             cct_us                         hot_p99                        lat_p99                        step_us                    throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray    ub_rg ub_rg_pop   packet_spray      ub_rg  ub_rg_pop
zipf_s
0.0           85.72    54.74     55.14        45.87   44.11     44.51        69.19   41.63     42.03        88.72    55.54     55.94       87731.50  137444.47  136445.41
0.3          225.70   196.96    197.36       178.96  126.83    127.23       190.00   66.93     67.33       228.70   197.76    198.16       33303.82   38163.69   38086.33
0.7          972.46   942.21    942.61       874.26  415.59    415.99       877.98  415.80    416.20       975.46   943.01    943.41        7729.08    7977.18    7973.80
0.9         1642.52  1617.58   1617.98      1481.39  898.21    898.61      1490.13  899.05    899.45      1645.52  1618.38   1618.78        4576.01    4646.56    4645.41
```
![exp2_combine_s4_bar_step_vs_batch_s0.7_sk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_sk2.png)
![exp2_combine_s4_bar_step_vs_batch_s0.7_sk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_sk4.png)
![exp2_combine_s4_bar_step_vs_batch_s0.7_sk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_sk8.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_sk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_sk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_sk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_sk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_sk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_sk8.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_sk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_sk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_sk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_sk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_sk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_sk8.png)
![exp2_combine_s4_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp2_combine_s4_hotcold_p99_vs_s.png)
![exp2_combine_s4_step_vs_batch.png](../results/ub_rg/figures/exp2_combine_s4_step_vs_batch.png)
![exp2_combine_s4_throughput_vs_s.png](../results/ub_rg/figures/exp2_combine_s4_throughput_vs_s.png)
## 4. 实验3：网络系统级 Dispatch+Combine 完成时间 (CCT) PDF
横轴优先为**端到端完成时间**（`e2e_us`/`step_us`：dispatch→GEMV→combine；GEMV 由 Zipf 专家负载与 batch 标定）。网络-only `cct_us` 仍写入 summary 供对照。对每个 (场景, BatchSize, Zipf S, EP) 组合，在多个随机种子下各跑一次 roundtrip，每次运行贡献一个系统 CCT 样本，以此得到系统 CCT 的概率密度分布（PDF，无 CDF）。
覆盖三个组网场景（与实验设计 §4.2.3 一致）：
- **场景1** 单层 Clos：EP ∈ {32, 64, 128}
- **场景4** Sparse CLOS：EP ∈ {128, 256, 512}
每场景单独出 PDF；另附跨场景对比图（S1-EP128 / S4-EP512）。线型区分方案（实线 ub_rg，点划线 ub_rg_pop，虚线 packet_spray）。
**系统 CCT 样本统计（µs，mean/std/count）**

```
                                 mean                                   std                               count
scheme                          islip packet_spray    ub_rg ub_rg_pop islip packet_spray  ub_rg ub_rg_pop islip packet_spray ub_rg ub_rg_pop
scenario ep_size batch zipf_s
1        32      16    0.0      13.89        18.25    16.92     17.52  0.33         0.61   0.39      0.39  96.0         96.0  96.0      96.0
                       0.3      14.35        20.18    18.61     19.21  0.62         0.92   0.74      0.74  96.0         96.0  96.0      96.0
                       0.7      19.05        25.68    23.45     24.05  1.06         1.12   1.07      1.07  96.0         96.0  96.0      96.0
                       0.9      21.34        27.71    25.36     25.96  1.17         1.18   1.02      1.02  96.0         96.0  96.0      96.0
                 64    0.0      31.94        45.48    33.07     33.67  0.65         1.07   0.68      0.68  96.0         96.0  96.0      96.0
                       0.3      39.05        58.07    44.22     44.82  1.60         1.71   1.82      1.82  96.0         96.0  96.0      96.0
                       0.7      63.61        81.94    67.58     68.18  1.62         1.75   1.49      1.49  96.0         96.0  96.0      96.0
                       0.9      72.56        90.41    75.54     76.14  1.61         1.68   1.29      1.29  96.0         96.0  96.0      96.0
                 256   0.0      98.02       155.52    93.30     93.90  1.80         1.73   1.33      1.33  96.0         96.0  96.0      96.0
                       0.3     141.92       211.79   147.57    148.17  2.21         2.41   3.01      3.01  96.0         96.0  96.0      96.0
                       0.7     238.55       305.85   242.21    242.81  2.72         3.36   2.67      2.67  96.0         96.0  96.0      96.0
                       0.9     273.98       340.61   275.59    276.19  2.48         2.74   1.95      1.95  96.0         96.0  96.0      96.0
         64      16    0.0      14.17        19.04    17.71     18.31  0.28         0.54   0.35      0.35  96.0         96.0  96.0      96.0
                       0.3      15.69        22.80    20.92     21.52  0.94         1.10   0.99      0.99  96.0         96.0  96.0      96.0
                       0.7      28.83        35.74    33.51     34.11  1.34         1.40   1.29      1.29  96.0         96.0  96.0      96.0
                       0.9      35.26        42.05    39.48     40.08  1.37         1.42   1.35      1.35  96.0         96.0  96.0      96.0
                 64    0.0      32.86        46.85    34.56     35.16  0.57         0.87   0.71      0.71  96.0         96.0  96.0      96.0
                       0.3      48.18        67.64    53.94     54.54  1.82         1.96   2.09      2.09  96.0         96.0  96.0      96.0
                       0.7     102.39       121.14   106.97    107.57  2.17         2.26   2.20      2.20  96.0         96.0  96.0      96.0
                       0.9     128.35       146.82   131.95    132.55  1.97         2.12   1.91      1.91  96.0         96.0  96.0      96.0
                 256   0.0     108.49       157.67    95.63     96.23  1.54         1.38   1.44      1.44  96.0         96.0  96.0      96.0
                       0.3     177.65       249.22   185.20    185.80  2.77         2.91   3.44      3.44  96.0         96.0  96.0      96.0
                       0.7     392.53       461.13   398.01    398.61  3.89         3.94   4.33      4.33  96.0         96.0  96.0      96.0
                       0.9     495.42       562.70   497.73    498.33  3.58         3.61   3.25      3.25  96.0         96.0  96.0      96.0
         128     16    0.0      14.31        19.61    18.32     18.92  0.23         0.45   0.41      0.41  96.0         96.0  96.0      96.0
                       0.3      18.30        25.77    23.70     24.30  1.24         1.31   1.20      1.20  96.0         96.0  96.0      96.0
                       0.7      44.82        51.93    50.04     50.64  1.66         1.81   1.77      1.77  96.0         96.0  96.0      96.0
                       0.9      60.89        67.85    65.25     65.85  1.50         1.55   1.61      1.61  96.0         96.0  96.0      96.0
                 64    0.0      33.74        48.33    35.81     36.41  0.56         0.83   0.74      0.74  96.0         96.0  96.0      96.0
                       0.3      59.13        79.58    65.51     66.11  2.12         2.12   2.79      2.79  96.0         96.0  96.0      96.0
                       0.7     165.36       184.61   170.93    171.53  2.72         2.85   3.10      3.10  96.0         96.0  96.0      96.0
                       0.9     228.47       247.17   232.57    233.17  2.71         2.61   2.69      2.69  96.0         96.0  96.0      96.0
                 256   0.0     114.74       159.71    97.39     97.99  1.38         1.43   1.25      1.25  96.0         96.0  96.0      96.0
                       0.3     221.01       293.46   229.86    230.46  3.30         3.55   4.97      4.97  96.0         96.0  96.0      96.0
                       0.7     641.97       711.63   648.68    649.28  5.70         5.88   5.62      5.62  96.0         96.0  96.0      96.0
                       0.9     893.20       961.07   895.41    896.01  4.38         4.77   4.70      4.70  96.0         96.0  96.0      96.0
4        128     16    0.0        NaN        19.64    18.72     19.52   NaN         0.49   0.41      0.41   NaN         96.0  96.0      96.0
                       0.3        NaN        25.87    24.10     24.90   NaN         1.33   1.30      1.30   NaN         96.0  96.0      96.0
                       0.7        NaN        53.23    50.72     51.52   NaN         1.88   1.84      1.84   NaN         96.0  96.0      96.0
                       0.9        NaN        69.79    66.50     67.30   NaN         1.68   1.67      1.67   NaN         96.0  96.0      96.0
                 64    0.0        NaN        48.87    37.02     37.82   NaN         0.89   0.80      0.80   NaN         96.0  96.0      96.0
                       0.3        NaN        81.16    66.60     67.40   NaN         2.23   2.70      2.70   NaN         96.0  96.0      96.0
                       0.7        NaN       191.34   175.78    176.58   NaN         3.31   3.61      3.61   NaN         96.0  96.0      96.0
                       0.9        NaN       256.94   241.35    242.15   NaN         3.21   4.15      4.15   NaN         96.0  96.0      96.0
                 256   0.0        NaN       164.78   103.52    104.32   NaN         1.52   1.73      1.73   NaN         96.0  96.0      96.0
                       0.3        NaN       303.31   235.36    236.16   NaN         3.81   6.17      6.17   NaN         96.0  96.0      96.0
                       0.7        NaN       741.83   675.95    676.75   NaN         5.59  10.10     10.10   NaN         96.0  96.0      96.0
                       0.9        NaN      1005.30   940.94    941.74   NaN         6.49   7.65      7.65   NaN         96.0  96.0      96.0
         256     16    0.0        NaN        20.10    19.24     20.04   NaN         0.42   0.39      0.39   NaN         96.0  96.0      96.0
                       0.3        NaN        29.38    27.91     28.71   NaN         1.48   1.72      1.72   NaN         96.0  96.0      96.0
                       0.7        NaN        80.19    78.68     79.48   NaN         2.14   2.82      2.82   NaN         96.0  96.0      96.0
                       0.9        NaN       117.54   116.59    117.39   NaN         2.17   2.79      2.79   NaN         96.0  96.0      96.0
                 64    0.0        NaN        50.02    38.67     39.47   NaN         0.84   0.76      0.76   NaN         96.0  96.0      96.0
                       0.3        NaN        95.70    81.71     82.51   NaN         2.39   3.15      3.15   NaN         96.0  96.0      96.0
                       0.7        NaN       297.67   290.11    290.91   NaN         3.99   7.06      7.06   NaN         96.0  96.0      96.0
                       0.9        NaN       446.07   444.28    445.08   NaN         4.09   6.45      6.45   NaN         96.0  96.0      96.0
                 256   0.0        NaN       166.61   105.32    106.12   NaN         1.63   1.80      1.80   NaN         96.0  96.0      96.0
                       0.3        NaN       359.03   298.33    299.13   NaN         5.00   8.53      8.53   NaN         96.0  96.0      96.0
                       0.7        NaN      1164.55  1135.92   1136.72   NaN         6.97  13.79     13.79   NaN         96.0  96.0      96.0
                       0.9        NaN      1755.41  1751.01   1751.81   NaN         8.11  13.01     13.01   NaN         96.0  96.0      96.0
         512     16    0.0        NaN        20.48    19.61     20.41   NaN         0.42   0.39      0.39   NaN         96.0  96.0      96.0
                       0.3        NaN        33.72    32.30     33.10   NaN         1.78   1.66      1.66   NaN         96.0  96.0      96.0
                       0.7        NaN       124.55   125.46    126.26   NaN         2.53   4.53      4.53   NaN         96.0  96.0      96.0
                       0.9        NaN       204.37   208.81    209.61   NaN         2.98   4.56      4.56   NaN         96.0  96.0      96.0
                 64    0.0        NaN        50.74    40.62     41.42   NaN         0.61   0.74      0.74   NaN         96.0  96.0      96.0
                       0.3        NaN       112.93    99.70    100.50   NaN         2.64   4.48      4.48   NaN         96.0  96.0      96.0
                       0.7        NaN       470.37   475.54    476.34   NaN         5.21   9.49      9.49   NaN         96.0  96.0      96.0
                       0.9        NaN       788.41   811.40    812.20   NaN         5.32   9.52      9.52   NaN         96.0  96.0      96.0
                 256   0.0        NaN       169.07   111.37    112.17   NaN         1.75   1.54      1.54   NaN         96.0  96.0      96.0
                       0.3        NaN       427.84   371.10    371.90   NaN         5.79  10.81     10.81   NaN         96.0  96.0      96.0
                       0.7        NaN      1851.71  1876.08   1876.88   NaN         9.29  19.99     19.99   NaN         96.0  96.0      96.0
                       0.9        NaN      3121.05  3216.35   3217.15   NaN        10.34  20.26     20.26   NaN         96.0  96.0      96.0
```
### 4.1 场景1 PDF
![exp3_pdf_s1_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.3.png)
![exp3_pdf_s1_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.7.png)
![exp3_pdf_s1_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.9.png)
![exp3_pdf_s1_b16_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.png)
![exp3_pdf_s1_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.3.png)
![exp3_pdf_s1_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.7.png)
![exp3_pdf_s1_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.9.png)
![exp3_pdf_s1_b256_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.png)
![exp3_pdf_s1_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.3.png)
![exp3_pdf_s1_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.7.png)
![exp3_pdf_s1_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.9.png)
![exp3_pdf_s1_b64_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.png)
### 4.4 场景4 PDF
![exp3_pdf_s4_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.3.png)
![exp3_pdf_s4_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.7.png)
![exp3_pdf_s4_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.9.png)
![exp3_pdf_s4_b16_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.png)
![exp3_pdf_s4_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.3.png)
![exp3_pdf_s4_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.7.png)
![exp3_pdf_s4_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.9.png)
![exp3_pdf_s4_b256_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.png)
![exp3_pdf_s4_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.3.png)
![exp3_pdf_s4_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.7.png)
![exp3_pdf_s4_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.9.png)
![exp3_pdf_s4_b64_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.png)
### 4.4 跨场景对比 PDF（S1-EP128 / S4-EP512）
![exp3_pdf_compare_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.3.png)
![exp3_pdf_compare_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.7.png)
![exp3_pdf_compare_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.9.png)
![exp3_pdf_compare_b16_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.png)
![exp3_pdf_compare_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.3.png)
![exp3_pdf_compare_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.7.png)
![exp3_pdf_compare_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.9.png)
![exp3_pdf_compare_b256_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.png)
![exp3_pdf_compare_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.3.png)
![exp3_pdf_compare_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.7.png)
![exp3_pdf_compare_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.9.png)
![exp3_pdf_compare_b64_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.png)
### 4.x Roundtrip Step vs EP（汇总）
![exp3_s1_step_vs_ep.png](../results/ub_rg/figures/exp3_s1_step_vs_ep.png)
![exp3_s4_step_vs_ep.png](../results/ub_rg/figures/exp3_s4_step_vs_ep.png)
## 5. 方案对比摘要
- **场景1** 平均 step（三方案共有参数格）：UB_RG=129.6µs vs POP=129.9µs（POP/RG=1.00×） vs Spray=150.0µs（Spray/RG=1.16×）
- **场景1** ub_rg CCT/König：mean=1.304，median=1.122
- **场景1** ub_rg_pop CCT/König：mean=1.321，median=1.133
- **场景1** packet_spray CCT/König：mean=1.493，median=1.314
- **场景1** islip CCT/König：mean=1.188，median=1.025
- **场景4** 平均 step（三方案共有参数格）：UB_RG=378.4µs vs POP=378.8µs（POP/RG=1.00×） vs Spray=362.6µs（Spray/RG=0.96×）
- **场景4** ub_rg CCT/König：mean=1.253，median=1.058
- **场景4** ub_rg_pop CCT/König：mean=1.270，median=1.063
- **场景4** packet_spray CCT/König：mean=1.318，median=1.111
## 6. 双引擎对比（逐包 vs 行为级）
在相同 (scenario, scheme, mode, batch, zipf_s, ep_size) 键上对齐 step_us / lat_p99。
对齐样本 **72** 组；step 比值（packet/behavioral）均值=684.359，中位数=40.705。
```
          exp  scenario       scheme     mode  batch  zipf_s  ep_size  step_packet  p99_packet  step_behav  p99_behav  step_ratio
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      13.415      8.509       4.705
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      14.975     10.100       4.215
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      18.094     13.543       3.488
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      25.525     20.228       7.912
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      27.152     21.720       7.438
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      30.462     24.982       6.630
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      33.657     27.589       8.599
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      35.181     29.031       8.226
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      38.491     32.278       7.519
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766       9.755      6.658       3.165
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766      11.575      8.380       2.668
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766      15.310     12.020       2.017
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      11.197      7.673      89.798
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      12.770      9.252      78.736
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      16.204     12.656      62.049
exp1_dispatch         1        ub_rg dispatch     16     0.7      128      511.074      21.721      24.967     19.022      20.470
exp1_dispatch         1        ub_rg dispatch     16     0.7      128      511.074      21.721      26.834     20.140      19.046
exp1_dispatch         1        ub_rg dispatch     16     0.7      128      511.074      21.721      30.568     22.541      16.719
exp1_dispatch         1        ub_rg dispatch     16     0.9      128     3507.593      31.352      32.565     26.513     107.711
exp1_dispatch         1        ub_rg dispatch     16     0.9      128     3507.593      31.352      34.432     27.628     101.870
```
若该比值显著偏离 1，不能仅解释为“逐包栈静态开销”。当前逐包实现还含50µs REQ pacing、10ms stale-credit 回收，且两引擎的本地专家和场景2/3plane 映射不一致；在统一输入、完成守恒和异常门禁通过前，这里是**交叉验证失败证据**，不是行为级绝对值校准。
- **packet** 同参数格平均：POP/RG=5.741×，Spray/RG=0.362×
- **behavioral** 同参数格平均：POP/RG=1.007×，Spray/RG=1.143×
## 7. 结论
- 当前 UB_RG 配置包的 CCT 更接近自定义 König 下界；由于 plane、path delay、jitter 与 barrier 尚未统一，这不是目的侧准入的受控因果结论。
- UB_RG_POP（SHMEM-POP）与 RG 共享目的侧节奏/König 渐近；Push→Pull 多付一次单向启动，均匀小负载时常接近 RG，高偏斜/两层上偶发更差。
- 当前 Packet Spray 配置包在倾斜流量下 p99/CCT 更大；需要消除上述混杂并统一计时起点后再解释机制原因。
- 当前 CCT 只包含网络 dispatch/combine 与屏障口径；Exp3 已计入按 Zipf/batch 标定的 GEMV straggler；更细 HBM/算子队列仍未建模。
- 逐包引擎可用于调试控制面与数据面交互；当前性能结果尚未通过完成守恒和跨引擎门禁，不能作为行为级绝对时延校准。
## 8. 复现方法
当前报告主体由行为级引擎生成。复现默认矩阵与 Exp3 PDF：
```bash
cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus --disable-python -d optimized
./ns3 build ub_rg-dispatch-experiment
cd ..
python3 run_ub_rg_experiments.py --engine behavioral
python3 run_ub_rg_experiments.py --engine behavioral --exp3-pdf --seeds 96 --batches 16,64,256
python3 analyze_ub_rg_experiments.py --engine behavioral
```
