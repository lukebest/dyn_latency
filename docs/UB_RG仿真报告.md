# UB_RG 网络仿真报告
> **可信性状态：实现证据存在，性能结论未验证。** 行为级结果仅作为网络机制假设；方案间路由、path delay、jitter 与 barrier 混杂尚未消除，逐包性能矩阵也未通过完成守恒与跨引擎校验。绝对硬件时延与完整POP硅片实现不得据此下结论；Exp3 GEMV 为标定服务模型。详见[UB_RG仿真可信性评估报告](./UB_RG仿真可信性评估报告.html)。
## 1. 主要实验结论
> 结论适用于场景1/4；Exp1/2 为网络子系统；Exp3 含 Zipf×batch GEMV straggler；启动偏差为 N(0,σ²)，σ∈{0,2,4,8} µs。
- **配置包输出差异**（Exp1，按 batch 分列，不跨 batch 平均 step）：batch=16：POP/RG=**1.004×**，Spray/RG=**2.067×**；batch=256：POP/RG=**1.000×**，Spray/RG=**8.715×**，POP2/RG 平均为 **1.010×**。这是当前配置包的联合差异；plane、path delay、jitter 和 barrier 尚未统一，不能把比值单独归因于目的侧配速（见 §1.1）。
- **POP 启动开销会被负载摊薄**：batch=16 时 POP/RG=**1.004×**，batch=256 时为 **1.000×**；结果符合“多一次 one-way 启动、稳态节拍与 RG 相同”的模型预期。
- **瓶颈下界**：CCT/König 中位数为 ub_rg=7.660、ub_rg_pop=7.682、ub_rg_pop2=7.670、packet_spray=8.819；它证明输出符合当前方程，但不是排除混杂后的硬件性能验证。
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

引擎：**packet**；成功汇总运行数：**896**。原始结果：`results/ub_rg_packet/`。
> 上表对齐当前 runner：仅场景1+4；启动偏差为 N(0,σ²)（σ∈{0,2,4,8}）；场景1 含 iSLIP；Exp3 输出 gemv_us/e2e_us。旧场景2/3 结果请忽略。
> 逐包引擎按风险路径裁剪且当前完整度不足；行为级引擎覆盖完整主矩阵与 PDF。本报告方案对比仅使用本引擎结果，不与行为级混比。实验3 系统 CCT PDF 若本引擎样本未齐，报告自动回退到行为级多 seed 结果。
## 3. 实验1：倾斜专家流量下的 Dispatch
> 下表按 **batch 分列**；不同 batch 的 `step_us` 不放在同一张表。
### 3.1 场景1
**batch=16 对比表**

```
             cct_us                                  hot_p99                                  lat_p99                                  step_us                             throughput_GBs
scheme packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2 packet_spray  ub_rg ub_rg_pop ub_rg_pop2   packet_spray    ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           42.99  25.89     26.19      25.26        30.96   4.86      5.16       5.06        30.70   4.83      5.13       4.96        44.99  26.29     26.59      25.66        3003.73  6386.99   6255.08    6781.90
0.3           67.89  28.85     29.15      28.38        54.94   8.13      8.43       7.96        47.25   6.24      6.54       6.17        69.89  29.25     29.55      28.78        1740.17  4848.30   4781.47    4937.89
0.7          212.12  46.13     46.43      45.78       180.77  24.37     24.67      23.87       156.70  21.92     22.22      21.23       214.12  46.53     46.83      46.18         554.36  2568.48   2551.60    2587.36
0.9          468.99  59.80     60.10      59.47       339.36  32.81     33.11      32.01       290.85  30.95     31.25      30.23       470.99  60.20     60.50      59.87         262.67  1969.23   1959.35    1980.35
```
**batch=256 对比表**

```
             cct_us                                   hot_p99                                   lat_p99                                   step_us                              throughput_GBs
scheme packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2 packet_spray   ub_rg ub_rg_pop ub_rg_pop2   packet_spray     ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0          417.63  162.97    163.27     162.52       381.13   67.14     67.44      68.40       351.07   56.69     56.99      55.97       419.63  163.37    163.67     162.92        4500.90  11552.86  11531.55   11649.34
0.3         3801.59  250.14    250.44     249.40      2376.45  125.03    125.33     125.05       394.90   64.62     64.92      63.78      3803.59  250.54    250.84     249.80         494.49   7512.39   7503.39    7534.45
0.7        15516.33  658.89    659.19     657.25      1189.91  201.68    201.98     200.97       787.32  115.72    116.02     114.38     15518.33  659.29    659.59     657.65         121.18   2851.92   2850.62    2858.97
0.9        26977.15  948.63    948.93     934.67      1200.96  223.66    223.96     222.93      1439.62  217.89    218.19     218.20     26979.15  949.03    949.33     935.07          69.65   1981.96   1981.33    2011.89
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
             cct_us                                     hot_p99                                 lat_p99                                 step_us                                throughput_GBs
scheme packet_spray     ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray     ub_rg ub_rg_pop ub_rg_pop2   packet_spray ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           28.64  17856.85  17857.40    7858.52        21.18  1.54      2.09       2.46        20.48  1.79      2.34       2.48        32.64  17858.05  17858.60    7859.72          57.16  0.15      0.15      35.13
0.3           29.18  17856.73  17857.28   12858.81        20.46  1.56      2.11       4.63        20.66  1.70      2.25       3.76        33.18  17857.93  17858.48   12860.01          79.33  0.22      0.22       3.85
0.7           36.90  17860.38  17860.93   17861.31        25.64  1.40      1.95      23.40        26.04  1.62      2.17      20.18        40.90  17861.58  17862.13   17862.51         101.18  0.31      0.31       2.96
0.9           68.42  17861.35  17861.90   17862.35        23.44  1.47      2.02      39.54        22.70  1.55      2.10      36.53        72.42  17862.55  17863.10   17863.55         179.67  0.33      0.33       2.97
```
**batch=256 对比表**

```
             cct_us                                       hot_p99                                 lat_p99                                    step_us                                  throughput_GBs
scheme packet_spray      ub_rg  ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray    ub_rg ub_rg_pop ub_rg_pop2 packet_spray      ub_rg  ub_rg_pop ub_rg_pop2   packet_spray ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           35.50   94040.64   94041.19   91514.46        26.39  1.66      2.21       2.50        25.81     1.99      2.54       2.50        39.50   94041.84   94042.39   91515.66          36.64  0.22      0.22       0.49
0.3           34.13  131463.89  131464.44  233815.58        20.02  1.84      2.39   12507.40        20.25     1.95      2.50       6.09        38.13  131465.09  131465.64  233816.78          77.44  0.30      0.30       0.30
0.7           50.54  258823.79  258824.34  548467.53        22.04  1.87      2.42    2522.41        27.97  4979.14   4979.69    2555.70        54.54  258824.99  258825.54  548468.73          68.74  0.23      0.23       0.28
0.9           56.88  553483.30  553483.85  111563.82        33.47  4.95      5.50      41.74        34.23     2.39      2.94      38.77        60.88  553484.50  553485.05  111565.02         117.80  0.22      0.22       0.55
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
             cct_us                                     hot_p99                                 lat_p99                                 step_us                                throughput_GBs
scheme packet_spray     ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray     ub_rg ub_rg_pop ub_rg_pop2   packet_spray ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0           30.26   7857.56   7858.11    7857.03        20.86   0.0       0.0       3.70        20.42  1.41      1.96       3.48        34.26   7858.76   7859.31    7858.23         136.50  1.00      0.99      35.03
0.3           31.45   7860.78   7861.33    7860.55        23.13   0.0       0.0       5.92        21.04  1.66      2.21       4.83        35.45   7861.98   7862.53    7861.75         113.79  0.76      0.76      40.16
0.7           33.24   7861.74   7862.29    7857.88        23.30   0.0       0.0       9.10        21.22  1.62      2.17       6.55        37.24   7862.94   7863.49    7859.08         322.01  0.51      0.51      45.41
0.9           40.73  10350.22  10350.77   10316.52        23.74   0.0       0.0       9.95        20.31  1.49      2.04       7.09        44.73  10351.42  10351.97   10317.72         568.06  0.06      0.06       5.36
```
**batch=256 对比表**

```
             cct_us                                     hot_p99                                 lat_p99                                 step_us                                throughput_GBs
scheme packet_spray     ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray ub_rg ub_rg_pop ub_rg_pop2 packet_spray     ub_rg ub_rg_pop ub_rg_pop2   packet_spray ub_rg ub_rg_pop ub_rg_pop2
zipf_s
0.0         3308.91  91466.14  91466.70   93962.58      1659.07   0.0       0.0      69.11        33.14  1.84      2.39      66.26      3312.91  91467.34  91467.90   93963.78         158.88  0.14      0.14       0.49
0.3         3326.98  78556.82  78557.37   78557.82        33.75   0.0       0.0      87.18       841.57  1.92      2.47      80.82      3330.98  78558.02  78558.57   78559.02         194.82  0.14      0.14       0.58
0.7           48.29  38205.07  38205.62   38204.21        35.57   0.0       0.0      94.63        35.63  1.72      2.27      87.59        52.29  38206.27  38206.82   38205.41         257.87  0.16      0.16       1.19
0.9          134.91  30354.23  30354.78   30353.00        35.66   0.0       0.0      91.26        35.30  1.74      2.29      83.96       138.91  30355.43  30355.98   30354.20          89.22  0.12      0.12       1.47
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
每场景单独出 PDF；另附跨场景对比图（S1-EP128 / S4-EP512）。线型区分方案（实线 ub_rg，点划线 ub_rg_pop，密虚线 ub_rg_pop2，虚线 packet_spray，点线 islip）。
（当前引擎尚无 exp3_pdf；下图暂用 **behavioral** 引擎样本）
**系统 CCT 样本统计（µs，mean/std/count）**——按 batch 分表，不把不同 batch 混在一张表里。
**batch=16**

```
                           mean                                               std                                          count
scheme                    islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2  islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      89.49        41.61    86.90     87.50      86.91   4.53         4.25   4.76      4.76       4.73  96.0         96.0  96.0      96.0       96.0
                 0.3     107.18        42.37   103.36    103.96     103.37   6.95         4.15   6.67      6.67       6.64  96.0         96.0  96.0      96.0       96.0
                 0.7     153.91        45.40   143.60    144.20     143.60   7.50         4.21   6.87      6.87       6.85  96.0         96.0  96.0      96.0       96.0
                 0.9     171.03        46.72   159.24    159.84     159.24   7.25         4.33   7.35      7.35       7.35  96.0         96.0  96.0      96.0       96.0
         64      0.0      99.68        47.60    95.53     96.13      95.45   5.03         3.88   4.37      4.37       4.37  96.0         96.0  96.0      96.0       96.0
                 0.3     133.44        49.26   124.86    125.46     124.83   8.33         3.75   5.86      5.86       5.88  96.0         96.0  96.0      96.0       96.0
                 0.7     250.28        57.51   208.61    209.21     208.62   9.10         4.16   5.25      5.25       5.24  96.0         96.0  96.0      96.0       96.0
                 0.9     303.54        62.67   247.73    248.33     247.74  10.34         4.24   6.65      6.65       6.65  96.0         96.0  96.0      96.0       96.0
         128     0.0     105.46        51.76   101.93    102.53     101.65   4.64         3.66   4.45      4.45       4.44  96.0         96.0  96.0      96.0       96.0
                 0.3     162.32        54.60   145.24    145.84     145.04  10.09         3.65   5.61      5.61       5.63  96.0         96.0  96.0      96.0       96.0
                 0.7     400.17        74.74   295.41    296.01     295.39  16.06         4.26   6.82      6.82       6.80  96.0         96.0  96.0      96.0       96.0
                 0.9     536.89        89.73   380.00    380.60     380.00  17.27         4.55   7.02      7.02       7.02  96.0         96.0  96.0      96.0       96.0
4        128     0.0        NaN        51.83   102.92    103.72     102.61    NaN         3.68   4.26      4.26       4.17   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN        54.52   145.57    146.37     145.37    NaN         3.66   5.80      5.80       5.83   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN        75.88   297.23    298.03     297.25    NaN         4.41   7.29      7.29       7.30   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN        91.56   384.43    385.23     384.44    NaN         4.61   8.48      8.48       8.48   NaN         96.0  96.0      96.0       96.0
         256     0.0        NaN        55.08   107.32    108.12     106.50    NaN         3.64   3.73      3.73       3.80   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN        59.50   169.27    170.07     168.90    NaN         3.84   7.49      7.49       7.64   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       104.41   432.83    433.63     432.82    NaN         5.33  12.07     12.07      12.07   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       141.10   621.53    622.33     621.53    NaN         5.35  13.22     13.22      13.20   NaN         96.0  96.0      96.0       96.0
         512     0.0        NaN        58.45   112.50    113.30     111.94    NaN         3.35   3.90      3.90       4.08   NaN         96.0  96.0      96.0       96.0
                 0.3        NaN        64.44   193.07    193.87     192.55    NaN         4.10   8.40      8.40       8.23   NaN         96.0  96.0      96.0       96.0
                 0.7        NaN       150.14   651.19    651.99     651.12    NaN         5.63  20.43     20.43      20.41   NaN         96.0  96.0      96.0       96.0
                 0.9        NaN       229.26  1068.19   1068.99    1067.76    NaN         5.84  21.75     21.75      21.72   NaN         96.0  96.0      96.0       96.0
```
**batch=64**

```
                            mean                                               std                                          count
scheme                     islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2  islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      236.60        66.01   231.68    232.28     231.68   6.77         4.08   6.63      6.63       6.62  96.0         96.0  96.0      96.0       96.0
                 0.3      342.54        74.68   323.73    324.33     323.73  16.11         4.86  11.93     11.93      11.92  96.0         96.0  96.0      96.0       96.0
                 0.7      548.61        96.52   493.41    494.01     493.41  18.24         5.15  16.05     16.05      16.05  96.0         96.0  96.0      96.0       96.0
                 0.9      620.13       104.73   558.16    558.76     558.16  17.26         5.45  17.49     17.49      17.48  96.0         96.0  96.0      96.0       96.0
         64      0.0      251.43        72.59   245.63    246.23     245.63   6.04         3.57   6.11      6.11       6.09  96.0         96.0  96.0      96.0       96.0
                 0.3      434.20        87.89   390.16    390.76     390.17  17.68         4.32  10.87     10.87      10.88  96.0         96.0  96.0      96.0       96.0
                 0.7      909.62       139.19   725.77    726.37     725.77  24.18         5.02  10.56     10.56      10.55  96.0         96.0  96.0      96.0       96.0
                 0.9     1133.21       164.48   888.24    888.84     888.24  26.21         4.87   9.43      9.43       9.42  96.0         96.0  96.0      96.0       96.0
         128     0.0      265.06        77.84   255.10    255.70     255.11   5.83         3.49   6.00      6.00       6.01  96.0         96.0  96.0      96.0       96.0
                 0.3      541.53       102.00   456.30    456.90     456.31  23.47         4.31  12.84     12.84      12.85  96.0         96.0  96.0      96.0       96.0
                 0.7     1485.65       204.95  1051.80   1052.40    1051.82  42.77         5.39  14.67     14.67      14.70  96.0         96.0  96.0      96.0       96.0
                 0.9     2038.90       267.06  1397.30   1397.90    1397.31  49.51         5.02  13.47     13.47      13.47  96.0         96.0  96.0      96.0       96.0
4        128     0.0         NaN        78.28   262.85    263.65     262.86    NaN         3.43   6.37      6.37       6.35   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       103.54   460.44    461.24     460.46    NaN         4.40  12.42     12.42      12.44   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       211.71  1072.83   1073.63    1072.85    NaN         5.62  16.83     16.83      16.83   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN       276.68  1435.14   1435.94    1435.15    NaN         5.12  20.18     20.18      20.19   NaN         96.0  96.0      96.0       96.0
         256     0.0         NaN        82.38   268.12    268.92     268.13    NaN         3.73   5.84      5.84       5.86   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       119.70   539.36    540.16     539.39    NaN         4.90  14.80     14.80      14.79   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       319.99  1619.15   1619.95    1619.18    NaN         5.65  32.25     32.25      32.24   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN       467.70  2417.24   2418.04    2417.27    NaN         6.01  30.94     30.94      30.94   NaN         96.0  96.0      96.0       96.0
         512     0.0         NaN        85.43   277.03    277.83     276.88    NaN         3.69   6.48      6.48       6.48   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       137.97   628.70    629.50     628.69    NaN         5.71  21.97     21.97      21.96   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       493.95  2528.44   2529.24    2528.42    NaN         7.19  46.63     46.63      46.61   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN       811.65  4216.59   4217.39    4216.58    NaN         7.30  45.91     45.91      45.91   NaN         96.0  96.0      96.0       96.0
```
**batch=128**

```
                            mean                                               std                                          count
scheme                     islip packet_spray    ub_rg ub_rg_pop ub_rg_pop2  islip packet_spray  ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      422.56       100.63   415.91    416.51     415.93   8.84         4.48   8.35      8.35       8.35  96.0         96.0  96.0      96.0       96.0
                 0.3      650.35       123.68   610.48    611.08     610.49  20.76         5.20  16.65     16.65      16.63  96.0         96.0  96.0      96.0       96.0
                 0.7     1070.54       169.59   954.66    955.26     954.67  32.15         5.78  28.09     28.09      28.07  96.0         96.0  96.0      96.0       96.0
                 0.9     1216.94       187.14  1088.18   1088.78    1088.19  31.60         5.66  32.33     32.33      32.32  96.0         96.0  96.0      96.0       96.0
         64      0.0      442.54       107.83   432.97    433.57     432.98   9.01         3.72   8.22      8.22       8.21  96.0         96.0  96.0      96.0       96.0
                 0.3      829.22       146.75   733.57    734.17     733.57  25.37         4.28  14.96     14.96      14.95  96.0         96.0  96.0      96.0       96.0
                 0.7     1782.57       251.49  1409.77   1410.37    1409.78  43.14         5.07  15.65     15.65      15.65  96.0         96.0  96.0      96.0       96.0
                 0.9     2226.70       301.72  1733.30   1733.90    1733.31  48.12         5.20  13.59     13.59      13.58  96.0         96.0  96.0      96.0       96.0
         128     0.0      457.60       113.06   445.13    445.73     445.12   8.21         3.38   8.19      8.19       8.18  96.0         96.0  96.0      96.0       96.0
                 0.3     1037.85       171.32   858.61    859.21     858.60  31.48         4.58  16.13     16.13      16.14  96.0         96.0  96.0      96.0       96.0
                 0.7     2921.86       379.50  2050.23   2050.83    2050.22  71.17         5.40  19.05     19.05      19.03  96.0         96.0  96.0      96.0       96.0
                 0.9     4025.55       504.11  2738.18   2738.78    2738.17  89.04         5.45  17.08     17.08      17.08  96.0         96.0  96.0      96.0       96.0
4        128     0.0         NaN       115.04   464.97    465.77     464.97    NaN         3.40   9.54      9.54       9.52   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       175.64   868.95    869.75     868.97    NaN         4.92  18.63     18.63      18.62   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       393.84  2097.87   2098.67    2097.88    NaN         5.49  28.94     28.94      28.93   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN       524.72  2827.30   2828.10    2827.31    NaN         5.53  27.77     27.77      27.76   NaN         96.0  96.0      96.0       96.0
         256     0.0         NaN       119.69   470.16    470.96     470.15    NaN         3.77   8.67      8.67       8.69   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       205.85  1026.70   1027.50    1026.70    NaN         6.01  26.92     26.92      26.92   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       607.74  3215.29   3216.09    3215.27    NaN         6.58  47.90     47.90      47.91   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN       903.72  4808.35   4809.15    4808.34    NaN         6.49  41.69     41.69      41.68   NaN         96.0  96.0      96.0       96.0
         512     0.0         NaN       123.42   485.82    486.62     485.78    NaN         3.96   8.14      8.14       8.18   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       242.33  1208.22   1209.02    1208.23    NaN         6.87  33.98     33.98      33.97   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       954.49  5048.47   5049.27    5048.48    NaN         8.76  66.45     66.45      66.44   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      1588.36  8412.99   8413.79    8413.01    NaN         8.35  69.28     69.28      69.29   NaN         96.0  96.0      96.0       96.0
```
**batch=256**

```
                            mean                                                 std                                           count
scheme                     islip packet_spray     ub_rg ub_rg_pop ub_rg_pop2   islip packet_spray   ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      783.73       171.71    772.81    773.41     772.81   11.93         4.85   10.77     10.77      10.77  96.0         96.0  96.0      96.0       96.0
                 0.3     1267.08       224.75   1181.19   1181.79    1181.20   32.12         5.33   29.98     29.98      29.98  96.0         96.0  96.0      96.0       96.0
                 0.7     2105.91       318.18   1868.70   1869.30    1868.70   59.74         6.64   53.65     53.65      53.66  96.0         96.0  96.0      96.0       96.0
                 0.9     2404.46       352.89   2137.77   2138.37    2137.78   60.56         6.20   60.69     60.69      60.70  96.0         96.0  96.0      96.0       96.0
         64      0.0      808.24       179.39    794.80    795.40     794.79   12.19         4.03   11.08     11.08      11.07  96.0         96.0  96.0      96.0       96.0
                 0.3     1612.99       265.99   1416.34   1416.94    1416.33   35.08         4.77   19.59     19.59      19.60  96.0         96.0  96.0      96.0       96.0
                 0.7     3516.99       476.66   2764.06   2764.66    2764.06   73.45         5.73   21.00     21.00      21.01  96.0         96.0  96.0      96.0       96.0
                 0.9     4412.07       578.41   3414.24   3414.84    3414.23   87.83         6.32   18.57     18.57      18.56  96.0         96.0  96.0      96.0       96.0
         128     0.0      830.00       185.65    809.96    810.56     809.97   11.91         3.41    9.47      9.47       9.48  96.0         94.0  96.0      96.0       96.0
                 0.3     2017.02       313.14   1653.94   1654.54    1653.96   53.83         5.16   26.57     26.57      26.58  96.0         96.0  96.0      96.0       96.0
                 0.7     5770.16       729.72   4024.83   4025.43    4024.84  138.50         7.18   28.92     28.92      28.96  96.0         96.0  96.0      96.0       96.0
                 0.9     7982.23       978.94   5406.05   5406.65    5406.06  175.98         6.26   22.63     22.63      22.65  96.0         96.0  96.0      96.0       96.0
4        128     0.0         NaN       189.85    862.06    862.86     862.06     NaN         3.60   13.67     13.67      13.67   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       322.72   1682.43   1683.23    1682.42     NaN         5.81   33.05     33.05      33.06   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN       759.53   4149.24   4150.04    4149.23     NaN         7.46   46.95     46.95      46.96   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      1022.80   5612.72   5613.52    5612.72     NaN         8.16   36.56     36.56      36.57   NaN         96.0  96.0      96.0       96.0
         256     0.0         NaN       195.30    866.53    867.33     866.55     NaN         4.27   12.85     12.85      12.84   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       380.62   1998.70   1999.50    1998.72     NaN         7.69   42.40     42.40      42.39   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN      1184.78   6411.96   6412.76    6411.98     NaN         8.93   67.24     67.24      67.23   NaN         96.0  96.0      96.0       96.0
                 0.9         NaN      1774.80   9595.50   9596.30    9595.52     NaN         9.65   63.41     63.41      63.40   NaN         96.0  96.0      96.0       96.0
         512     0.0         NaN       200.36    888.97    889.77     888.97     NaN         4.09   10.79     10.79      10.79   NaN         96.0  96.0      96.0       96.0
                 0.3         NaN       451.43   2349.48   2350.28    2349.47     NaN         8.23   50.76     50.76      50.75   NaN         96.0  96.0      96.0       96.0
                 0.7         NaN          NaN  10060.77  10057.10        NaN     NaN          NaN   98.07     98.46        NaN   NaN          NaN  96.0      82.0        NaN
                 0.9         NaN      3142.09  16796.37  16795.53   16794.72     NaN        11.70  100.61     99.64      99.66   NaN         96.0  86.0      96.0       96.0
```
**batch=512**

```
                             mean                                                 std                                           count
scheme                      islip packet_spray     ub_rg ub_rg_pop ub_rg_pop2   islip packet_spray   ub_rg ub_rg_pop ub_rg_pop2 islip packet_spray ub_rg ub_rg_pop ub_rg_pop2
scenario ep_size zipf_s
1        32      0.0      1488.66       316.30   1473.96   1474.56    1473.95   17.18         5.18   14.29     14.29      14.28  96.0         96.0  96.0      96.0       96.0
                 0.3      2490.74       428.28   2314.39   2314.99    2314.39   52.55         5.90   49.59     49.59      49.59  96.0         96.0  96.0      96.0       96.0
                 0.7      4174.09       616.32   3689.61   3690.21    3689.61  110.93         6.50  102.71    102.71     102.70  96.0         96.0  96.0      96.0       96.0
                 0.9      4779.45       685.37   4231.10   4231.70    4231.10  117.69         6.48  117.07    117.07     117.07  96.0         96.0  96.0      96.0       96.0
         64      0.0      1522.64       324.99   1503.53   1504.13    1503.52   17.65         4.28   15.48     15.48      15.48  96.0         96.0  96.0      96.0       96.0
                 0.3      3161.09       507.10   2756.96   2757.56    2756.94   61.22         6.01   30.64     30.64      30.65  96.0         96.0  96.0      96.0       96.0
                 0.7      6963.16       928.47   5449.12   5449.72    5449.10  149.07         6.73   32.70     32.70      32.72  96.0         96.0  96.0      96.0       96.0
                 0.9      8767.17      1130.40   6758.93   6759.53    6758.91  176.34         7.05   30.92     30.92      30.92  96.0         96.0  96.0      96.0       96.0
         128     0.0      1552.56       331.62   1524.46   1525.06    1524.46   16.70         4.16   16.70     16.70      16.71  96.0         96.0  96.0      96.0       96.0
                 0.3      3962.21       597.73   3226.92   3227.52    3226.92   77.14         6.47   31.98     31.98      32.00  96.0         96.0  96.0      96.0       96.0
                 0.7     11458.94      1429.08   7966.56   7967.16    7966.56  261.12         7.58   40.32     40.32      40.34  96.0         96.0  96.0      96.0       96.0
                 0.9     15910.26      1928.84  10761.74  10762.34   10761.74  351.42         8.07   32.17     32.17      32.19  96.0         96.0  96.0      96.0       96.0
4        128     0.0          NaN       342.46   1647.95   1648.75    1647.96     NaN         4.23   21.63     21.63      21.64   NaN         96.0  96.0      96.0       96.0
                 0.3          NaN       620.32   3299.50   3300.30    3299.51     NaN         6.99   52.40     52.40      52.39   NaN         96.0  96.0      96.0       96.0
                 0.7          NaN      1496.12   8252.64   8253.44    8252.65     NaN        10.97   68.57     68.57      68.56   NaN         96.0  96.0      96.0       96.0
                 0.9          NaN      2022.25  11192.90  11193.70   11192.93     NaN        12.24   59.50     59.50      59.49   NaN         96.0  96.0      96.0       96.0
         256     0.0          NaN       348.84   1635.10   1635.90    1635.09     NaN         4.22   18.15     18.15      18.15   NaN         96.0  96.0      96.0       96.0
                 0.3          NaN       733.33   3925.71   3926.51    3925.70     NaN         8.86   61.16     61.16      61.15   NaN         96.0  96.0      96.0       96.0
                 0.7          NaN      2339.69  12790.67  12791.47   12790.67     NaN        14.22  107.08    107.08     107.09   NaN         96.0  96.0      96.0       96.0
                 0.9          NaN      3522.74  19168.01  19168.81   19168.00     NaN        13.37   87.30     87.30      87.32   NaN         96.0  96.0      96.0       96.0
         512     0.0          NaN       353.80   1673.00   1673.80    1672.98     NaN         4.45   17.26     17.26      17.25   NaN         96.0  96.0      96.0       96.0
                 0.3          NaN       868.98   4642.32   4643.12    4642.30     NaN         7.94   72.87     72.87      72.86   NaN         96.0  96.0      96.0       96.0
                 0.7          NaN      3712.24  20104.30  20105.10   20104.27     NaN        14.20  150.68    150.68     150.70   NaN         96.0  96.0      96.0       96.0
                 0.9          NaN      6249.05  33581.31  33582.11   33581.28     NaN        16.04  127.98    127.98     128.01   NaN         96.0  96.0      96.0       96.0
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
![exp3_s1_step_vs_ep.png](../results/ub_rg_packet/figures/exp3_s1_step_vs_ep.png)
![exp3_s4_step_vs_ep.png](../results/ub_rg_packet/figures/exp3_s4_step_vs_ep.png)
## 6. 方案对比摘要
> 下列 step 均值均按 **batch 分列**，不跨 batch 平均。
- **场景1 batch=16** 平均 step（共有参数格）：UB_RG=40.6µs vs POP=40.9µs（POP/RG=1.01×） vs Spray=200.0µs（Spray/RG=4.93×）
- **场景1 batch=256** 平均 step（共有参数格）：UB_RG=505.6µs vs POP=505.9µs（POP/RG=1.00×） vs Spray=11680.2µs（Spray/RG=23.10×）
- **场景1 batch=16** ub_rg CCT/König：mean=3.326，median=2.210
- **场景1 batch=16** ub_rg_pop CCT/König：mean=3.357，median=2.232
- **场景1 batch=16** ub_rg_pop2 CCT/König：mean=3.270，median=2.121
- **场景1 batch=16** packet_spray CCT/König：mean=10.757，median=9.632
- **场景1 batch=256** ub_rg CCT/König：mean=2.472，median=2.186
- **场景1 batch=256** ub_rg_pop CCT/König：mean=2.475，median=2.188
- **场景1 batch=256** ub_rg_pop2 CCT/König：mean=2.459，median=2.164
- **场景1 batch=256** packet_spray CCT/König：mean=37.562，median=39.962
- **场景4 batch=16** 平均 step（共有参数格）：UB_RG=17860.0µs vs POP=17860.6µs（POP/RG=1.00×） vs Spray=44.8µs（Spray/RG=0.00×）
- **场景4 batch=256** 平均 step（共有参数格）：UB_RG=259454.1µs vs POP=259454.7µs（POP/RG=1.00×） vs Spray=48.3µs（Spray/RG=0.00×）
- **场景4 batch=16** ub_rg CCT/König：mean=255.710，median=80.907
- **场景4 batch=16** ub_rg_pop CCT/König：mean=255.718，median=80.911
- **场景4 batch=16** ub_rg_pop2 CCT/König：mean=135.605，median=47.542
- **场景4 batch=16** packet_spray CCT/König：mean=0.430，median=0.137
- **场景4 batch=256** ub_rg CCT/König：mean=120.435，median=90.335
- **场景4 batch=256** ub_rg_pop CCT/König：mean=120.435，median=90.336
- **场景4 batch=256** ub_rg_pop2 CCT/König：mean=138.674，median=94.223
- **场景4 batch=256** packet_spray CCT/König：mean=0.038，median=0.010
## 7. 双引擎对比（逐包 vs 行为级）
在相同 (scenario, scheme, mode, batch, zipf_s, ep_size) 键上对齐 step_us / lat_p99。
对齐样本 **3584** 组；step 比值（packet/behavioral）均值=87.119，中位数=3.427。
```
          exp  scenario       scheme     mode  batch  zipf_s  ep_size  step_packet  p99_packet  step_behav  p99_behav  step_ratio
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.439      49.862      11.855      7.131       5.351
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.439      49.862      20.058     14.955       3.163
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.439      49.862      28.936     25.646       2.192
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       63.439      49.862      51.752     48.319       1.226
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       67.491      49.567      11.855      7.131       5.693
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       67.491      49.567      20.058     14.955       3.365
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       67.491      49.567      28.936     25.646       2.332
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       67.491      49.567      51.752     48.319       1.304
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       70.714      47.183      11.855      7.131       5.965
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       70.714      47.183      20.058     14.955       3.525
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       70.714      47.183      28.936     25.646       2.444
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       70.714      47.183      51.752     48.319       1.366
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       77.924      42.393      11.855      7.131       6.573
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       77.924      42.393      20.058     14.955       3.885
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       77.924      42.393      28.936     25.646       2.693
exp1_dispatch         1 packet_spray dispatch     16     0.3      128       77.924      42.393      51.752     48.319       1.506
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      222.284     177.540      24.901     19.030       8.927
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      222.284     177.540      31.957     26.270       6.956
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      222.284     177.540      40.384     34.656       5.504
exp1_dispatch         1 packet_spray dispatch     16     0.7      128      222.284     177.540      58.591     51.716       3.794
```
若该比值显著偏离 1，不能仅解释为“逐包栈静态开销”。逐包引擎含真实CBFC/缓冲与控制面，行为级折叠了 byte buffer；两引擎 plane 映射也不一致。在统一输入、完成守恒和异常门禁通过前，这里是**交叉验证对照**，不是行为级绝对值校准。
- **packet** batch=16 同参数格平均：POP/RG=1.004×，Spray/RG=1.768×
- **packet** batch=256 同参数格平均：POP/RG=1.000×，Spray/RG=4.156×
- **behavioral** batch=16 同参数格平均：POP/RG=1.004×，Spray/RG=0.451×
- **behavioral** batch=64 同参数格平均：POP/RG=1.001×，Spray/RG=0.327×
- **behavioral** batch=128 同参数格平均：POP/RG=1.001×，Spray/RG=0.306×
- **behavioral** batch=256 同参数格平均：POP/RG=1.000×，Spray/RG=0.324×
- **behavioral** batch=512 同参数格平均：POP/RG=1.000×，Spray/RG=0.292×
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

