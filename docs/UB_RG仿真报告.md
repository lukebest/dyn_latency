# UB_RG 网络仿真报告
> **可信性状态：实现证据存在，性能结论未验证。** 行为级结果仅作为网络机制假设；方案间路由、path delay、jitter 与 barrier 混杂尚未消除，逐包性能矩阵也未通过完成守恒与跨引擎校验。绝对硬件时延与完整POP硅片实现不得据此下结论；Exp3 GEMV 为标定服务模型。详见[UB_RG仿真可信性评估报告](./UB_RG仿真可信性评估报告.html)。
## 1. 主要实验结论
> 结论适用于场景1/4；Exp1/2 为网络子系统；Exp3 含 Zipf×batch GEMV straggler；启动偏差为 N(0,σ²)，σ∈{0,2,4,8} µs。
- **配置包输出差异**（Exp1，按 batch 分列，不跨 batch 平均 step）：batch=16：POP/RG=**1.010×**，Spray/RG=**1.006×**；batch=256：POP/RG=**0.991×**，Spray/RG=**1.587×**，POP2/RG 平均为 **0.990×**。这是当前配置包的联合差异；plane、path delay、jitter 和 barrier 尚未统一，不能把比值单独归因于目的侧配速（见 §1.1）。
- **POP 启动开销会被负载摊薄**：batch=16 时 POP/RG=**1.010×**，batch=256 时为 **0.991×**；结果符合“多一次 one-way 启动、稳态节拍与 RG 相同”的模型预期。
- **瓶颈下界**：CCT/König 中位数为 ub_rg=2.580、ub_rg_pop=2.617、ub_rg_pop2=2.633、packet_spray=8.800；它证明输出符合当前方程，但不是排除混杂后的硬件性能验证。
- **拓扑范围**：主矩阵为场景1（Clos+iSLIP）与场景4（Sparse CLOS 512P）。
- **Exp3**：端到端含 GEMV；`gemv_us` 随 Zipf 热点与 batch 变化。
- 当前 UB_RG 配置包的 CCT 更接近自定义 König 下界；与 Spray 的比值是**配置包联合差异**，不是“仅改目的侧准入”的受控因果结论（原因见 §1.1）。
- UB_RG_POP（近似模型）与 RG 共享目的侧节奏/König 渐近；多付一次 one-way 启动，小 batch 略慢、大负载接近 RG。
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
本报告对应 [UB_RG实验设计.md](./UB_RG实验设计.md) §4.2.1–§4.2.3，在 `ns-3-ub` **Unified Bus 协议栈**上用逐包仿真器 `scratch/ub_rg-packet-experiment.cc` 对比 **UB_RG**、**UB_RG_POP（SHMEM-POP）** 与 **Packet Spray（自由注入）**。结构对齐参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html)：组网 → 方案差异 → 扫参结果。
### 2.1 仿真环境、微架构抽象与 CCT 口径

| 项目 | 配置 / 抽象 |
|---|---|
| 执行主机 | Linux 6.17.0-40-generic（x86_64） |
| 工具链 | Python 3.12.3；g++ 13.3.0；CMake 3.28.3；ns-3.44 optimized build |
| 当前报告引擎 | `packet`；ns-3.44 逐包离散事件模型：Unified Bus 的 TP/Jetty、端口、交换机转发以及 REQ/GNT/SYNC 控制报文均进入事件队列。 |
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

对齐 [UB_RG实验设计.md](./UB_RG实验设计.md) 与 [场景4_Sparse_CLOS_512P_设计说明.md](./场景4_Sparse_CLOS_512P_设计说明.md)；本报告由 逐包引擎（`ub_rg-packet-experiment` + `UbRgExperimentApp`） 驱动。

> 逐包场景4拓扑若未就绪，则逐包仅用于场景1 协议调试。

| 场景 | 拓扑 | NPU | 交换 | 备注 |
|---|---|---:|---|---|
| 1 | 单层 Clos | 128 | 8 × SW128 | 8×400G；2 跳；另含 iSLIP 调度对照 |
| 4 | Sparse CLOS | 512 | 32 × SW128 | 8 Cluster×64 Server；15×400G（7 PFM+8 上联）；唯一路径 |

组网差异要点：

- **跳数 / RTT**：场景1 RTT_rg≈0.6µs；场景4 典型 SW≈0.8µs，同机 PFM 更短。
- **瓶颈**：场景1 目的侧平面下行；场景4 跨 Cluster SW 下行与 PFM 争用。
- **调度**：场景1 含 `islip`；场景4 为 `ub_rg` / `ub_rg_pop` / `ub_rg_pop2` / `packet_spray`。

### 2.3 网络方案与实现差异

| 方案 | Scheme | 语义 |
|---|---|---|
| §2.1 | `packet_spray` | 自由注入 / Packet Spray 基线（参考报告中的 `ub_unscheduled`） |
| §2.2 | `ub_rg` | 标准 Request-Grant：目的侧按 1 grain/τ_g 授权 |
| §2.3 | `ub_rg_pop` | SHMEM-POP：Push 元数据 → ESC → PullGrant → 远端读 Pull |
| POP2 | `ub_rg_pop2` | ub_rg + 源侧每 Plane 万能 GNT 预授权（见 [UB_RG_POP2方案设计.md](./UB_RG_POP2方案设计.md)） |

主 KPI：CCT / step（µs）；辅 KPI：hot/cold p99、吞吐、CCT/König。机制对照如下（以本仓库仿真为准，POP 为近似模型，非完整 supernode `UbRgPopEsc` 模块）。

#### 角色关系

| 对象 | 形态 | 角色 |
|---|---|---|
| `ub_request_grant.md` / 设计 | 文档 | 交换机侧分布式 REQ/GNT：每 τ_g 每出口 ≤1、路径钉扎、cursor/SYNC |
| `ub_rg` | 仿真 scheme | 主协议的落地：目的侧授权节奏 + 源侧 FCFS；行为级折叠控制面为 RTT；逐包走真实 REQ/GNT/SYNC |
| `ub_rg_pop` | 仿真 scheme | [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md) 的假设模型：行为级为 RG + startup + PullCredit；逐包为 RG 路径 + completion 计时 overlay |
| `ub_rg_pop2` | 仿真 scheme | [UB_RG_POP2方案设计.md](./UB_RG_POP2方案设计.md)：同 ub_rg 目的侧；源侧每 Plane 万能 GNT 池（与同引擎其它 scheme 比对） |
| `packet_spray` | 仿真 scheme | 无授权准入；源上联自由注入；目的/中段 FIFO；分析阶段叠软件屏障 |
| `islip` | 仿真 scheme | 与 `ub_rg` 相同：路径钉扎 + REQ/GNT + RTT/barrier；仅将每出口独立 RR 换成每 τ_g 的 iSLIP matching（对齐 `ub_request_grant.md` §2.7） |

> **对齐的核心（设计 ↔ ub_rg）：** grain 量化、τ_g、每平面 ≤1 授权、Clos/MpClos 钉扎。
> **POP 相对 RG：** 稳态 König 渐近相同；startup = RTT_rg + oneWay（≈1.5×）；小 batch 略慢，大负载/高偏斜时 pop≈rg。
> **POP2 相对 RG：** 同目的侧节拍与 RTT_rg；前 N≈⌈RTT_rg/τ_g⌉ grain 可零等待投机注入；调度器可按出口 DATA 深度空拍排空。
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

CLI：`--scheme=ub_rg|ub_rg_pop|ub_rg_pop2|packet_spray|islip`；`--start-skew-us=0|2|4|8`（Normal σ）。
### 2.4 模型假设与简化
- 端口 400Gbps，grain = 7KB（2×MTU），τ_g ≈ 143.36 ns
- 交换机缓冲：每入口 (port, VL) **256KB @ 400Gbps**；exclusive CBFC 初始信用 ⌊256KB/160B⌋=1638 cell；SharedPool=0
- 真实 REQ/GNT/SYNC 控制报文（VL1）；末跳交换机拦截 REQ；目的侧 1 grain/τ_g + credit window + RR；源侧 FCFS grant 队列
- UB_RG_POP：复用 RG 路径和相同 credit，只在 completion 统计上追加单向 startup；未实现独立 Push/Pull 数据通路（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）
- UB_RG_POP2：源侧万能 GNT 池 + 投机 DATA；调度器 `m_earlyData` 匹配早到 DATA；与同引擎其它 scheme 比对（不与行为级混比）
- SYNC：各调度器 LOCAL → 聚合 NPU(member0) → GLOBAL 广播（与文档 §4.9 聚合点差异见正文）
- transport retrans 已启用；省略：完整 POP 状态机、预补偿、多世代窗口、PHASE 管理面
- Packet Spray：`UsePacketSpray` + 自由注入；软件屏障在分析阶段叠加
- 专家与 NPU 1:1；TopK=8
### 2.5 参数矩阵（裁剪）
| 实验 | mode | 场景 | Batch | Zipf S | EP | 启动偏差 | 调度 |
|---|---|---|---|---|---|---|---|
| 1 Dispatch | dispatch | 1,4 | 16,256 | 0,0.3,0.7,0.9 | full | σ=0/2/4/8 µs | S1:+islip |
| 2 Combine | combine | 同实验1 | 同左 | 同左 | full | 同左 | 同左 |
| 3 Roundtrip+GEMV | roundtrip | 1→{32,64,128}; 4→{128,256,512} | 256（S1 iSLIP 另含 128/512） | 同左 | 上列 | 同左 | 同左 |
| 3 PDF | roundtrip | 同上 | 16,64,128,256,512 | 同左 | 每格 96 seeds | σ=4µs | 同左 |

引擎：**packet**；成功汇总运行数：**610**。原始结果：`results/ub_rg_packet/`。
> 上表对齐当前 runner：仅场景1+4；启动偏差为 N(0,σ²)（σ∈{0,2,4,8}）；场景1 含 iSLIP；Exp3 输出 gemv_us/e2e_us。旧场景2/3 结果请忽略。
> 逐包引擎按风险路径裁剪且当前完整度不足；行为级引擎覆盖完整主矩阵与 PDF。本报告方案对比仅使用本引擎结果，不与行为级混比。实验3 系统 CCT PDF 若本引擎样本未齐，报告自动回退到行为级多 seed 结果。
## 3. 实验1：倾斜专家流量下的 Dispatch
> 下表按 **batch 分列**；不同 batch 的 `step_us` 不放在同一张表。
> **读图（Exp1/2 汇总图均为分组柱状，不再用多线折线）**
> - **颜色 = 方案**；数值对 seed / 启动偏差 σ 取均值。
> - `throughput_vs_s`：每栏一个 batch，横轴 Zipf S → 聚合吞吐；偏斜升高时常下降。
> - `hotcold_p99_vs_s`：左 hot（Zipf 最热 10% token p99）/ 右 cold（最冷 50%）；S↑ 时 hot 应升、cold 应大致持平；cold 也被抬高 ⇒ 拥塞外溢。
> - `step_vs_batch`：左 `step_us`（含屏障）/ 右 `cct_us`（纯数据面）；固定某一 Zipf S，横轴 batch（log y）。
> - `bar_step_vs_zipf_*`：按 (batch, σ) 拆开的 step 柱图，与逐 token hot/cold 不是同一指标。
### 3.1 场景1
**batch=16 对比表**

```
             cct_us                                  hot_p99                                  lat_p99                                  step_us                             throughput_GBs
scheme packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2   packet_spray    ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           25.03  25.89     26.19      25.26         6.41   4.86      5.16       5.06         6.34   4.83      5.13       4.96        27.03  26.29     26.59      25.66        7091.64  6386.99   6255.08    6781.90
0.3           26.67  28.85     29.15      28.38         9.51   8.13      8.43       7.96         8.08   6.24      6.54       6.17        28.67  29.25     29.55      28.78        5574.26  4848.30   4781.47    4937.89
0.7           40.72  46.13     46.43      45.78        30.14  24.37     24.67      23.87        27.03  21.92     22.22      21.23        42.72  46.53     46.83      46.18        2928.76  2568.48   2551.60    2587.36
0.9           51.92  59.80     60.10      59.47        42.37  32.81     33.11      32.01        40.19  30.95     31.25      30.23        53.92  60.20     60.50      59.87        2270.26  1969.23   1959.35    1980.35
```
**batch=256 对比表**

```
             cct_us                                   hot_p99                                   lat_p99                                   step_us                              throughput_GBs
scheme packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2   packet_spray     ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0          119.82  162.97    163.27     162.52       102.73   67.14     67.44      68.40        92.72   56.69     56.99      55.97       121.82  163.37    163.67     162.92       15825.54  11552.86  11531.55   11649.34
0.3          244.88  250.14    250.44     249.40       218.58  125.03    125.33     125.05        96.12   64.62     64.92      63.78       246.88  250.54    250.84     249.80        7676.85   7512.39   7503.39    7534.45
0.7         1487.17  658.89    659.19     657.25       217.81  201.68    201.98     200.97       144.35  115.72    116.02     114.38      1489.17  659.29    659.59     657.65        1291.17   2851.92   2850.62    2858.97
0.9         2785.49  948.63    948.93     934.67       229.72  223.66    223.96     222.93       255.99  217.89    218.19     218.20      2787.49  949.03    949.33     935.07         694.04   1981.96   1981.33    2011.89
```
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk0.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b16_nsk8.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk0.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk2.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk4.png)
![exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_bar_step_vs_zipf_b256_nsk8.png)
![exp1_dispatch_s1_hotcold_p99_vs_s.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_hotcold_p99_vs_s.png)
![exp1_dispatch_s1_step_vs_batch.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_step_vs_batch.png)
![exp1_dispatch_s1_throughput_vs_s.png](../results/ub_rg_packet/figures/exp1_dispatch_s1_throughput_vs_s.png)
### 3.4 场景4
**batch=16 对比表**

```
             cct_us                                   hot_p99                                   lat_p99                                  step_us                              throughput_GBs
scheme packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2   packet_spray     ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           28.37   29.07     29.62      28.33         5.29    4.20      4.75       3.95         6.17   5.31      5.86       5.14        32.37   30.27     30.82      29.53       26785.57  24580.38  23642.10   26837.50
0.3           33.40   33.86     34.41      33.24        13.43    8.57      9.12       8.22         9.28   6.66      7.21       6.43        37.40   35.06     35.61      34.44       16518.48  16196.94  15861.95   16640.92
0.7           98.24   96.21     96.76      95.84        82.38   55.51     56.06      55.24        77.97  47.86     48.41      47.62       102.24   97.41     97.96      97.04        4801.63   4896.67   4868.68    4917.31
0.9          161.05  157.82    158.37     157.38       144.46  101.26    101.81     100.47       141.07  94.14     94.69      93.59       165.05  159.02    159.57     158.58        2921.05   2979.21   2968.85    2987.72
```
**batch=256 对比表**

```
             cct_us                         hot_p99                       lat_p99                       step_us                    throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop packet_spray  ub_rg ub_rg_pop packet_spray  ub_rg ub_rg_pop packet_spray    ub_rg ub_rg_pop   packet_spray     ub_rg ub_rg_pop
zipf_s
0.0          209.45   210.58    200.48       124.12  99.38    104.24       111.33  77.83     84.11       213.45   211.78    201.68       35908.57  35784.57  37491.73
0.9        14015.00  8325.16       NaN       101.53  66.47       NaN        45.97  31.41       NaN     14019.00  8326.36       NaN         536.42    909.28       NaN
```
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk0.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b16_nsk8.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk0.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk2.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk4.png)
![exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_bar_step_vs_zipf_b256_nsk8.png)
![exp1_dispatch_s4_hotcold_p99_vs_s.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_hotcold_p99_vs_s.png)
![exp1_dispatch_s4_step_vs_batch.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_step_vs_batch.png)
![exp1_dispatch_s4_throughput_vs_s.png](../results/ub_rg_packet/figures/exp1_dispatch_s4_throughput_vs_s.png)
## 4. 实验2：倾斜专家流量下的 Combine
> 下表按 **batch 分列**；不同 batch 的 `step_us` 不放在同一张表。
> **读图（Exp1/2 汇总图均为分组柱状，不再用多线折线）**
> - **颜色 = 方案**；数值对 seed / 启动偏差 σ 取均值。
> - `throughput_vs_s`：每栏一个 batch，横轴 Zipf S → 聚合吞吐；偏斜升高时常下降。
> - `hotcold_p99_vs_s`：左 hot（Zipf 最热 10% token p99）/ 右 cold（最冷 50%）；S↑ 时 hot 应升、cold 应大致持平；cold 也被抬高 ⇒ 拥塞外溢。
> - `step_vs_batch`：左 `step_us`（含屏障）/ 右 `cct_us`（纯数据面）；固定某一 Zipf S，横轴 batch（log y）。
> - `bar_step_vs_zipf_*`：按 (batch, σ) 拆开的 step 柱图，与逐 token hot/cold 不是同一指标。
### 4.1 场景1
**batch=16 对比表**

```
             cct_us                                  hot_p99                                  lat_p99                                  step_us                             throughput_GBs
scheme packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2   packet_spray    ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           43.21  25.51     25.81      24.99        31.37   4.79      5.09       5.11        31.18   4.82      5.12       5.30        45.21  25.91     26.21      25.39        2948.56  6472.60   6337.93    6733.36
0.3           67.18  28.31     28.61      27.69        58.26  10.85     11.15      11.14        50.61   8.45      8.75       8.46        69.18  28.71     29.01      28.09        1757.36  4831.31   4766.05    4977.16
0.7          180.14  47.88     48.18      52.93       167.86  25.47     25.77      25.56       156.17  22.16     22.46      22.14       182.14  48.28     48.58      53.33         652.29  2471.58   2455.96    2261.33
0.9          245.44  64.55     64.85      64.14       231.54  33.34     33.64      33.45       220.97  30.43     30.73      30.28       247.44  64.95     65.25      64.54         478.64  1843.35   1834.61    1833.43
```
**batch=256 对比表**

```
             cct_us                                    hot_p99                                   lat_p99                                  step_us                               throughput_GBs
scheme packet_spray    ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray    ub_rg ub_rg_pop ub_rg_pop2   packet_spray     ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0          406.04   161.56    161.86     156.17       383.70   63.38     63.68      64.66       348.80  56.78     57.08      57.60       408.04   161.96    162.26     156.57        4630.42  11669.97  11648.19   12090.13
0.3          989.19   358.20    358.50     328.49       926.11  160.81    161.11     165.69       341.92  59.66     59.96      60.62       991.19   358.60    358.90     328.89        1899.59   5250.34   5245.94    5721.41
0.7         2811.21   995.32    995.62    1086.90       709.16  108.85    109.15     109.43       505.77  65.07     65.37      65.79      2813.21   995.72    996.02    1087.30         668.42   1890.90   1890.32    1749.90
0.9         3892.93  1645.33   1645.63    1622.03       705.26   98.73     99.03      99.55       758.26  97.80     98.10     100.29      3894.93  1645.73   1646.03    1622.43         482.68   1147.56   1147.35    1167.23
```
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk0.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b16_nsk8.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk0.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk2.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk4.png)
![exp2_combine_s1_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg_packet/figures/exp2_combine_s1_bar_step_vs_zipf_b256_nsk8.png)
![exp2_combine_s1_hotcold_p99_vs_s.png](../results/ub_rg_packet/figures/exp2_combine_s1_hotcold_p99_vs_s.png)
![exp2_combine_s1_step_vs_batch.png](../results/ub_rg_packet/figures/exp2_combine_s1_step_vs_batch.png)
![exp2_combine_s1_throughput_vs_s.png](../results/ub_rg_packet/figures/exp2_combine_s1_throughput_vs_s.png)
### 4.4 场景4
**batch=16 对比表**

```
             cct_us                                   hot_p99                                  lat_p99                                  step_us                              throughput_GBs
scheme packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2   packet_spray     ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           28.69   29.34     29.89      28.80         6.54   5.57      6.12       5.74         6.36   5.37      5.92       5.57        32.69   30.54     31.09      30.00       26693.00  24798.09  23822.87   25769.90
0.3           35.05   35.97     36.52      35.21        19.25  13.00     13.55      13.70        13.35  10.35     10.90      10.78        39.05   37.17     37.72      36.41       15083.03  14534.65  14271.86   14946.28
0.7           98.95  108.12    108.67     107.50        80.84  44.29     44.84      45.07        69.73  37.61     38.16      38.28       102.95  109.32    109.87     108.70        4768.60   4349.66   4327.60    4376.21
0.9          161.98  191.56    192.11     194.79       137.89  70.51     71.06      70.52       129.35  63.58     64.13      63.18       165.98  192.76    193.31     195.99        2905.21   2454.95   2447.91    2412.59
```
**batch=256 对比表**

```
             cct_us               hot_p99              lat_p99             step_us          throughput_GBs
scheme packet_spray    ub_rg packet_spray   ub_rg packet_spray  ub_rg packet_spray    ub_rg   packet_spray     ub_rg
zipf_s
0.0          208.75   211.59       147.24  121.25       111.87  77.87       212.75   212.79       36057.59  35647.08
0.9        13114.80  6527.96       154.43  111.83       167.43  81.69     13118.80  6529.16         572.76   1178.85
```
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk0.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk0.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk2.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk4.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b16_nsk8.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b16_nsk8.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk0.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk0.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk2.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk2.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk4.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk4.png)
![exp2_combine_s4_bar_step_vs_zipf_b256_nsk8.png](../results/ub_rg_packet/figures/exp2_combine_s4_bar_step_vs_zipf_b256_nsk8.png)
![exp2_combine_s4_hotcold_p99_vs_s.png](../results/ub_rg_packet/figures/exp2_combine_s4_hotcold_p99_vs_s.png)
![exp2_combine_s4_step_vs_batch.png](../results/ub_rg_packet/figures/exp2_combine_s4_step_vs_batch.png)
![exp2_combine_s4_throughput_vs_s.png](../results/ub_rg_packet/figures/exp2_combine_s4_throughput_vs_s.png)
## 5. 实验3：网络系统级 Dispatch+Combine 完成时间 (CCT) PDF
横轴优先为**端到端完成时间**（`e2e_us`/`step_us`：dispatch→GEMV→combine；GEMV 由 Zipf 专家负载与 batch 标定）。网络-only `cct_us` 仍写入 summary 供对照。对每个 (场景, BatchSize, Zipf S, EP) 组合，在多个随机种子下各跑一次 roundtrip，每次运行贡献一个系统 CCT 样本，以此得到系统 CCT 的概率密度分布（PDF，无 CDF）。
覆盖三个组网场景（与实验设计 §4.2.3 一致）：
- **场景1** 单层 Clos：EP ∈ {32, 64, 128}；PDF batch∈{16,64,128,256,512}（含 iSLIP）
- **场景4** Sparse CLOS：EP ∈ {128, 256, 512}；PDF batch∈{16,64,128,256,512}
每场景单独出 PDF（每个 (EP, Zipf S) 一张）；另附跨场景对比图（S1-EP128 / S4-EP512）。**颜色区分方案**（ub_rg / ub_rg_pop / ub_rg_pop2 / packet_spray / islip），**线型区分 batch**（16 实线、64 虚线、128 点划、256 密虚线、512 点线）。
（当前引擎尚无 exp3_pdf；下图暂用 **behavioral** 引擎样本）
**系统 CCT 样本统计（µs，mean/std/count）**——按 batch 分表，不把不同 batch 混在一张表里。
**batch=16**

```
                          mean                                             std                                         count
scheme                   islip packet_spray   ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0     39.80        41.61   39.78     39.78      39.79  4.37         4.25  4.37      4.37       4.37  96.0         96.0  96.0      96.0       96.0
                 0.3     40.39        42.37   40.40     40.40      40.40  4.42         4.15  4.41      4.41       4.42  96.0         96.0  96.0      96.0       96.0
                 0.7     42.71        45.40   42.71     42.71      42.72  4.33         4.21  4.33      4.33       4.33  96.0         96.0  96.0      96.0       96.0
                 0.9     43.91        46.72   43.91     43.91      43.91  4.37         4.33  4.37      4.37       4.36  96.0         96.0  96.0      96.0       96.0
         64      0.0     45.46        47.60   45.46     45.46      45.43  3.99         3.88  3.98      3.98       3.97  96.0         96.0  96.0      96.0       96.0
                 0.3     46.54        49.26   46.52     46.52      46.54  3.90         3.75  3.90      3.90       3.90  96.0         96.0  96.0      96.0       96.0
                 0.7     51.22        57.51   51.22     51.22      51.22  4.21         4.16  4.20      4.20       4.19  96.0         96.0  96.0      96.0       96.0
                 0.9     54.85        62.67   54.85     54.85      54.85  4.49         4.24  4.48      4.48       4.48  96.0         96.0  96.0      96.0       96.0
         128     0.0     49.44        51.76   49.44     49.44      49.44  3.63         3.66  3.61      3.61       3.63  96.0         96.0  96.0      96.0       96.0
                 0.3     50.79        54.60   50.78     50.78      50.78  3.62         3.65  3.62      3.62       3.62  96.0         96.0  96.0      96.0       96.0
                 0.7     61.98        74.74   61.97     61.97      61.96  4.22         4.26  4.19      4.19       4.20  96.0         96.0  96.0      96.0       96.0
                 0.9     71.46        89.73   71.44     71.56      71.45  4.26         4.55  4.23      4.21       4.27  96.0         96.0  96.0      96.0       96.0
4        128     0.0       NaN        51.83   49.46     49.46      49.49   NaN         3.68  3.63      3.63       3.61   NaN         96.0  96.0      96.0       96.0
                 0.3       NaN        54.52   50.77     50.77      50.76   NaN         3.66  3.62      3.62       3.64   NaN         96.0  96.0      96.0       96.0
                 0.7       NaN        75.88   62.08     62.08      62.05   NaN         4.41  4.13      4.13       4.14   NaN         96.0  96.0      96.0       96.0
                 0.9       NaN        91.56   72.17     72.37      72.16   NaN         4.61  4.20      4.18       4.23   NaN         96.0  96.0      96.0       96.0
         256     0.0       NaN        55.08   52.55     52.55      52.55   NaN         3.64  3.53      3.53       3.51   NaN         96.0  96.0      96.0       96.0
                 0.3       NaN        59.50   54.48     54.48      54.48   NaN         3.84  3.77      3.77       3.76   NaN         96.0  96.0      96.0       96.0
                 0.7       NaN       104.41   84.28     84.67      84.28   NaN         5.33  4.75      4.73       4.79   NaN         96.0  96.0      96.0       96.0
                 0.9       NaN       141.10  122.03    122.44     122.00   NaN         5.35  4.61      4.59       4.67   NaN         96.0  96.0      96.0       96.0
         512     0.0       NaN        58.45   56.29     56.29      56.28   NaN         3.35  3.14      3.14       3.13   NaN         96.0  96.0      96.0       96.0
                 0.3       NaN        64.44   58.46     58.46      58.46   NaN         4.10  3.75      3.75       3.75   NaN         96.0  96.0      96.0       96.0
                 0.7       NaN       150.14  131.48    131.89     131.47   NaN         5.63  6.46      6.45       6.49   NaN         96.0  96.0      96.0       96.0
                 0.9       NaN       229.26  214.88    215.28     214.86   NaN         5.84  6.14      6.13       6.16   NaN         96.0  96.0      96.0       96.0
```
**batch=64**

```
                           mean                                             std                                          count
scheme                    islip packet_spray   ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      54.96        66.01   54.95     54.95      54.96  4.45         4.08   4.43      4.43       4.45  96.0         96.0  96.0      96.0       96.0
                 0.3      60.54        74.68   60.53     60.53      60.55  4.55         4.86   4.55      4.55       4.54  96.0         96.0  96.0      96.0       96.0
                 0.7      77.51        96.52   77.50     77.51      77.52  4.87         5.15   4.88      4.87       4.88  96.0         96.0  96.0      96.0       96.0
                 0.9      84.67       104.73   84.67     84.67      84.67  4.89         5.45   4.88      4.87       4.86  96.0         96.0  96.0      96.0       96.0
         64      0.0      60.97        72.59   60.95     60.95      60.98  4.02         3.57   4.01      4.01       4.02  96.0         96.0  96.0      96.0       96.0
                 0.3      70.19        87.89   70.18     70.18      70.17  4.17         4.32   4.17      4.17       4.17  96.0         96.0  96.0      96.0       96.0
                 0.7     110.88       139.19  110.88    111.18     110.88  4.42         5.02   4.41      4.41       4.41  96.0         96.0  96.0      96.0       96.0
                 0.9     135.69       164.48  135.70    136.01     135.69  4.41         4.87   4.40      4.38       4.42  96.0         96.0  96.0      96.0       96.0
         128     0.0      64.83        77.84   64.85     64.85      64.84  3.50         3.49   3.52      3.52       3.51  96.0         96.0  96.0      96.0       96.0
                 0.3      79.08       102.00   79.07     79.07      79.10  4.09         4.31   4.08      4.08       4.09  96.0         96.0  96.0      96.0       96.0
                 0.7     175.91       204.95  175.92    176.23     175.90  4.69         5.39   4.70      4.68       4.71  96.0         96.0  96.0      96.0       96.0
                 0.9     237.46       267.06  237.46    237.77     237.46  5.00         5.02   5.00      4.97       5.00  96.0         96.0  96.0      96.0       96.0
4        128     0.0        NaN        78.28   65.32     65.32      65.32   NaN         3.43   3.62      3.62       3.62   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       103.54   79.45     79.45      79.46   NaN         4.40   4.07      4.08       4.05   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       211.71  180.57    180.99     180.58   NaN         5.62   5.07      5.05       5.12   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       276.68  246.09    246.51     246.08   NaN         5.12   5.76      5.74       5.81   NaN         96.0  96.0      96.0       96.0
         256     0.0        NaN        82.38   68.51     68.51      68.52   NaN         3.73   3.51      3.51       3.51   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       119.70   90.07     90.17      90.05   NaN         4.90   4.98      4.94       5.01   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       319.99  295.79    296.21     295.78   NaN         5.65   8.24      8.23       8.25   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       467.70  449.90    450.31     449.91   NaN         6.01   7.89      7.87       7.93   NaN         96.0  96.0      96.0       96.0
         512     0.0        NaN        85.43   72.12     72.12      72.13   NaN         3.69   3.35      3.35       3.36   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       137.97  106.21    106.59     106.20   NaN         5.71   6.03      6.04       6.03   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       493.95  481.74    482.15     481.72   NaN         7.19  10.50     10.49      10.52   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       811.65  817.55    817.95     817.52   NaN         7.30  10.50     10.49      10.52   NaN         96.0  96.0      96.0       96.0
```
**batch=128**

```
                           mean                                              std                                          count
scheme                    islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      74.80       100.63    74.79     74.79      74.78  4.55         4.48   4.54      4.54       4.54  96.0         96.0  96.0      96.0       96.0
                 0.3      90.25       123.68    90.25     90.26      90.27  5.04         5.20   5.04      5.03       5.03  96.0         96.0  96.0      96.0       96.0
                 0.7     129.37       169.59   129.38    129.57     129.40  4.76         5.78   4.74      4.70       4.76  96.0         96.0  96.0      96.0       96.0
                 0.9     145.10       187.14   145.09    145.33     145.10  4.51         5.66   4.50      4.46       4.50  96.0         96.0  96.0      96.0       96.0
         64      0.0      80.94       107.83    80.92     80.92      80.90  4.04         3.72   4.04      4.04       4.05  96.0         96.0  96.0      96.0       96.0
                 0.3     106.64       146.75   106.64    106.66     106.65  4.32         4.28   4.32      4.30       4.32  96.0         96.0  96.0      96.0       96.0
                 0.7     208.27       251.49   208.28    208.59     208.28  4.68         5.07   4.66      4.64       4.67  96.0         96.0  96.0      96.0       96.0
                 0.9     257.70       301.72   257.70    258.01     257.70  4.80         5.20   4.78      4.77       4.78  96.0         96.0  96.0      96.0       96.0
         128     0.0      84.91       113.06    84.93     84.93      84.92  3.89         3.38   3.90      3.90       3.89  96.0         96.0  96.0      96.0       96.0
                 0.3     126.06       171.32   126.06    126.32     126.05  4.57         4.58   4.59      4.58       4.59  96.0         96.0  96.0      96.0       96.0
                 0.7     336.24       379.50   336.23    336.54     336.23  5.11         5.40   5.12      5.11       5.12  96.0         96.0  96.0      96.0       96.0
                 0.9     459.18       504.11   459.18    459.49     459.17  4.96         5.45   4.96      4.95       4.97  96.0         96.0  96.0      96.0       96.0
4        128     0.0        NaN       115.04    86.17     86.17      86.18   NaN         3.40   3.69      3.69       3.70   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       175.64   128.15    128.53     128.15   NaN         4.92   5.08      5.09       5.07   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       393.84   346.85    347.26     346.82   NaN         5.49   7.69      7.67       7.71   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       524.72   479.09    479.51     479.07   NaN         5.53   7.17      7.15       7.20   NaN         96.0  96.0      96.0       96.0
         256     0.0        NaN       119.69    89.55     89.55      89.56   NaN         3.77   3.64      3.64       3.63   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       205.85   159.42    159.83     159.40   NaN         6.01   6.88      6.87       6.92   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       607.74   577.60    578.02     577.56   NaN         6.58  11.02     11.01      11.05   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       903.72   885.32    885.73     885.28   NaN         6.49  10.06     10.04      10.10   NaN         96.0  96.0      96.0       96.0
         512     0.0        NaN       123.42    92.76     92.76      92.76   NaN         3.96   3.22      3.22       3.22   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       242.33   197.31    197.71     197.31   NaN         6.87   7.98      7.97       7.99   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       954.49   950.40    950.81     950.40   NaN         8.76  13.85     13.85      13.86   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN      1588.36  1619.88   1620.29    1619.90   NaN         8.35  14.71     14.70      14.73   NaN         96.0  96.0      96.0       96.0
```
**batch=256**

```
                           mean                                              std                                          count
scheme                    islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0     113.46       171.71   113.48    113.48     113.46  4.68         4.85   4.69      4.69       4.70  96.0         96.0  96.0      96.0       96.0
                 0.3     152.46       224.75   152.46    152.55     152.46  5.16         5.33   5.14      5.10       5.15  96.0         96.0  96.0      96.0       96.0
                 0.7     244.52       318.18   244.53    244.85     244.53  5.06         6.64   5.06      5.04       5.04  96.0         96.0  96.0      96.0       96.0
                 0.9     277.76       352.89   277.77    278.08     277.77  4.60         6.20   4.60      4.58       4.60  96.0         96.0  96.0      96.0       96.0
         64      0.0     119.69       179.39   119.69    119.69     119.71  3.90         4.03   3.92      3.92       3.92  96.0         96.0  96.0      96.0       96.0
                 0.3     189.13       265.99   189.13    189.43     189.12  4.59         4.77   4.59      4.58       4.60  96.0         96.0  96.0      96.0       96.0
                 0.7     402.00       476.66   402.00    402.31     402.01  4.96         5.73   4.97      4.97       4.95  96.0         96.0  96.0      96.0       96.0
                 0.9     501.71       578.41   501.71    502.02     501.72  4.59         6.32   4.60      4.59       4.57  96.0         96.0  96.0      96.0       96.0
         128     0.0     123.96       185.57   123.96    123.96     123.96  3.96         3.41   3.96      3.96       3.95  96.0         96.0  96.0      96.0       96.0
                 0.3     234.82       313.14   234.82    235.13     234.83  6.90         5.16   6.90      6.89       6.92  96.0         96.0  96.0      96.0       96.0
                 0.7     653.85       729.72   653.85    654.16     653.86  6.90         7.18   6.92      6.90       6.95  96.0         96.0  96.0      96.0       96.0
                 0.9     900.47       978.94   900.47    900.78     900.49  6.17         6.26   6.19      6.18       6.21  96.0         96.0  96.0      96.0       96.0
4        128     0.0        NaN       189.85   127.73    127.73     127.72   NaN         3.60   3.73      3.73       3.74   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       322.72   240.29    240.71     240.30   NaN         5.81   7.51      7.49       7.53   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       759.53   681.07    681.48     681.06   NaN         7.46  11.15     11.13      11.17   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN      1022.80   945.99    946.40     945.98   NaN         8.16   8.74      8.72       8.77   NaN         96.0  96.0      96.0       96.0
         256     0.0        NaN       195.30   130.05    130.05     130.06   NaN         4.27   3.26      3.26       3.27   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       380.62   304.11    304.52     304.11   NaN         7.69   9.43      9.43       9.46   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN      1184.78  1141.74   1142.15    1141.73   NaN         8.93  14.22     14.22      14.22   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN      1774.80  1756.82   1757.23    1756.82   NaN         9.65  14.17     14.15      14.20   NaN         96.0  96.0      96.0       96.0
         512     0.0        NaN       200.36   135.37    135.37     135.35   NaN         4.09   3.31      3.31       3.31   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN       451.43   377.35    377.76     377.34   NaN         8.23  10.93     10.92      10.94   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN      1873.71  1882.51   1882.91    1882.49   NaN        10.92  19.84     19.83      19.85   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN      3142.09  3222.79   3223.20    3222.78   NaN        11.70  20.29     20.28      20.31   NaN         96.0  96.0      96.0       96.0
```
**batch=512**

```
                            mean                                              std                                          count
scheme                     islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      190.21       316.30   190.20    190.20     190.20  4.97         5.18   4.98      4.98       4.98  96.0         96.0  96.0      96.0       96.0
                 0.3      287.02       428.28   287.02    287.33     287.03  4.88         5.90   4.88      4.88       4.88  96.0         96.0  96.0      96.0       96.0
                 0.7      476.68       616.32   476.68    477.00     476.69  5.02         6.50   5.00      4.99       5.00  96.0         96.0  96.0      96.0       96.0
                 0.9      544.26       685.37   544.27    544.59     544.27  4.48         6.48   4.47      4.45       4.47  96.0         96.0  96.0      96.0       96.0
         64      0.0      196.98       324.99   196.97    196.97     196.99  3.97         4.28   3.97      3.97       3.97  96.0         96.0  96.0      96.0       96.0
                 0.3      361.71       507.10   361.71    362.02     361.72  6.11         6.01   6.12      6.10       6.13  96.0         96.0  96.0      96.0       96.0
                 0.7      786.64       928.47   786.64    786.95     786.63  6.59         6.73   6.60      6.59       6.60  96.0         96.0  96.0      96.0       96.0
                 0.9      987.80      1130.40   987.81    988.12     987.79  5.28         7.05   5.30      5.29       5.29  96.0         96.0  96.0      96.0       96.0
         128     0.0      201.31       331.62   201.28    201.28     201.29  4.00         4.16   4.00      4.00       4.02  96.0         96.0  96.0      96.0       96.0
                 0.3      451.62       597.73   451.61    451.92     451.61  7.56         6.47   7.57      7.56       7.58  96.0         96.0  96.0      96.0       96.0
                 0.7     1288.34      1429.08  1288.35   1288.65    1288.35  9.65         7.58   9.66      9.65       9.65  96.0         96.0  96.0      96.0       96.0
                 0.9     1784.92      1928.84  1784.91   1785.22    1784.93  7.68         8.07   7.70      7.68       7.69  96.0         96.0  96.0      96.0       96.0
4        128     0.0         NaN       342.46   212.23    212.23     212.23   NaN         4.23   4.03      4.03       4.04   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       620.32   465.26    465.67     465.26   NaN         6.99  10.59     10.59      10.59   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN      1496.12  1349.92   1350.33    1349.93   NaN        10.97  15.27     15.26      15.27   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      2022.25  1879.42   1879.84    1879.44   NaN        12.24  13.20     13.19      13.21   NaN         96.0  96.0      96.0       96.0
         256     0.0         NaN       348.84   213.43    213.43     213.44   NaN         4.22   3.81      3.81       3.82   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       733.33   591.66    592.07     591.66   NaN         8.86  12.39     12.39      12.38   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN      2339.69  2266.62   2267.03    2266.59   NaN        14.22  21.69     21.70      21.68   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      3522.74  3499.85   3500.26    3499.83   NaN        13.37  18.08     18.07      18.10   NaN         96.0  96.0      96.0       96.0
         512     0.0         NaN       353.80   219.41    219.41     219.42   NaN         4.45   3.85      3.85       3.85   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       868.98   741.09    741.50     741.07   NaN         7.94  15.69     15.69      15.68   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN      3712.24  3750.00   3750.40    3749.96   NaN        14.20  30.36     30.35      30.38   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      6249.05  6433.22   6433.63    6433.18   NaN        16.04  26.17     26.16      26.20   NaN         96.0  96.0      96.0       96.0
```
### 5.1 场景1 PDF
![exp3_pdf_s1_ep128_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_ep128_s0.3.png)
![exp3_pdf_s1_ep128_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_ep128_s0.7.png)
![exp3_pdf_s1_ep128_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_ep128_s0.9.png)
![exp3_pdf_s1_ep128_s0.png](../results/ub_rg/figures/exp3_pdf_s1_ep128_s0.png)
![exp3_pdf_s1_ep32_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_ep32_s0.3.png)
![exp3_pdf_s1_ep32_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_ep32_s0.7.png)
![exp3_pdf_s1_ep32_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_ep32_s0.9.png)
![exp3_pdf_s1_ep32_s0.png](../results/ub_rg/figures/exp3_pdf_s1_ep32_s0.png)
![exp3_pdf_s1_ep64_s0.3.png](../results/ub_rg/figures/exp3_pdf_s1_ep64_s0.3.png)
![exp3_pdf_s1_ep64_s0.7.png](../results/ub_rg/figures/exp3_pdf_s1_ep64_s0.7.png)
![exp3_pdf_s1_ep64_s0.9.png](../results/ub_rg/figures/exp3_pdf_s1_ep64_s0.9.png)
![exp3_pdf_s1_ep64_s0.png](../results/ub_rg/figures/exp3_pdf_s1_ep64_s0.png)
### 5.4 场景4 PDF
![exp3_pdf_s4_ep128_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_ep128_s0.3.png)
![exp3_pdf_s4_ep128_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_ep128_s0.7.png)
![exp3_pdf_s4_ep128_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_ep128_s0.9.png)
![exp3_pdf_s4_ep128_s0.png](../results/ub_rg/figures/exp3_pdf_s4_ep128_s0.png)
![exp3_pdf_s4_ep256_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_ep256_s0.3.png)
![exp3_pdf_s4_ep256_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_ep256_s0.7.png)
![exp3_pdf_s4_ep256_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_ep256_s0.9.png)
![exp3_pdf_s4_ep256_s0.png](../results/ub_rg/figures/exp3_pdf_s4_ep256_s0.png)
![exp3_pdf_s4_ep512_s0.3.png](../results/ub_rg/figures/exp3_pdf_s4_ep512_s0.3.png)
![exp3_pdf_s4_ep512_s0.7.png](../results/ub_rg/figures/exp3_pdf_s4_ep512_s0.7.png)
![exp3_pdf_s4_ep512_s0.9.png](../results/ub_rg/figures/exp3_pdf_s4_ep512_s0.9.png)
![exp3_pdf_s4_ep512_s0.png](../results/ub_rg/figures/exp3_pdf_s4_ep512_s0.png)
### 5.4 跨场景对比 PDF（S1-EP128 / S4-EP512）
![exp3_pdf_compare_s0.3.png](../results/ub_rg/figures/exp3_pdf_compare_s0.3.png)
![exp3_pdf_compare_s0.7.png](../results/ub_rg/figures/exp3_pdf_compare_s0.7.png)
![exp3_pdf_compare_s0.9.png](../results/ub_rg/figures/exp3_pdf_compare_s0.9.png)
![exp3_pdf_compare_s0.png](../results/ub_rg/figures/exp3_pdf_compare_s0.png)
### 5.x Roundtrip Step vs EP（汇总）
> **读图**：每个面板一个 Zipf S；横轴 EP size，颜色=方案（log y）。对比同一偏斜下方案随 EP 的 roundtrip step，不再把 scheme×S 叠成折线。
![exp3_s1_step_vs_ep.png](../results/ub_rg_packet/figures/exp3_s1_step_vs_ep.png)
![exp3_s4_step_vs_ep.png](../results/ub_rg_packet/figures/exp3_s4_step_vs_ep.png)
## 6. 方案对比摘要
> 下列 step 均值均按 **batch 分列**，不跨 batch 平均。
- **场景1 batch=16** 平均 step（共有参数格）：UB_RG=40.6µs vs POP=40.9µs（POP/RG=1.01×） vs Spray=38.1µs（Spray/RG=0.94×）
- **场景1 batch=256** 平均 step（共有参数格）：UB_RG=505.6µs vs POP=505.9µs（POP/RG=1.00×） vs Spray=1161.3µs（Spray/RG=2.30×）
- **场景1 batch=16** ub_rg CCT/König：mean=3.326，median=2.210
- **场景1 batch=16** ub_rg_pop CCT/König：mean=3.357，median=2.232
- **场景1 batch=16** ub_rg_pop2 CCT/König：mean=3.270，median=2.121
- **场景1 batch=16** packet_spray CCT/König：mean=3.086，median=1.896
- **场景1 batch=256** ub_rg CCT/König：mean=2.472，median=2.186
- **场景1 batch=256** ub_rg_pop CCT/König：mean=2.475，median=2.188
- **场景1 batch=256** ub_rg_pop2 CCT/König：mean=2.459，median=2.164
- **场景1 batch=256** packet_spray CCT/König：mean=4.023，median=3.762
- **场景4 batch=16** 平均 step（共有参数格）：UB_RG=80.4µs vs POP=81.0µs（POP/RG=1.01×） vs Spray=84.3µs（Spray/RG=1.05×）
- **场景4 batch=16** ub_rg CCT/König：mean=0.513，median=0.235
- **场景4 batch=16** ub_rg_pop CCT/König：mean=0.521，median=0.239
- **场景4 batch=16** ub_rg_pop2 CCT/König：mean=0.503，median=0.235
- **场景4 batch=16** packet_spray CCT/König：mean=0.507，median=0.242
- **场景4 batch=256** ub_rg CCT/König：mean=0.692，median=0.678
- **场景4 batch=256** ub_rg_pop CCT/König：mean=0.635，median=0.635
- **场景4 batch=256** packet_spray CCT/König：mean=0.935，median=0.934
## 7. 双引擎对比（逐包 vs 行为级）
在相同 (scenario, scheme, mode, batch, zipf_s, ep_size) 键上对齐 step_us / lat_p99。
对齐样本 **2440** 组；step 比值（packet/behavioral）均值=1.840，中位数=0.878。
```
          exp  scenario       scheme     mode  batch  zipf_s  ep_size  step_packet  p99_packet  step_behav  p99_behav  step_ratio
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       15.987      11.645      11.855      7.131       1.349
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       15.987      11.645      20.058     14.955       0.797
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       15.987      11.645      28.936     25.646       0.552
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       15.987      11.645      51.752     48.319       0.309
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       18.500       9.330      11.855      7.131       1.561
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       18.500       9.330      20.058     14.955       0.922
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       18.500       9.330      28.936     25.646       0.639
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       18.500       9.330      51.752     48.319       0.357
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       28.599       6.151      11.855      7.131       2.412
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       28.599       6.151      20.058     14.955       1.426
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       28.599       6.151      28.936     25.646       0.988
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       28.599       6.151      51.752     48.319       0.553
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       51.599       5.176      11.855      7.131       4.352
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       51.599       5.176      20.058     14.955       2.572
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       51.599       5.176      28.936     25.646       1.783
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       51.599       5.176      51.752     48.319       0.997
exp1_dispatch         1 packet_spray dispatch     16     0.7      128       37.825      34.035      24.901     19.030       1.519
exp1_dispatch         1 packet_spray dispatch     16     0.7      128       37.825      34.035      31.957     26.270       1.184
exp1_dispatch         1 packet_spray dispatch     16     0.7      128       37.825      34.035      40.384     34.656       0.937
exp1_dispatch         1 packet_spray dispatch     16     0.7      128       37.825      34.035      58.591     51.716       0.646
```
若该比值显著偏离 1，不能仅解释为“逐包栈静态开销”。逐包引擎含真实CBFC/缓冲与控制面，行为级折叠了 byte buffer；两引擎 plane 映射也不一致。在统一输入、完成守恒和异常门禁通过前，这里是**交叉验证对照**，不是行为级绝对值校准。
- **packet** batch=16 同参数格平均：POP/RG=1.009×，Spray/RG=1.482×
- **packet** batch=256 同参数格平均：POP/RG=0.999×，Spray/RG=4.086×
- **behavioral** batch=16 同参数格平均：POP/RG=1.002×，Spray/RG=0.858×
- **behavioral** batch=64 同参数格平均：POP/RG=1.000×，Spray/RG=1.136×
- **behavioral** batch=128 同参数格平均：POP/RG=1.000×，Spray/RG=1.144×
- **behavioral** batch=256 同参数格平均：POP/RG=1.000×，Spray/RG=0.644×
- **behavioral** batch=512 同参数格平均：POP/RG=1.000×，Spray/RG=1.158×
## 8. 复现方法
逐包引擎复现（仅用于协议调试；性能门禁通过前不要当作绝对值校准）：
```bash
cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus --enable-mtp --disable-python -d optimized
./ns3 build ub_rg-packet-experiment
cd ..
python3 gen_ub_rg_topo.py --scenario 1
python3 run_ub_rg_experiments.py --engine packet --workers 4
python3 analyze_ub_rg_experiments.py --engine packet
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
| S4 / iSLIP / POP2 / 空拍排空 / 启动偏差 / GEMV | PathClass、iSLIP、UniversalGntDepth、egress drain idle、start-skew、ComputeGemvUs | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc` |
| 逐包 POP2 万能 GNT | `SetPop2Enabled` / `TrySpeculate` / `HandleGnt` 归还池 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-sender-agent.cc` |
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

