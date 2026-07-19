---
number headings: auto, first-level 1, max 6, 1.1
---

# 1 组网方案

*基本假设*

- 所有端口400Gbps（50GB/s）

*场景1： 单层CLOS组网(128 NPU + 8 × SW128)*

- NPU：8x400G
- SW
  - 8台
  - 每台：128 * 400G= 51.2T

*场景2：两层CLOS组网(1024 NPU + 128 Leaf + 64 Spine，ub_request_grant中的组网)*

- NPU：
  - 8x400G
  - 64台NPU连一个Leaf SW， 一共16组
  - 总共8平面
- Leaf SW：
  - 128 * 400G=51.2T
  - 每台LeafSW：每台 64 口接 NPU、64 口接 Spine
  - 16组 * 8平面 = 128 leaf SW
- Spine SW:
  - 128 * 400G = 51.2T
  - 8平面
  - 每平面：Spine SW连同平面的128台交换机

场景3：两层CLOS多平面组网（1024 NPU + 128 Leaf + 64 Spine， 组成8个独立平面）

- NPU：
  - 8x400G，每个400G连对应平面的LeafSW， 总共8平面
  - 64台NPU连一个Leaf SW， 一共16组
- Leaf SW：
  - 编号规则：LeafSW_N_M, N代表平面，M代表平面内的编号
  - 128 * 400G=51.2T
  - 每台LeafSW：每台 64 口接 同平面的NPU端口、64 口接同平面的Spine
  - 同平面的Leaf SW 和 Spine SW之间连接数量为8*400G
  - 每台交换机归属于8个平面中的一个
  - 每平面1024/64=16台leaf SW
  - 16组 * 8平面 = 128 leaf SW
- Spine SW:
  - 128 * 400G = 51.2T
  - 每台Spine SW：连接同平面的Leaf
  - 每平面：Spine SW连同平面的128台交换机



# 2 网络方案



## 2.1 分组Packet Spray（源NPU 链路级PS+ Up LeafSW 链路级PS）

路由规则：

- 源NPU：N个400G端口散射



## 2.2 UB_RG

见 [ub_request_grant.md](./ub_request_grant.md) 中方案

# 3 网络有界时延分析



## 3.1 现在Scale-up网络中P99时延的构成

P99时延 = 静态时延 + 排队时延 + Req-Gnt RTT时延

- 排队时延：Incast导致的排队，负载均衡不均导致的，端侧或交换机头阻（流控头阻 或拥塞控制限速）
  - Incast产生的无法解决
  - 负载均衡不均和头阻导致的可以解决
  - 流控和拥塞控制的可以解决
- 静态时延：
  - Barrier同步时延
- Non-conserving调度引入的时延
  - TDM调度会额外引入带宽的浪费
  - 控制面的带宽开销



# 4 实验设计



## 4.1 专家倾斜度模型

```python
import numpy as np
import matplotlib.pyplot as plt

def simulate_moe_ep_zipf(num_tokens=100000, num_experts=64, zipf_s=1.2, top_k=1):
    """
    使用 Zipf 模型模拟多 XPU 专家并行 (EP) 下的 Token 分配与发送
    
    参数:
    - num_tokens: 总共要处理和发送的 Token 数量
    - num_experts: 全局总专家数（对应切分在不同的 XPU 上）
    - zipf_s: Zipf 倾斜指数 (s 越大，热点越集中；s=0 退化为绝对均匀分布)
    - top_k: 每个 Token 选择的专家数量 (通常为 1 或 2)
    """
    print(f"=== 开始模拟 MoE 专家并行 Token 发送 ===")
    print(f"总 Token 数: {num_tokens} | 总专家数: {num_experts} | Zipf 指数 s: {zipf_s} | Top-{top_k} 路由\n")

    # 1. 构建广义 Zipf 分布的概率权重
    ranks = np.arange(1, num_experts + 1)
    weights = 1.0 / (ranks ** zipf_s)
    probabilities = weights / np.sum(weights)  # 归一化，使概率和为 1

    # 2. 模拟 Router（门控网络）为每个 Token 分配专家
    # 每个专家编号为 0 到 num_experts-1，其被选中的概率服从 Zipf 分布
    expert_ids = np.arange(num_experts)
    
    # 模拟发送：每个 Token 独立随机抽取 top_k 个不重复的专家
    allocated_tokens = []
    for _ in range(num_tokens):
        # 抽取 top_k 个专家（不允许重复）
        chosen_experts = np.random.choice(expert_ids, size=top_k, replace=False, p=probabilities)
        allocated_tokens.extend(chosen_experts)

    # 3. 统计每个专家实际接收到的 Token 数量（即 XPU 的计算负载）
    expert_loads = np.zeros(num_experts, dtype=int)
    for exp_id in allocated_tokens:
        expert_loads[exp_id] += 1

    # 4. 分析负载不均衡指标
    max_load = np.max(expert_loads)
    min_load = np.min(expert_loads)
    avg_load = np.mean(expert_loads)
    std_dev = np.std(expert_loads)
    
    # 负载不均衡度 (Imbalance Ratio): 最大负载 / 平均负载
    imbalance_ratio = max_load / avg_load if avg_load > 0 else 0

    print(f"--- 统计结果 ---")
    print(f"Top-1 超级热点专家 (ID: {np.argmax(expert_loads)}) 接收 Token 数: {max_load} (占比 {max_load/len(allocated_tokens)*100:.2f}%)")
    print(f"最冷门尾部专家 (ID: {np.argmin(expert_loads)}) 接收 Token 数: {min_load} (占比 {min_load/len(allocated_tokens)*100:.2f}%)")
    print(f"理想状态下平均每专家负载: {avg_load:.1f}")
    print(f"标准差 (各专家负载波动程度): {std_dev:.2f}")
    print(f"负载不均衡度 (Max / Avg): {imbalance_ratio:.2f}x")
    
    if imbalance_ratio > 1.5:
        print("⚠️ 警告：检测到严重的分布式热点倾斜！这将引发 All-to-All 通信时延崩塌与木桶效应。")

    return ranks, expert_loads, imbalance_ratio
’‘’
# 5 执行模拟
# 6 设定 10 万个 Token，64 个专家，倾斜指数 s=1.1 (符合自然语言长尾特征)，Top-1 路由
ranks, loads, ratio = simulate_moe_ep_zipf(num_tokens=100000, num_experts=64, zipf_s=1.1, top_k=1)
```



## 4.2 网络级仿真



### 4.2.1 实验1：倾斜专家流量下的Dispatch

实验目的：

- 模拟LLM中的EP通讯中的Dispatch通讯过程

*实验可配置参数* 


| 组网场景               | 场景1、场景2、场景3                  |
| ------------------ | ---------------------------- |
| NPU同步启动Dispatch    | 是                            |
| TopK               | 8                            |
| Token报文大小          | 7KB                          |
| Token报文是否切成更小的报文发送 | 否                            |
| BatchSize          | 16，64， 256， 1024， 4096       |
| 专家倾斜度模型            | Zipf模型                       |
| 专家倾斜度              | S=0, 0.1, 0.3, 0.5, 0.7, 0.9 |


观测与预期现象：

1. SW下行链路头阻导致的吞吐降低，观测指标：吞吐， 热点专家时延、非热点专家时延
2. 热点专家对于非热点专家的时延阻塞：观测对象dispatch-combine的时延
3. CCT完成时间

*仿真入口*：`ns-3-ub/scratch/ub_rg-dispatch-experiment.cc`（`UbRgDrawZipfDispatch` + 全 NPU 同步 `Start`）。默认 `G = tokenBytes = 7168`（7KB=1 grain）；专家与 NPU 1:1；`--scheme=ub_rg|ub_unscheduled`。Combine / dispatch–combine 时延见 §4.2.2。

### 4.2.2 实验2：倾斜专家流量下的Combine

类似实验1，但是为反方向

### 4.2.3 实验3：不同EP大小的combine-dispatch 时延的时延累积分布函数和概率密度函数

实验目的：

- 观测不同组网场景，不同网络方案 2.1, 2.2下，不同EP大小的cdf与pdf；

*实验可配置参数* 


| 组网场景                    | 场景1、场景2、场景3                         |
| ----------------------- | ----------------------------------- |
| NPU同步启动Dispatch-combine | 是                                   |
| EP大小                    | 场景1覆盖：32，64，128；场景2/3覆盖256，512，1024 |
| TopK                    | 8                                   |
| Token报文大小               | 7KB                                 |
| Token报文是否切成更小的报文发送      | 否                                   |
| BatchSize               | 16，64， 256， 1024， 4096              |
| 专家倾斜度模型                 | Zipf模型                              |
| 专家倾斜度                   | S=0, 0.1, 0.3, 0.5, 0.7, 0.9        |


观测与预期现象：

1. SW下行链路头阻导致的吞吐降低，观测指标：吞吐， 热点专家时延、非热点专家时延
2. 热点专家对于非热点专家的时延阻塞：观测对象dispatch-combine的时延
3. CCT完成时间



# 5 下一步计划（暂不实现）

- 基准方案的优化
  - 分组Packet Spray（源NPU 路径级PS）
- UB_RG方案优化：
  - UB_RG方案优化
  - UB_RG_NWPOP
  - UB_RG_SHMEMPOP
- 仿真场景丰富
  - 非对称网络场景下的效果
  - 网络实验：
    - 补充AFD M2N/N2M
  - 系统时延:
    - 多层模型
      - 不掩盖模型
      - Wide EP通算掩盖模型
      - AFD模型
- 系统模型与性能指标
  - 系统级支持
  - Straggler NPU效果
  - 更丰富的模型部署（N-bacth-overlap等）
- 其他目标优化
  - SW的突发大小与缓存容量

