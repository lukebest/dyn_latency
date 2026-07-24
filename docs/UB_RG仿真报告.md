# UB_RG 网络仿真报告
> **可信性状态：实现证据存在，性能结论未验证。** 行为级结果仅作为网络机制假设；方案间路由、path delay、jitter 与 barrier 混杂尚未消除，逐包性能矩阵也未通过完成守恒与跨引擎校验。绝对硬件时延与完整POP硅片实现不得据此下结论；Exp3 GEMV 为标定服务模型。详见[UB_RG仿真可信性评估报告](./UB_RG仿真可信性评估报告.html)。
## 1. 主要实验结论
> 结论适用于场景1/4；Exp1/2 为网络子系统；Exp3 含 Zipf×batch GEMV straggler；启动偏差为 N(0,σ²)，σ∈{0,2,4,8} µs。
- **配置包输出差异**：Exp1 三方案共有参数格中，POP/RG 平均为 **1.005×**，Spray/RG 平均为 **1.088×**。这是当前配置包的联合差异；plane、path delay、jitter 和 barrier 尚未统一，不能把比值单独归因于目的侧配速（见 §1.1）。
- **POP 启动开销会被负载摊薄**：batch=16 时 POP/RG=**1.009×**，batch=256 时为 **1.002×**；结果符合“多一次 one-way 启动、稳态节拍与 RG 相同”的模型预期。
- **场景1 iSLIP（匹配对照）**：与 `ub_rg` 共路径钉扎/REQ-GNT/RTT/barrier，仅 SW 仲裁不同；Exp1 iSLIP/RG 平均 **1.001×**（中位 0.998×）。batch=16 为 **1.006×**，batch=256 为 **0.996×**。这是文档 §2.7「每 τ_g matching」相对当前模型「每出口独立 RR」的对照。
- **Exp3（S1）iSLIP/RG** 平均 **1.000×**。 Exp3 端到端中 GEMV 约占 e2e 的 **48%**，调度差异被计算 straggler 摊薄，故 iSLIP≈RG。 iSLIP 另覆盖 batch∈{128,256,512}（与 RG 共有格上比值如下）。
- **瓶颈下界**：CCT/König 中位数为 ub_rg=1.227、ub_rg_pop=1.232、packet_spray=1.472、islip=1.256；它证明输出符合当前方程，但不是排除混杂后的硬件性能验证。
- **拓扑范围**：主矩阵为场景1（Clos+iSLIP）与场景4（Sparse CLOS 512P）。
- **Exp3**：端到端含 GEMV；`gemv_us` 随 Zipf 热点与 batch 变化。
- 当前 UB_RG 配置包的 CCT 更接近自定义 König 下界；与 Spray 的比值是**配置包联合差异**，不是“仅改目的侧准入”的受控因果结论（原因见 §1.1）。
- UB_RG_POP（近似模型）与 RG 共享目的侧节奏/König 渐近；多付一次 one-way 启动，小 batch 略慢、大负载接近 RG。
- **场景1 iSLIP（Exp1）**：与 `ub_rg` 同路径钉扎与 REQ/GNT，仅将每出口独立 RR 换成 iSLIP matching；共有格 step 平均 **1.001×**（batch=16 为 1.006×；batch=256 为 0.996×）。差异应解读为调度匹配算法之差，而非另一套数据面。
- **场景1 iSLIP（Exp3）**：端到端 step 相对 RG 平均 **1.000×**（共有 batch 格）；iSLIP 另扫 batch∈{128,256,512}。因 Zipf×batch 标定的 GEMV 占 e2e 很大比例，网络调度差异被摊薄，iSLIP 与 RG 几乎重合。
- 当前 Packet Spray 配置包在倾斜流量下 p99/CCT 更大；在统一 plane/path/jitter/barrier 之前，不宜把差距全部归因于“无目的侧配速”。
- Exp3 端到端含按 Zipf/batch 标定的 GEMV straggler；更细 HBM/算子队列仍未建模。
- 逐包引擎可用于协议调试；性能门禁通过前不能校准行为级绝对时延。
### 1.1 为何说“不是目的侧准入的受控因果结论”
受控因果结论需要：**只改变一个机制变量**，其余路径、时延、屏障、负载相同，再比较 CCT。当前行为级里，把 scheme 从 `packet_spray` 换成 `ub_rg` 会**同时**改变多处，因此 Spray/RG 比值不能解读为“目的侧准入单独带来的收益”。

| 混杂维度 | `packet_spray` | `ub_rg` | 为何干扰归因 |
|---|---|---|---|
| **plane 映射** | 源序 RR（`AssignSprayPlane`） | 源/目的 group 钉扎（`AssignRgPlane`） | 热点落到的出口集合不同，队列长度本身就变 |
| **path delay** | 经交换机下行 FIFO 排队推进 | 注入后按 hop 公式到达 + 近零队 | 数据面时延模型不同，不只是“有没有 grant” |
| **jitter** | 无 RG 式到达抖动 | 到达叠加 `U(0,1.5)·τ_g` | 人为噪声改变尾部，混入方案差 |
| **barrier** | 软件屏障更重（场景1 约 2.0µs） | BSP 轻屏障（场景1 约 0.4µs） | `step_us` 含屏障；即使边界 CCT 相同，step 也会因屏障差拉开 |

因此报告写的是**配置包输出差异**，不是“目的侧 1/τ_g 准入”的净效应。若要做受控因果，应固定同一 plane 映射、同一 hop/队列公式、同一 jitter 与 barrier，**只开关目的侧 grant 节拍**，再比 CCT。

相对地，场景1 的 **iSLIP vs `ub_rg`** 是受控的调度对照：二者共用 `AssignRgPlane` 路径钉扎、同一 RTT_rg、同一 hop/jitter/barrier 与同一源侧 FCFS grant 注入；**唯一差别**是交换机每 τ_g 的授权挑选——`ub_rg` 为每目的出口独立对 src 做 RR，`islip` 为平面内 bipartite matching（request/grant/accept，对齐 `ub_request_grant.md` §2.7）。因此 iSLIP/RG 比值可归因于匹配算法，而 Spray/RG 仍不能。
## 2. 实验概述
本报告对应 [UB_RG实验设计.md](./UB_RG实验设计.md) §4.2.1–§4.2.3，在 `ns-3-ub` 中用自包含行为级仿真器 `scratch/ub_rg-dispatch-experiment.cc` 对比 **UB_RG（request/grant）**、**UB_RG_POP（SHMEM-POP）** 与 **Packet Spray（自由注入）**。结构对齐参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html)：组网 → 方案差异 → 扫参结果。
### 2.1 仿真环境、微架构抽象与 CCT 口径

| 项目 | 配置 / 抽象 |
|---|---|
| 执行主机 | Linux 6.17.0-40-generic（x86_64） |
| 工具链 | Python 3.12.3；g++ 13.3.0；CMake 3.28.3；ns-3.44 optimized build |
| 当前报告引擎 | `behavioral`；grain 级行为离散事件模型：不逐包执行完整协议栈，而以串行化服务器、FIFO、固定传播/流水时延和控制 RTT 表示网络。 |
| 并行方式 | 单次仿真保持单线程确定性；参数点由 Python `ProcessPoolExecutor` 并行 |
| 端点模型 | 每个 NPU 对应一个网络端点/专家；每 token 的每个 TopK 路由项形成一个 7 KB grain |
| 网络接口 | 每 NPU 8 个 400 Gbit/s 上联；有效 50 GB/s/端口；τ_g=7168/50e9≈143.36 ns |
| 交换结构 | 50 ns/跳传播 + 150 ns/跳流水；场景1 单层 Clos；场景4 Sparse CLOS（PFM/SW-S/SW-a-b） |
| 启动偏差 | 各 NPU 起点 ~N(0,σ²)，再平移使最早 NPU 于 t=0；σ∈{0,2,4,8} µs |
| 负载生成 | TopK=8；Zipf S；主矩阵 seed=1；Exp3 PDF 每格 96 seeds |

#### 微架构模型边界

- **已建模的是通信微架构**：NPU 端口串行化、8 平面选路、Spray 目的出口/两层 Clos 中段队列、RG nominal 授权节拍、POP 的启动时延/PullCredit，以及 BSP 屏障常量。
- **因果比较尚未闭环**：Spray 与 RG 同时改变 plane 映射、path delay 公式、jitter 和固定 barrier；当前比值是配置包差异，不能单独归因于目的侧准入。
- **计算侧（Exp3）**：`gemv_us = max_e N_e·τ_tok`（均匀 Zipf、batch=256 时约 80µs/专家）；`e2e_us = dispatch_cct + gemv_us + combine_cct`。
- **未建模**：完整 SM/HBM/cache、专家算力异构；iSLIP 仅替换 SW 匹配算法（其余同 `ub_rg`）。
- 主矩阵为 **场景1 + 场景4**（已去掉场景2/3）。

#### CCT 的准确口径

- Exp1/2：`cct_us` / `step_us` = 网络阶段（含启动偏差）+ barrier。
- Exp3：`cct_us` = 网络往返；`gemv_us` / `e2e_us` / `step_us(=e2e+barriers)` 含 Zipf×batch GEMV。

### 2.2 组网方案

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

### 2.3 网络方案与实现差异

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
| `islip` | 仿真 scheme | 与 `ub_rg` 相同：路径钉扎 + REQ/GNT + RTT/barrier；仅将每出口独立 RR 换成每 τ_g 的 iSLIP matching（对齐 `ub_request_grant.md` §2.7） |

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

CLI：`--scheme=ub_rg|ub_rg_pop|packet_spray|islip`；`--start-skew-us=0|2|4|8`（Normal σ）。
### 2.4 模型假设与简化
- 端口 400Gbps（有效 50GB/s），grain = 7KB，τ_g ≈ 143.36 ns
- 链路建模为串行化服务器 + FIFO；交换机直通 150 ns/跳，传播 50 ns/跳
- UB_RG：目的侧按 1 grain/τ_g 授权节奏 + 源端口 FCFS
- UB_RG_POP：同目的侧节奏；startup = RTT_rg + oneWay（Push→Grant→Pull）；PullCredit 窗口保稳态流水（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）
- Packet Spray：自由注入；软件屏障在分析阶段叠加
- 场景4 按 Sparse CLOS 路径类建模；场景1 另跑 iSLIP（同 ub_rg，仅 matching 不同）
- 启动偏差：每 NPU ~N(0,σ²) 后平移至最早为 0；σ∈{0,2,4,8}µs
- Exp3：GEMV = max 专家 token 数 × τ_tok
- 专家与 NPU 1:1；TopK=8
### 2.5 参数矩阵（裁剪）
| 实验 | mode | 场景 | Batch | Zipf S | EP | 启动偏差 | 调度 |
|---|---|---|---|---|---|---|---|
| 1 Dispatch | dispatch | 1,4 | 16,256 | 0,0.3,0.7,0.9 | full | σ=0/2/4/8 µs | S1:+islip |
| 2 Combine | combine | 同实验1 | 同左 | 同左 | full | 同左 | 同左 |
| 3 Roundtrip+GEMV | roundtrip | 1→{32,64,128}; 4→{128,256,512} | 256（S1 iSLIP 另含 128/512） | 同左 | 上列 | 同左 | 同左 |
| 3 PDF | roundtrip | 同上 | 16,64,128,256,512 | 同左 | 每格 96 seeds | σ=4µs | 同左 |

引擎：**behavioral**；成功汇总运行数：**41200**。原始结果：`results/ub_rg/`。
> 上表对齐当前 runner：仅场景1+4；启动偏差为 N(0,σ²)（σ∈{0,2,4,8}）；场景1 含 iSLIP；Exp3 输出 gemv_us/e2e_us。旧场景2/3 结果请忽略。
## 3. 实验1：倾斜专家流量下的 Dispatch
### 3.1 场景1
**batch=256 对比表**

```
        cct_us                                hot_p99                                lat_p99                                step_us                                throughput_GBs
scheme   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop          islip packet_spray     ub_rg ub_rg_pop
zipf_s
0.0      62.53        93.44   62.98     63.28   52.80        86.59   54.08     54.38   43.46        79.30   44.36     44.66   62.93        95.44   63.38     63.68       31946.64     20413.70  31734.38  31565.41
0.3     129.31       163.74  130.13    130.43  110.13       145.81  110.16    110.46   47.44       106.45   48.26     48.56  129.71       165.74  130.53    130.83       14712.67     11529.51  14629.79  14595.28
0.7     341.40       376.30  340.67    340.97  312.62       345.30  312.71    313.01   97.58       253.98   97.96     98.26  341.80       378.30  341.07    341.37        5510.20      4996.34   5522.74   5517.87
0.9     461.67       502.33  463.52    463.82  433.01       464.11  433.22    433.52  157.53       350.08  157.86    158.16  462.07       504.33  463.92    464.22        4073.38      3741.73   4057.39   4054.76
```
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk0.png)
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk2.png)
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk4.png)
![exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_batch_s0.7_nsk8.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk0.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk8.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk0.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk8.png)
![exp1_dispatch_s1_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s1_hotcold_p99_vs_s.png)
![exp1_dispatch_s1_step_vs_batch.png](../results/ub_rg/figures/exp1_dispatch_s1_step_vs_batch.png)
![exp1_dispatch_s1_throughput_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s1_throughput_vs_s.png)
### 3.4 场景4
**batch=256 对比表**

```
             cct_us                         hot_p99                        lat_p99                        step_us                    throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray    ub_rg ub_rg_pop   packet_spray      ub_rg  ub_rg_pop
zipf_s
0.0          101.97    75.96     76.36        90.57   61.50     61.90        87.53   57.46     57.86       104.97    76.76     77.16       75407.55  103340.93  102753.10
0.3          228.08   213.48    213.88       180.41  128.30    128.70       111.05   78.38     78.78       231.08   214.28    214.68       33081.44   35416.08   35349.08
0.7          899.87   958.66    959.06       451.07  425.99    426.39       446.92  425.85    426.25       902.87   959.46    959.86        8354.68    7842.63    7839.36
0.9         1510.58  1634.46   1634.86       905.85  909.34    909.74       917.71  909.03    909.43      1513.58  1635.26   1635.66        4976.06    4599.06    4597.93
```
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk0.png)
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk2.png)
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk4.png)
![exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_batch_s0.7_nsk8.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk0.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk8.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk0.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk8.png)
![exp1_dispatch_s4_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s4_hotcold_p99_vs_s.png)
![exp1_dispatch_s4_step_vs_batch.png](../results/ub_rg/figures/exp1_dispatch_s4_step_vs_batch.png)
![exp1_dispatch_s4_throughput_vs_s.png](../results/ub_rg/figures/exp1_dispatch_s4_throughput_vs_s.png)
## 4. 实验2：倾斜专家流量下的 Combine
### 4.1 场景1
**batch=256 对比表**

```
        cct_us                                hot_p99                                lat_p99                                step_us                                throughput_GBs
scheme   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop   islip packet_spray   ub_rg ub_rg_pop          islip packet_spray     ub_rg ub_rg_pop
zipf_s
0.0      59.29        88.39   58.76     59.06   52.24        52.72   52.51     52.81   42.55        75.10   42.94     43.24   59.69        90.39   59.16     59.46       33116.31     21595.10  33388.06  33204.07
0.3     125.26       155.26  125.13    125.43  111.32       121.29  111.34    111.64   46.71       139.49   47.06     47.36  125.66       157.26  125.53    125.83       15079.45     12143.26  15094.84  15058.37
0.7     339.01       364.14  339.01    339.31  314.01       331.60  313.99    314.29   98.09       343.21   98.29     98.59  339.41       366.14  339.41    339.71        5546.79      5163.45   5546.79   5541.88
0.9     458.14       488.58  458.11    458.41  434.57       457.04  434.59    434.89  158.16       465.49  158.27    158.57  458.54       490.58  458.51    458.81        4103.10      3847.30   4103.35   4100.67
```
![exp2_combine_s1_bar_step_vs_batch_s0.7_nsk0.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_nsk0.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_nsk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_nsk2.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_nsk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_nsk4.png)
![exp2_combine_s1_bar_step_vs_batch_s0.7_nsk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_batch_s0.7_nsk8.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk0.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk8.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk0.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk8.png)
![exp2_combine_s1_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp2_combine_s1_hotcold_p99_vs_s.png)
![exp2_combine_s1_step_vs_batch.png](../results/ub_rg/figures/exp2_combine_s1_step_vs_batch.png)
![exp2_combine_s1_throughput_vs_s.png](../results/ub_rg/figures/exp2_combine_s1_throughput_vs_s.png)
### 4.4 场景4
**batch=256 对比表**

```
             cct_us                         hot_p99                        lat_p99                        step_us                    throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray   ub_rg ub_rg_pop packet_spray    ub_rg ub_rg_pop   packet_spray      ub_rg  ub_rg_pop
zipf_s
0.0           96.46    65.94     66.34        57.00   55.05     55.45        80.90   51.32     51.72        99.46    66.74     67.14       79311.52  118633.85  117862.97
0.3          235.11   206.35    206.75       188.38  136.91    137.31       199.42   75.93     76.33       238.11   207.15    207.55       32030.65   36515.26   36444.26
0.7          981.87   951.63    952.03       883.67  423.60    424.00       887.40  422.61    423.01       984.87   952.43    952.83        7655.80    7899.18    7895.86
0.9         1651.94  1627.00   1627.40      1490.80  904.87    905.27      1499.55  905.85    906.25      1654.94  1627.80   1628.20        4550.10    4619.86    4618.72
```
![exp2_combine_s4_bar_step_vs_batch_s0.7_nsk0.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_nsk0.png)
![exp2_combine_s4_bar_step_vs_batch_s0.7_nsk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_nsk2.png)
![exp2_combine_s4_bar_step_vs_batch_s0.7_nsk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_nsk4.png)
![exp2_combine_s4_bar_step_vs_batch_s0.7_nsk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_batch_s0.7_nsk8.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk0.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk8.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk0.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk8.png)
![exp2_combine_s4_hotcold_p99_vs_s.png](../results/ub_rg/figures/exp2_combine_s4_hotcold_p99_vs_s.png)
![exp2_combine_s4_step_vs_batch.png](../results/ub_rg/figures/exp2_combine_s4_step_vs_batch.png)
![exp2_combine_s4_throughput_vs_s.png](../results/ub_rg/figures/exp2_combine_s4_throughput_vs_s.png)
## 5. 实验3：网络系统级 Dispatch+Combine 完成时间 (CCT) PDF
横轴优先为**端到端完成时间**（`e2e_us`/`step_us`：dispatch→GEMV→combine；GEMV 由 Zipf 专家负载与 batch 标定）。网络-only `cct_us` 仍写入 summary 供对照。对每个 (场景, BatchSize, Zipf S, EP) 组合，在多个随机种子下各跑一次 roundtrip，每次运行贡献一个系统 CCT 样本，以此得到系统 CCT 的概率密度分布（PDF，无 CDF）。
覆盖三个组网场景（与实验设计 §4.2.3 一致）：
- **场景1** 单层 Clos：EP ∈ {32, 64, 128}；PDF batch∈{16,64,128,256,512}（含 iSLIP）
- **场景4** Sparse CLOS：EP ∈ {128, 256, 512}；PDF batch∈{16,64,128,256,512}
每场景单独出 PDF；另附跨场景对比图（S1-EP128 / S4-EP512）。线型区分方案（实线 ub_rg，点划线 ub_rg_pop，虚线 packet_spray，点线 islip）。
**系统 CCT 样本统计（µs，mean/std/count）**

```
                                  mean                                   std                               count
scheme                           islip packet_spray    ub_rg ub_rg_pop islip packet_spray  ub_rg ub_rg_pop islip packet_spray ub_rg ub_rg_pop
scenario ep_size batch zipf_s
1        32      16    0.0       41.35        41.61    41.47     42.07  4.37         4.25   4.38      4.38  96.0         96.0  96.0      96.0
                       0.3       42.17        42.37    42.26     42.86  4.40         4.15   4.41      4.41  96.0         96.0  96.0      96.0
                       0.7       45.33        45.40    45.39     45.99  4.32         4.21   4.30      4.30  96.0         96.0  96.0      96.0
                       0.9       46.84        46.72    46.89     47.49  4.34         4.33   4.33      4.33  96.0         96.0  96.0      96.0
                 64    0.0       56.94        66.01    56.99     57.59  4.47         4.08   4.52      4.52  96.0         96.0  96.0      96.0
                       0.3       64.10        74.68    64.13     64.73  4.86         4.86   4.75      4.75  96.0         96.0  96.0      96.0
                       0.7       85.03        96.52    85.16     85.76  5.15         5.15   5.11      5.11  96.0         96.0  96.0      96.0
                       0.9       93.22       104.73    93.24     93.84  4.85         5.45   4.85      4.85  96.0         96.0  96.0      96.0
                 128   0.0       77.10       100.63    77.12     77.72  4.48         4.48   4.55      4.55  96.0         96.0  96.0      96.0
                       0.3       95.81       123.68    95.98     96.58  5.05         5.20   5.19      5.19  96.0         96.0  96.0      96.0
                       0.7      142.38       169.59   142.55    143.15  5.56         5.78   5.60      5.60  96.0         96.0  96.0      96.0
                       0.9      159.19       187.14   159.29    159.89  5.35         5.66   5.36      5.36  96.0         96.0  96.0      96.0
                 256   0.0      116.20       171.71   116.02    116.62  4.58         4.85   4.63      4.63  96.0         96.0  96.0      96.0
                       0.3      163.20       224.75   163.30    163.90  5.04         5.33   4.90      4.90  96.0         96.0  96.0      96.0
                       0.7      258.04       318.18   258.09    258.69  5.83         6.64   5.74      5.74  96.0         96.0  96.0      96.0
                       0.9      292.07       352.89   292.14    292.74  5.51         6.20   5.49      5.49  96.0         96.0  96.0      96.0
                 512   0.0      193.33       316.30   193.25    193.85  4.76         5.18   4.75      4.75  96.0         96.0  96.0      96.0
                       0.3      299.16       428.28   299.46    300.06  5.44         5.90   5.35      5.35  96.0         96.0  96.0      96.0
                       0.7      489.80       616.32   489.89    490.49  5.38         6.50   5.33      5.33  96.0         96.0  96.0      96.0
                       0.9      557.89       685.37   558.13    558.73  5.07         6.48   5.04      5.04  96.0         96.0  96.0      96.0
         64      16    0.0       47.23        47.60    47.35     47.95  3.96         3.88   3.97      3.97  96.0         96.0  96.0      96.0
                       0.3       48.85        49.26    48.99     49.59  3.99         3.75   4.02      4.02  96.0         96.0  96.0      96.0
                       0.7       57.10        57.51    57.18     57.78  4.30         4.16   4.21      4.21  96.0         96.0  96.0      96.0
                       0.9       62.41        62.67    62.51     63.11  4.52         4.24   4.44      4.44  96.0         96.0  96.0      96.0
                 64    0.0       63.36        72.59    63.55     64.15  4.00         3.57   3.93      3.93  96.0         96.0  96.0      96.0
                       0.3       76.35        87.89    76.61     77.21  4.23         4.32   4.16      4.16  96.0         96.0  96.0      96.0
                       0.7      127.50       139.19   127.70    128.30  5.00         5.02   5.07      5.07  96.0         96.0  96.0      96.0
                       0.9      152.52       164.48   152.78    153.38  5.05         4.87   5.01      5.01  96.0         96.0  96.0      96.0
                 128   0.0       83.59       107.83    83.59     84.19  4.03         3.72   4.10      4.10  96.0         96.0  96.0      96.0
                       0.3      118.13       146.75   118.18    118.78  4.79         4.28   4.84      4.84  96.0         96.0  96.0      96.0
                       0.7      224.04       251.49   224.51    225.11  5.32         5.07   5.23      5.23  96.0         96.0  96.0      96.0
                       0.9      273.75       301.72   274.15    274.75  5.00         5.20   5.16      5.16  96.0         96.0  96.0      96.0
                 256   0.0      123.33       179.39   123.24    123.84  4.12         4.03   3.99      3.99  96.0         96.0  96.0      96.0
                       0.3      203.93       265.99   204.44    205.04  5.17         4.77   5.23      5.23  96.0         96.0  96.0      96.0
                       0.7      416.69       476.66   417.18    417.78  5.07         5.73   4.91      4.91  96.0         96.0  96.0      96.0
                       0.9      517.19       578.41   517.66    518.26  5.06         6.32   5.13      5.13  96.0         96.0  96.0      96.0
                 512   0.0      201.27       324.99   200.82    201.42  4.16         4.28   4.24      4.24  96.0         96.0  96.0      96.0
                       0.3      375.96       507.10   376.08    376.68  6.74         6.01   6.57      6.57  96.0         96.0  96.0      96.0
                       0.7      800.30       928.47   800.80    801.40  6.80         6.73   6.60      6.60  96.0         96.0  96.0      96.0
                       0.9     1002.47      1130.40  1002.86   1003.46  5.33         7.05   5.29      5.29  96.0         96.0  96.0      96.0
         128     16    0.0       51.26        51.76    51.45     52.05  3.66         3.66   3.66      3.66  96.0         96.0  96.0      96.0
                       0.3       53.94        54.60    53.98     54.58  3.73         3.65   3.64      3.64  96.0         96.0  96.0      96.0
                       0.7       73.78        74.74    73.97     74.57  4.26         4.26   4.00      4.00  96.0         96.0  96.0      96.0
                       0.9       88.82        89.73    88.87     89.47  4.46         4.55   4.24      4.24  96.0         96.0  96.0      96.0
                 64    0.0       67.87        77.84    67.90     68.50  3.55         3.49   3.49      3.49  96.0         96.0  96.0      96.0
                       0.3       89.24       102.00    89.57     90.17  3.93         4.31   4.04      4.04  96.0         96.0  96.0      96.0
                       0.7      192.98       204.95   193.39    193.99  5.22         5.39   5.21      5.21  96.0         96.0  96.0      96.0
                       0.9      254.72       267.06   255.31    255.91  5.27         5.02   5.29      5.29  96.0         96.0  96.0      96.0
                 128   0.0       88.45       113.06    88.36     88.96  3.87         3.38   3.77      3.77  96.0         96.0  96.0      96.0
                       0.3      142.39       171.32   142.76    143.36  4.82         4.58   5.16      5.16  96.0         96.0  96.0      96.0
                       0.7      352.32       379.50   353.13    353.73  5.44         5.40   5.33      5.33  96.0         96.0  96.0      96.0
                       0.9      475.87       504.11   476.57    477.17  5.32         5.45   5.10      5.10  96.0         96.0  96.0      96.0
                 256   0.0      128.45       185.57   127.96    128.56  3.83         3.41   3.73      3.73  96.0         96.0  96.0      96.0
                       0.3      251.03       313.14   251.45    252.05  6.76         5.16   6.77      6.77  96.0         96.0  96.0      96.0
                       0.7      669.33       729.72   669.91    670.51  6.64         7.18   6.91      6.91  96.0         96.0  96.0      96.0
                       0.9      916.40       978.94   916.78    917.38  5.75         6.26   6.05      6.05  96.0         96.0  96.0      96.0
                 512   0.0      206.64       331.62   205.74    206.34  3.51         4.16   3.86      3.86  96.0         96.0  96.0      96.0
                       0.3      466.98       597.73   467.38    467.98  7.77         6.47   7.65      7.65  96.0         96.0  96.0      96.0
                       0.7     1303.26      1429.08  1303.51   1304.11  9.93         7.58   9.80      9.80  96.0         96.0  96.0      96.0
                       0.9     1799.79      1928.84  1800.24   1800.84  7.68         8.07   7.71      7.71  96.0         96.0  96.0      96.0
4        128     16    0.0         NaN        51.83    51.89     52.69   NaN         3.68   3.64      3.64   NaN         96.0  96.0      96.0
                       0.3         NaN        54.52    54.41     55.21   NaN         3.66   3.66      3.66   NaN         96.0  96.0      96.0
                       0.7         NaN        75.88    74.73     75.53   NaN         4.41   4.06      4.06   NaN         96.0  96.0      96.0
                       0.9         NaN        91.56    90.06     90.86   NaN         4.61   4.31      4.31   NaN         96.0  96.0      96.0
                 64    0.0         NaN        78.28    68.86     69.66   NaN         3.43   3.61      3.61   NaN         96.0  96.0      96.0
                       0.3         NaN       103.54    90.59     91.39   NaN         4.40   4.32      4.32   NaN         96.0  96.0      96.0
                       0.7         NaN       211.71   197.72    198.52   NaN         5.62   5.46      5.46   NaN         96.0  96.0      96.0
                       0.9         NaN       276.68   262.80    263.60   NaN         5.12   6.03      6.03   NaN         96.0  96.0      96.0
                 128   0.0         NaN       115.04    90.29     91.09   NaN         3.40   3.66      3.66   NaN         96.0  96.0      96.0
                       0.3         NaN       175.64   145.35    146.15   NaN         4.92   5.41      5.41   NaN         96.0  96.0      96.0
                       0.7         NaN       393.84   363.04    363.84   NaN         5.49   7.46      7.46   NaN         96.0  96.0      96.0
                       0.9         NaN       524.72   494.95    495.75   NaN         5.53   7.74      7.74   NaN         96.0  96.0      96.0
                 256   0.0         NaN       189.85   132.69    133.49   NaN         3.60   3.90      3.90   NaN         96.0  96.0      96.0
                       0.3         NaN       322.72   256.68    257.48   NaN         5.81   7.65      7.65   NaN         96.0  96.0      96.0
                       0.7         NaN       759.53   696.39    697.19   NaN         7.46  11.18     11.18   NaN         96.0  96.0      96.0
                       0.9         NaN      1022.80   961.63    962.43   NaN         8.16   9.10      9.10   NaN         96.0  96.0      96.0
                 512   0.0         NaN       342.46   218.07    218.87   NaN         4.23   3.95      3.95   NaN         96.0  96.0      96.0
                       0.3         NaN       620.32   480.78    481.58   NaN         6.99  10.52     10.52   NaN         96.0  96.0      96.0
                       0.7         NaN      1496.12  1364.48   1365.28   NaN        10.97  15.09     15.09   NaN         96.0  96.0      96.0
                       0.9         NaN      2022.25  1893.96   1894.76   NaN        12.24  13.33     13.33   NaN         96.0  96.0      96.0
         256     16    0.0         NaN        55.08    55.08     55.88   NaN         3.64   3.56      3.56   NaN         96.0  96.0      96.0
                       0.3         NaN        59.50    59.15     59.95   NaN         3.84   3.95      3.95   NaN         96.0  96.0      96.0
                       0.7         NaN       104.41   103.30    104.10   NaN         5.33   5.27      5.27   NaN         96.0  96.0      96.0
                       0.9         NaN       141.10   140.67    141.47   NaN         5.35   5.27      5.27   NaN         96.0  96.0      96.0
                 64    0.0         NaN        82.38    72.77     73.57   NaN         3.73   3.50      3.50   NaN         96.0  96.0      96.0
                       0.3         NaN       119.70   106.72    107.52   NaN         4.90   5.24      5.24   NaN         96.0  96.0      96.0
                       0.7         NaN       319.99   313.22    314.02   NaN         5.65   8.86      8.86   NaN         96.0  96.0      96.0
                       0.9         NaN       467.70   467.42    468.22   NaN         6.01   8.54      8.54   NaN         96.0  96.0      96.0
                 128   0.0         NaN       119.69    94.75     95.55   NaN         3.77   3.40      3.40   NaN         96.0  96.0      96.0
                       0.3         NaN       205.85   177.51    178.31   NaN         6.01   7.39      7.39   NaN         96.0  96.0      96.0
                       0.7         NaN       607.74   594.46    595.26   NaN         6.58  11.60     11.60   NaN         96.0  96.0      96.0
                       0.9         NaN       903.72   902.09    902.89   NaN         6.49  10.57     10.57   NaN         96.0  96.0      96.0
                 256   0.0         NaN       195.30   136.31    137.11   NaN         4.27   3.16      3.16   NaN         96.0  96.0      96.0
                       0.3         NaN       380.62   320.94    321.74   NaN         7.69   9.89      9.89   NaN         96.0  96.0      96.0
                       0.7         NaN      1184.78  1158.06   1158.86   NaN         8.93  14.85     14.85   NaN         96.0  96.0      96.0
                       0.9         NaN      1774.80  1773.26   1774.06   NaN         9.65  14.45     14.45   NaN         96.0  96.0      96.0
                 512   0.0         NaN       348.84   220.26    221.06   NaN         4.22   3.73      3.73   NaN         96.0  96.0      96.0
                       0.3         NaN       733.33   607.80    608.60   NaN         8.86  13.08     13.08   NaN         96.0  96.0      96.0
                       0.7         NaN      2339.69  2282.32   2283.12   NaN        14.22  22.24     22.24   NaN         96.0  96.0      96.0
                       0.9         NaN      3522.74  3515.67   3516.47   NaN        13.37  18.33     18.33   NaN         96.0  96.0      96.0
         512     16    0.0         NaN        58.45    58.82     59.62   NaN         3.35   3.14      3.14   NaN         96.0  96.0      96.0
                       0.3         NaN        64.44    64.29     65.09   NaN         4.10   3.64      3.64   NaN         96.0  96.0      96.0
                       0.7         NaN       150.14   150.62    151.42   NaN         5.63   6.83      6.83   NaN         96.0  96.0      96.0
                       0.9         NaN       229.26   233.85    234.65   NaN         5.84   6.83      6.83   NaN         96.0  96.0      96.0
                 64    0.0         NaN        85.43    77.38     78.18   NaN         3.69   3.23      3.23   NaN         96.0  96.0      96.0
                       0.3         NaN       137.97   125.26    126.06   NaN         5.71   6.52      6.52   NaN         96.0  96.0      96.0
                       0.7         NaN       493.95   500.14    500.94   NaN         7.19  11.32     11.32   NaN         96.0  96.0      96.0
                       0.9         NaN       811.65   835.82    836.62   NaN         7.30  10.80     10.80   NaN         96.0  96.0      96.0
                 128   0.0         NaN       123.42   100.38    101.18   NaN         3.96   3.13      3.13   NaN         96.0  96.0      96.0
                       0.3         NaN       242.33   216.08    216.88   NaN         6.87   8.50      8.50   NaN         96.0  96.0      96.0
                       0.7         NaN       954.49   968.21    969.01   NaN         8.76  13.86     13.86   NaN         96.0  96.0      96.0
                       0.9         NaN      1588.36  1638.01   1638.81   NaN         8.35  14.60     14.60   NaN         96.0  96.0      96.0
                 256   0.0         NaN       200.36   144.37    145.17   NaN         4.09   3.23      3.23   NaN         96.0  96.0      96.0
                       0.3         NaN       451.43   395.45    396.25   NaN         8.23  11.58     11.58   NaN         96.0  96.0      96.0
                       0.7         NaN      1873.71  1900.14   1900.94   NaN        10.92  20.47     20.47   NaN         96.0  96.0      96.0
                       0.9         NaN      3142.09  3240.05   3240.85   NaN        11.70  20.35     20.35   NaN         96.0  96.0      96.0
                 512   0.0         NaN       353.80   229.54    230.34   NaN         4.45   3.44      3.44   NaN         96.0  96.0      96.0
                       0.3         NaN       868.98   758.53    759.33   NaN         7.94  16.29     16.29   NaN         96.0  96.0      96.0
                       0.7         NaN      3712.24  3766.84   3767.64   NaN        14.20  30.88     30.88   NaN         96.0  96.0      96.0
                       0.9         NaN      6249.05  6450.03   6450.83   NaN        16.04  26.29     26.29   NaN         96.0  96.0      96.0
```
### 5.1 场景1 PDF
![exp3_pdf_s1_b128_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b128_s0.3.png)
![exp3_pdf_s1_b128_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b128_s0.7.png)
![exp3_pdf_s1_b128_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b128_s0.9.png)
![exp3_pdf_s1_b128_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b128_s0.png)
![exp3_pdf_s1_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.3.png)
![exp3_pdf_s1_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.7.png)
![exp3_pdf_s1_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.9.png)
![exp3_pdf_s1_b16_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b16_s0.png)
![exp3_pdf_s1_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.3.png)
![exp3_pdf_s1_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.7.png)
![exp3_pdf_s1_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.9.png)
![exp3_pdf_s1_b256_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b256_s0.png)
![exp3_pdf_s1_b512_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b512_s0.3.png)
![exp3_pdf_s1_b512_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b512_s0.7.png)
![exp3_pdf_s1_b512_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b512_s0.9.png)
![exp3_pdf_s1_b512_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b512_s0.png)
![exp3_pdf_s1_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.3.png)
![exp3_pdf_s1_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.7.png)
![exp3_pdf_s1_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.9.png)
![exp3_pdf_s1_b64_s0.png](../results/ub_rg/figures/exp3_pdf_s1_b64_s0.png)
### 5.4 场景4 PDF
![exp3_pdf_s4_b128_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b128_s0.3.png)
![exp3_pdf_s4_b128_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b128_s0.7.png)
![exp3_pdf_s4_b128_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b128_s0.9.png)
![exp3_pdf_s4_b128_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b128_s0.png)
![exp3_pdf_s4_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.3.png)
![exp3_pdf_s4_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.7.png)
![exp3_pdf_s4_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.9.png)
![exp3_pdf_s4_b16_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b16_s0.png)
![exp3_pdf_s4_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.3.png)
![exp3_pdf_s4_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.7.png)
![exp3_pdf_s4_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.9.png)
![exp3_pdf_s4_b256_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b256_s0.png)
![exp3_pdf_s4_b512_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b512_s0.3.png)
![exp3_pdf_s4_b512_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b512_s0.7.png)
![exp3_pdf_s4_b512_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b512_s0.9.png)
![exp3_pdf_s4_b512_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b512_s0.png)
![exp3_pdf_s4_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.3.png)
![exp3_pdf_s4_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.7.png)
![exp3_pdf_s4_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.9.png)
![exp3_pdf_s4_b64_s0.png](../results/ub_rg/figures/exp3_pdf_s4_b64_s0.png)
### 5.4 跨场景对比 PDF（S1-EP128 / S4-EP512）
![exp3_pdf_compare_b128_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b128_s0.3.png)
![exp3_pdf_compare_b128_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b128_s0.7.png)
![exp3_pdf_compare_b128_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b128_s0.9.png)
![exp3_pdf_compare_b128_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b128_s0.png)
![exp3_pdf_compare_b16_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.3.png)
![exp3_pdf_compare_b16_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.7.png)
![exp3_pdf_compare_b16_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.9.png)
![exp3_pdf_compare_b16_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b16_s0.png)
![exp3_pdf_compare_b256_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.3.png)
![exp3_pdf_compare_b256_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.7.png)
![exp3_pdf_compare_b256_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.9.png)
![exp3_pdf_compare_b256_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b256_s0.png)
![exp3_pdf_compare_b512_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b512_s0.3.png)
![exp3_pdf_compare_b512_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b512_s0.7.png)
![exp3_pdf_compare_b512_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b512_s0.9.png)
![exp3_pdf_compare_b512_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b512_s0.png)
![exp3_pdf_compare_b64_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.3.png)
![exp3_pdf_compare_b64_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.7.png)
![exp3_pdf_compare_b64_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.9.png)
![exp3_pdf_compare_b64_s0.png](../results/ub_rg/figures/exp3_pdf_compare_b64_s0.png)
### 5.x Roundtrip Step vs EP（汇总）
![exp3_s1_step_vs_ep.png](../results/ub_rg/figures/exp3_s1_step_vs_ep.png)
![exp3_s4_step_vs_ep.png](../results/ub_rg/figures/exp3_s4_step_vs_ep.png)
## 6. 方案对比摘要
- **场景1** 平均 step（三方案共有参数格）：UB_RG=142.3µs vs POP=142.6µs（POP/RG=1.00×） vs Spray=160.5µs（Spray/RG=1.13×）
- **场景1** ub_rg CCT/König：mean=2.125，median=1.274
- **场景1** ub_rg_pop CCT/König：mean=2.142，median=1.282
- **场景1** packet_spray CCT/König：mean=2.282，median=1.492
- **场景1** islip CCT/König：mean=2.126，median=1.242
- **场景4** 平均 step（三方案共有参数格）：UB_RG=394.1µs vs POP=394.5µs（POP/RG=1.00×） vs Spray=377.1µs（Spray/RG=0.96×）
- **场景4** ub_rg CCT/König：mean=2.010，median=1.183
- **场景4** ub_rg_pop CCT/König：mean=2.027，median=1.190
- **场景4** packet_spray CCT/König：mean=2.070，median=1.195
## 7. 双引擎对比（逐包 vs 行为级）
在相同 (scenario, scheme, mode, batch, zipf_s, ep_size) 键上对齐 step_us / lat_p99。
对齐样本 **96** 组；step 比值（packet/behavioral）均值=568.468，中位数=20.563。
```
          exp  scenario       scheme     mode  batch  zipf_s  ep_size  step_packet  p99_packet  step_behav  p99_behav  step_ratio
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      11.855      7.131       5.324
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      20.058     14.955       3.147
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      28.936     25.646       2.181
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.116      49.651      51.752     48.319       1.220
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      24.901     19.030       8.110
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      31.957     26.270       6.320
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      40.384     34.656       5.001
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      201.956     150.648      58.591     51.716       3.447
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      32.786     26.342       8.827
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      39.985     33.564       7.238
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      48.188     41.789       6.006
exp1_dispatch         1 packet_spray dispatch     16     0.9      128      289.405     212.317      66.045     58.866       4.382
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766       8.414      5.268       3.670
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766      17.385     14.095       1.776
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766      28.793     25.503       1.072
exp1_dispatch         1 packet_spray dispatch     16     0.0      128       30.879      26.766      51.609     48.319       0.598
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884       9.911      6.390     101.454
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      18.590     14.020      54.087
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      28.999     23.618      34.673
exp1_dispatch         1        ub_rg dispatch     16     0.3      128     1005.475       5.884      51.815     42.060      19.405
```
若该比值显著偏离 1，不能仅解释为“逐包栈静态开销”。当前逐包实现还含50µs REQ pacing、10ms stale-credit 回收，且两引擎的本地专家和场景2/3plane 映射不一致；在统一输入、完成守恒和异常门禁通过前，这里是**交叉验证失败证据**，不是行为级绝对值校准。
- **packet** 同参数格平均：POP/RG=5.741×，Spray/RG=0.362×
- **behavioral** 同参数格平均：POP/RG=1.004×，Spray/RG=1.108×
## 8. 复现方法
当前报告主体由行为级引擎生成。复现默认矩阵与 Exp3 PDF：
```bash
cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus --disable-python -d optimized
./ns3 build ub_rg-dispatch-experiment
cd ..
python3 run_ub_rg_experiments.py --engine behavioral
python3 run_ub_rg_experiments.py --engine behavioral --exp3-pdf --seeds 96 --batches 16,64,128,256,512
python3 analyze_ub_rg_experiments.py --engine behavioral
```
## 附录 A. 通信微架构与证据索引

下图概括本仿真**已建模的通信微架构**与**未建模的计算微架构**。随后表格给出上图各模块对应的关键代码位置。

![UB_RG 通信微架构](./ub_rg_figures/ub_rg_microarchitecture.png)

### A.1 微架构关键代码证据索引

下表把上图中的模块直接映射到仓库文件位置；阅读结果前应先能定位这些实现。

| 微架构模块 | 证据 | 文件与位置 |
|---|---|---|
| 行为级常量 / grain / 端口速率 | τ_g、50 GB/s、hop 时延 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:29-36` |
| Zipf / TopK → grain | 负载与专家路由 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:260-351` |
| Spray / RG / POP phase | 三方案排队与授权 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:438-738` |
| S4 / iSLIP / 启动偏差 / GEMV | PathClass、iSLIP matching、start-skew、ComputeGemvUs | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc` |
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

