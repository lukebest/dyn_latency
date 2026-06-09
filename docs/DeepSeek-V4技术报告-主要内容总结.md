# DeepSeek-V4 技术报告主要内容总结

> **来源**：[DeepSeek_V4.pdf](./DeepSeek_V4.pdf) — *DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence*  
> **整理目的**：提炼架构、训练、推理与评测要点，供后续互联/仿真工作引用。

---

## 1. 概述

DeepSeek-V4 系列是面向 **百万 token 超长上下文** 的高效 MoE 大语言模型预览版，包含两个主力型号：

| 型号 | 总参数量 | 每 token 激活参数 | 上下文长度 |
|------|----------|-------------------|------------|
| **DeepSeek-V4-Pro** | 1.6T | 49B | 1M |
| **DeepSeek-V4-Flash** | 284B | 13B | 1M |

核心定位：在保持/提升能力的同时，**大幅降低长上下文场景下的推理 FLOPs 与 KV Cache 占用**，使百万级上下文成为可常规部署的能力，并为 test-time scaling、长程 Agent 任务提供基础。

相对 DeepSeek-V3.2，在 **1M token** 场景下（图 1 数据）：

- **V4-Pro**：单 token 推理 FLOPs 约为 V3.2 的 **27%**，KV Cache 约为 **10%**
- **V4-Flash**：单 token FLOPs 约为 **10%**，KV Cache 约为 **7%**

预训练规模：V4-Flash **32T** tokens，V4-Pro **33T** tokens；两者均可原生高效支持 1M 长度上下文。

---

## 2. 架构创新（相对 V3）

整体仍基于 Transformer + MTP（Multi-Token Prediction），在 V3 基础上引入三大升级（图 2）：

1. **混合注意力**：CSA（Compressed Sparse Attention）+ HCA（Heavily Compressed Attention）交错使用  
2. **mHC**（Manifold-Constrained Hyper-Connections）：增强残差连接稳定性  
3. **Muon 优化器**：更快收敛、更稳训练  

MoE 部分沿用 **DeepSeekMoE** 范式，MTP 配置与 V3 一致。

### 2.1 继承自 V3 的设计

**DeepSeekMoE**

- 细粒度 routed experts + shared expert  
- 亲和度函数由 `Sigmoid` 改为 **`Sqrt(Softplus)`**  
- 负载均衡：无辅助损失策略 + 轻微 **sequence-wise balance loss**  
- 取消 routing target nodes 数量约束，重设计并行策略  
- 前若干层 dense FFN 替换为 **Hash routing MoE**（按 token ID 哈希选专家）  

**MTP**

- 与 V3 相同，深度为 1  

### 2.2 mHC（流形约束超连接）

- 将残差流宽度扩展为 \(n_{hc} \times d\)（\(n_{hc}=4\)）  
- 核心约束：残差映射矩阵 \(B_l\) 落在 **双随机矩阵流形**（Birkhoff polytope）上，保证谱范数 \(\le 1\)，前向/反向数值稳定  
- 输入/输出映射 \(A_l, C_l\) 经 Sigmoid 约束为非负有界  
- 参数动态生成：输入相关分量 + 静态分量；\(B_l\) 通过 **Sinkhorn-Knopp** 迭代（\(t_{max}=20\)）投影到流形  

### 2.3 混合注意力：CSA + HCA

长上下文下 attention 是主要瓶颈。V4 设计两种压缩注意力并 **交错配置**：

| 机制 | 压缩率 | 注意力方式 | 作用 |
|------|--------|------------|------|
| **CSA** | 每 \(m\) 个 token → 1 条 KV（\(m=4\)） | 先压缩，再 **DSA 稀疏 top-k**（Pro: k=1024，Flash: k=512） | 压缩 + 稀疏，兼顾效率与精度 |
| **HCA** | 每 \(m'\) 个 token → 1 条 KV（\(m'=128\)） | **稠密** attention on 压缩 KV | 极端压缩，进一步降 FLOPs/KV |

**共同技术细节**

- Query/KV 在 core attention 前做 **RMSNorm**，抑制 attention logit 爆炸  
- **部分 RoPE**（末 64 维）+ 对 core attention 输出做反向 RoPE，保持相对位置语义  
- 附加 **Sliding Window Attention** 分支（窗口 \(n_{win}=128\)），弥补块内因果性限制、增强局部依赖  
- **Attention Sink**：可学习 sink logit，允许每头总注意力不必归一化为 1  
- KV 存储：**RoPE 维 BF16 + 其余 FP8**；lightning indexer 用 **FP4** 计算  

**效率结论**（§2.3.4）：1M 上下文下，KV Cache 可降至 BF16 GQA8 基线的约 **2%**。

### 2.4 Muon 优化器

- 除 embedding、prediction head、mHC 静态偏置/门控、RMSNorm 权重外，**其余模块用 Muon**  
- **Hybrid Newton-Schulz**：10 步正交化（前 8 步快速收敛，后 2 步稳定奇异值至 1）  
- 因 attention 已对 Q/KV 做 RMSNorm，**不使用 QK-Clip**  

---

## 3. 模型配置（预训练）

### 3.1 DeepSeek-V4-Pro

| 项 | 值 |
|----|-----|
| Transformer 层数 | 61 |
| Hidden \(d\) | 7168 |
| 前 2 层 | 纯 HCA |
| 后续层 | CSA / HCA 交错 |
| Query heads \(n_h\) | 128，head dim \(c=512\)，\(d_c=1536\) |
| Output groups \(g\) | 16，\(d_g=1024\) |
| MoE | 全层 MoE；**前 3 层 Hash routing** |
| Experts | 1 shared + **384 routed**，每 token 激活 **6** |
| Expert 中间维 | 3072 |
| mHC \(n_{hc}\) | 4 |

### 3.2 DeepSeek-V4-Flash

| 项 | 值 |
|----|-----|
| Transformer 层数 | 43 |
| Hidden \(d\) | 4096 |
| 前 2 层 | 纯 Sliding Window Attention |
| 后续层 | CSA / HCA 交错 |
| Query heads | 64，\(c=512\)，\(d_c=1024\) |
| MoE | 1 shared + **256 routed**，top-6 |
| Expert 中间维 | 2048 |

### 3.3 训练要点

- 序列长度渐进：4K → 16K → 64K → **1M**  
- 前 1T tokens **dense attention** warmup，64K 起引入稀疏 attention  
- 最大 batch：Flash 75.5M tokens，Pro 94.4M tokens  
- **稳定性技巧**：  
  - **Anticipatory Routing**：路由索引用历史参数 \(\theta_{t-\Delta t}\) 计算，打破路由-主干恶性循环；与 EP 通信流水线重叠，额外墙钟开销约 **20%**  
  - **SwiGLU Clamping**：linear 分量 \([-10,10]\)，gate 上界 10  

---

## 4. 基础设施亮点

### 4.1 MoE 专家并行（EP）

- **细粒度通信-计算重叠**：将专家切分为 **wave**，在单个融合 mega-kernel 中流水线执行（详见 [`DeepSeek-V4-MoE通信完整流程.md`](./DeepSeek-V4-MoE通信完整流程.md)）  
- 开源实现：**MegaMoE2**（DeepGEMM 组件）  
- 推理加速：相对非融合基线 **1.50–1.73×**；RL rollout 等延迟敏感场景最高 **1.96×**  

### 4.2 TileLang 内核开发

- 用 DSL 融合数百个细粒度 ATen 算子  
- **Host Codegen**：将校验/封送移出 Python，单次调用开销降至 **<1 μs**  
- 集成 **Z3 SMT** 做整数分析，支撑向量化、屏障插入等优化  
- 默认禁用 fast-math，支持 IEEE 合规与 **bitwise 可复现**  

### 4.3 批不变与确定性内核

- **Attention**：双 kernel 策略（整序列单 SM + 尾 wave 多 SM），避免 split-KV 破坏 batch invariance  
- **MoE backward**：单 rank 内 token 顺序预处理 + 跨 rank buffer 隔离，保证 EP 发送与累加顺序确定  
- 矩阵乘全面使用 **DeepGEMM**，多数场景放弃 split-k  

### 4.4 FP4 量化感知训练（QAT）

- 后训练阶段对 **MoE expert 权重** 与 **indexer QK 路径** 做 QAT  
- Routed expert 权重以 FP4 部署；当前硬件上 FP4×FP8 峰值 FLOPs 与 FP8×FP8 相同，未来硬件理论可再快 **1/3**  

### 4.5 训练框架

- **Muon + 混合 ZeRO**：按矩阵形状分桶，MoE 专家独立优化、BF16 梯度同步减半通信量  
- **mHC 工程化**：融合 kernel + 选择性重计算 + DualPipe 1F1B 调整，墙钟开销约 **6.7%**  
- **Contextual Parallelism**：两阶段通信解决 CSA/HCA 在 CP 下的边界压缩与变长问题  
- **张量级 activation checkpointing**：TorchFX 追踪最小重计算子图  

### 4.6 推理框架

- **异构 KV Cache 布局**（图 6）：  
  - **Classical KV Cache**：CSA/HCA 压缩块（块大小为 \(\mathrm{lcm}(m, m')\) 的倍数）  
  - **State Cache**：SWA + 尚未凑满压缩块的 tail token  
- **磁盘 KV Cache**：支持共享前缀复用；CSA/HCA 存压缩 KV；SWA 提供 Full / Periodic Checkpoint / Zero 三档策略  

---

## 5. 后训练（Post-Training）

范式：**领域专家独立训练 → On-Policy Distillation（OPD）统一融合**（替代 V3.2 的混合 RL 阶段）。

### 5.1 专家训练（Specialist）

- 各域（数学、代码、Agent、指令跟随等）：SFT → **GRPO** RL  
- **三种推理力度**：Non-think / Think High / Think Max（不同长度惩罚与上下文窗口）  
- **生成式奖励模型（GRM）**：Actor 兼作评判器，联合优化生成与评分能力  
- 工具调用：`|DSML|` + XML schema；**Interleaved Thinking** 在 1M 上下文下跨多轮保留推理轨迹  

### 5.2 OPD 与 RL 基础设施

- FP4 QAT 集成、全词表 OPD 的高效 teacher 调度  
- 可抢占、容错的 rollout 服务  
- 百万 token 上下文 RL 框架扩展  
- Agent 沙箱基础设施  

---

## 6. 评测摘要

### 6.1 Base 模型（表 1）

- **V4-Flash-Base**：参数量小于 V3.2-Base，却在多数 benchmark 上反超，长上下文优势尤其明显  
- **V4-Pro-Base**：在知识、推理、代码、长上下文等维度全面领先系列前代  

### 6.2 最终模型（V4-Pro-Max / V4-Flash-Max）

| 维度 | 结论 |
|------|------|
| **知识** | V4-Pro-Max 在 SimpleQA、中文 SimpleQA 等领先开源模型；教育类 benchmark 略优；与 Gemini-3.1-Pro 仍有差距 |
| **推理** | 扩展 reasoning tokens 后优于 GPT-5.2、Gemini-3.0-Pro；略逊于 GPT-5.4、Gemini-3.1-Pro（约 3–6 个月差距） |
| **Agent** | 公开 benchmark 与 Kimi-K2.6、GLM-5.1 相当；内部评测接近 Claude Opus 4.5 |
| **长上下文** | 1M 窗口在合成与真实任务上表现强劲，部分学术 benchmark 超过 Gemini-3.1-Pro |

图 1 左：V4-Pro-Max 在 HLE、Apex、Codeforces、SWE、Terminal Bench、Toolathlon 等上与闭源/开源旗舰对比。

---

## 7. 对互联与系统仿真的启示（简表）

| 主题 | 报告要点 | 与本仓库关联 |
|------|----------|--------------|
| MoE EP 流量 | Dispatch FP8 + Combine BF16；每 token-expert 约 **3h 字节** | 见 MoE 流程专文；[`SHMEM-POP技术分档.md`](./SHMEM-POP技术分档.md) §1.12 |
| 计算/通信比 | \(C/B \le 2d = 6144\) FLOPs/Byte（Pro） | 带宽足够时通信可被计算掩盖 |
| Wave 调度 | 专家分 wave 流水线，利于小 batch / RL tail | 仿真可用 \(\tau_{wave}\) 黑盒建模 |
| Pull 语义 | GPU 主动从远端 **pull** 读 token 数据 | 与 SHMEM-POP Pull-on-notify 语义一致 |
| 热点专家 | 路由偏斜导致 M2N incast | 仿真需 Zipf/显式热点模型 |

---

## 8. 参考文献与资源

- 模型权重：[Hugging Face — deepseek-v4 collection](https://huggingface.co/collections/deepseek-ai/deepseek-v4)  
- 推理实现参考：[DeepSeek-V4-Pro inference](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/tree/main/inference)  
- MegaMoE2：[DeepGEMM PR #304](https://github.com/deepseek-ai/DeepGEMM/pull/304)  

---

*文档版本：基于技术报告 preview 版整理。*
