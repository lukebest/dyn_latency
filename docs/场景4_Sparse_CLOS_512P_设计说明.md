---
number headings: auto, first-level 1, max 6, 1.1
---

# 1 场景4：Sparse CLOS（512P + 32×SW128）— 路由表设计说明

> **来源草稿**：[[场景4：Sparse CLOS 512P+32xSW.md]]  
> **原则**：以 **SW连接关系** 为物理真源；按纠正后的层次与 **无多路径** 转发规则生成 NPU/SW 转发表。  
> **修订**：2026-07-23（纠正：Cluster=各 Server 同号 NPU；转发无主备/ECMP）

---

# 2 约定与规模

## 2.1 层次（8 Cluster × 64 Server = 512 NPU）

```text
64 Server
  Server Sy:  8 张 NPU = NPU-C1Sy … NPU-C8Sy   （同机 FullMesh）
8 Cluster
  Cluster Ci: 64 张 NPU = NPU-CiS1 … NPU-CiS64
              = 所有 Server 上「编号为 i」的那张卡
NPU 总数 = 8 × 64 = 512
```

| 项 | 取值 | 说明 |
| --- | ---: | --- |
| 端口速率 | 400 Gbps | |
| Cluster | 8 | C=1..8；**每 Cluster 64 NPU**（无「Cluster 内若干 Server」子层） |
| Server | 64 | S=1..64；每 Server 8 NPU（分属 8 个 Cluster） |
| NPU | 512 | id = `NPU-CxSy`（无第三维 member） |
| SW | 32 | 每台 128×400G；两侧各接一 Cluster 的全部 64 NPU |

**与旧版错误对照**：不再使用「每 Cluster 8 Server × 每 Server 8 member」。`NPU-CxSy` 即唯一端点。

## 2.2 端口命名

| 记号 | 含义 |
| --- | --- |
| `PFMz` | 同 Server 上连向 `NPU-CzSy` 的直连口（z ≠ 本卡 Cluster），共 7 口 |
| `Pz` | 上联 SW 口，z=1..8，共 8 口 |
| `SW-a-b` | 连接 Cluster a 与 b 的交换机（跨 Cluster） |
| `SW-a-b-S` | 同边副交换机；**仅** 服务 a/b **Cluster 内**跨 Server |

每 NPU：**15×400G** = 7×PFM + 8×上联。

## 2.3 转发规则（唯一路径，无多路径）

| 优先级 | 条件 | 出端口 | SW |
| ---: | --- | --- | --- |
| 1 | 同 Server（Ss=Sd 且 Cs≠Cd） | `PFM{Cd}` | 无 |
| 2 | 同 Cluster（Cs=Cd 且 Ss≠Sd） | 内聚上联口（见内聚口表） | 对应 `SW-*-S` |
| 3 | 异 Cluster（Cs≠Cd；同 Server 已由规则 1 处理） | 连接表中 **非 `-S`** 的侧口 | **仅** `SW-a-b` |

- **禁止** ECMP / 主备：异 Cluster **永不** 走 `SW-a-b-S`。  
- 草稿原文 NPU 表中「多路径/备份」行 **作废**，以本规则为准。

| SW | 业务用途 |
| --- | --- |
| `SW-a-b` | **仅** a↔b 跨 Cluster |
| `SW-a-b-S` | **仅** Cluster a 内、Cluster b 内同侧转发；**不**承担 a↔b |

成对边 {1,2},{3,4},{5,6},{7,8} 各有一台 `-S` 专供两侧内聚；其余 24 条 Cluster 对仅 1 台 `SW-a-b`。校验：4×2+24=32。

---

# 3 SW 连接关系（物理真源）

每台 SW：Cluster a 侧 64 口 + Cluster b 侧 64 口 = 128。

| SW | Cluster a 侧 NPU 口 | Cluster b 侧 NPU 口 |
| --- | --- | --- |
| SW-1-2 | NPU-C1S*P1 | NPU-C2S*P1 |
| SW-1-2-S | NPU-C1S*P2 | NPU-C2S*P2 |
| SW-1-3 | NPU-C1S*P3 | NPU-C3S*P1 |
| SW-1-4 | NPU-C1S*P4 | NPU-C4S*P1 |
| SW-1-5 | NPU-C1S*P5 | NPU-C5S*P1 |
| SW-1-6 | NPU-C1S*P6 | NPU-C6S*P1 |
| SW-1-7 | NPU-C1S*P7 | NPU-C7S*P1 |
| SW-1-8 | NPU-C1S*P8 | NPU-C8S*P1 |
| SW-3-4 | NPU-C3S*P2 | NPU-C4S*P2 |
| SW-3-4-S | NPU-C3S*P3 | NPU-C4S*P3 |
| SW-2-3 | NPU-C2S*P3 | NPU-C3S*P4 |
| SW-2-4 | NPU-C2S*P4 | NPU-C4S*P4 |
| SW-2-5 | NPU-C2S*P5 | NPU-C5S*P2 |
| SW-2-6 | NPU-C2S*P6 | NPU-C6S*P2 |
| SW-2-7 | NPU-C2S*P7 | NPU-C7S*P2 |
| SW-2-8 | NPU-C2S*P8 | NPU-C8S*P2 |
| SW-5-6 | NPU-C5S*P3 | NPU-C6S*P3 |
| SW-5-6-S | NPU-C5S*P4 | NPU-C6S*P4 |
| SW-3-5 | NPU-C3S*P5 | NPU-C5S*P5 |
| SW-3-6 | NPU-C3S*P6 | NPU-C6S*P5 |
| SW-3-7 | NPU-C3S*P7 | NPU-C7S*P3 |
| SW-3-8 | NPU-C3S*P8 | NPU-C8S*P3 |
| SW-4-5 | NPU-C4S*P5 | NPU-C5S*P6 |
| SW-4-6 | NPU-C4S*P6 | NPU-C6S*P6 |
| SW-4-7 | NPU-C4S*P7 | NPU-C7S*P4 |
| SW-4-8 | NPU-C4S*P8 | NPU-C8S*P4 |
| SW-7-8 | NPU-C7S*P5 | NPU-C8S*P5 |
| SW-7-8-S | NPU-C7S*P6 | NPU-C8S*P6 |
| SW-5-7 | NPU-C5S*P7 | NPU-C7S*P7 |
| SW-5-8 | NPU-C5S*P8 | NPU-C8S*P7 |
| SW-6-7 | NPU-C6S*P7 | NPU-C7S*P8 |
| SW-6-8 | NPU-C6S*P8 | NPU-C8S*P8 |

**校验**：每个 Cluster 的 P1…P8 在上表中各出现恰好一次。

---

# 4 NPU 转发表

## 4.1 生成规则

```text
Route(src=CxSy, dst=CdSd):
  if Sy == Sd and Cx != Cd:  return PFM[Cd]              # 同机直连
  if Cx == Cd and Sy != Sd:  return (P_intra[Cx], SW_S) # 同 Cluster 内聚
  if Cx != Cd:               return cross[(Cx,Cd)]      # 唯一 SW-a-b
```

## 4.2 各 Cluster 内聚口（同 Cluster、异 Server）

| Cluster | 出端口 | SW（`-S`） |
| ---: | --- | --- |
| 1 | P2 | SW-1-2-S |
| 2 | P2 | SW-1-2-S |
| 3 | P3 | SW-3-4-S |
| 4 | P3 | SW-3-4-S |
| 5 | P4 | SW-5-6-S |
| 6 | P4 | SW-5-6-S |
| 7 | P6 | SW-7-8-S |
| 8 | P6 | SW-7-8-S |

## 4.3 按源 Cluster 的 NPU 路由规则表

通配：`NPU-CxS*` = Cluster x 上任意 Server。出端口只依赖目的 Cluster / 是否同 Server。

### 4.3.1 源 = NPU-C1S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠1 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C1S* | Sd≠Ss | P2 | SW-1-2-S | 同 Cluster 跨 Server |
| NPU-C2S* | Cd=2（且异 Server） | P1 | SW-1-2 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P3 | SW-1-3 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P4 | SW-1-4 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P5 | SW-1-5 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P6 | SW-1-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-1-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-1-8 | 跨 Cluster（唯一路径） |

### 4.3.2 源 = NPU-C2S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠2 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C2S* | Sd≠Ss | P2 | SW-1-2-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-2 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P3 | SW-2-3 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P4 | SW-2-4 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P5 | SW-2-5 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P6 | SW-2-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-2-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-2-8 | 跨 Cluster（唯一路径） |

### 4.3.3 源 = NPU-C3S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠3 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C3S* | Sd≠Ss | P3 | SW-3-4-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-3 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P4 | SW-2-3 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P2 | SW-3-4 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P5 | SW-3-5 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P6 | SW-3-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-3-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-3-8 | 跨 Cluster（唯一路径） |

### 4.3.4 源 = NPU-C4S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠4 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C4S* | Sd≠Ss | P3 | SW-3-4-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-4 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P4 | SW-2-4 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P2 | SW-3-4 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P5 | SW-4-5 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P6 | SW-4-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-4-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-4-8 | 跨 Cluster（唯一路径） |

### 4.3.5 源 = NPU-C5S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠5 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C5S* | Sd≠Ss | P4 | SW-5-6-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-5 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P2 | SW-2-5 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P5 | SW-3-5 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P6 | SW-4-5 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P3 | SW-5-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-5-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-5-8 | 跨 Cluster（唯一路径） |

### 4.3.6 源 = NPU-C6S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠6 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C6S* | Sd≠Ss | P4 | SW-5-6-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-6 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P2 | SW-2-6 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P5 | SW-3-6 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P6 | SW-4-6 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P3 | SW-5-6 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P7 | SW-6-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P8 | SW-6-8 | 跨 Cluster（唯一路径） |

### 4.3.7 源 = NPU-C7S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠7 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C7S* | Sd≠Ss | P6 | SW-7-8-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-7 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P2 | SW-2-7 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P3 | SW-3-7 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P4 | SW-4-7 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P7 | SW-5-7 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P8 | SW-6-7 | 跨 Cluster（唯一路径） |
| NPU-C8S* | Cd=8（且异 Server） | P5 | SW-7-8 | 跨 Cluster（唯一路径） |

### 4.3.8 源 = NPU-C8S*

| 目的 | 条件 | 出端口 | SW | 说明 |
| --- | --- | --- | --- | --- |
| NPU-C*S*（同 Server） | Sd=Ss 且 Cd≠8 | PFM{Cd} | 无 | 同机 FullMesh |
| NPU-C8S* | Sd≠Ss | P6 | SW-7-8-S | 同 Cluster 跨 Server |
| NPU-C1S* | Cd=1（且异 Server） | P1 | SW-1-8 | 跨 Cluster（唯一路径） |
| NPU-C2S* | Cd=2（且异 Server） | P2 | SW-2-8 | 跨 Cluster（唯一路径） |
| NPU-C3S* | Cd=3（且异 Server） | P3 | SW-3-8 | 跨 Cluster（唯一路径） |
| NPU-C4S* | Cd=4（且异 Server） | P4 | SW-4-8 | 跨 Cluster（唯一路径） |
| NPU-C5S* | Cd=5（且异 Server） | P7 | SW-5-8 | 跨 Cluster（唯一路径） |
| NPU-C6S* | Cd=6（且异 Server） | P8 | SW-6-8 | 跨 Cluster（唯一路径） |
| NPU-C7S* | Cd=7（且异 Server） | P5 | SW-7-8 | 跨 Cluster（唯一路径） |

## 4.4 跨 Cluster 唯一路径一览

| 源→目的 | 出端口 | SW |
| --- | --- | --- |
| C1→C2 | P1 | SW-1-2 |
| C1→C3 | P3 | SW-1-3 |
| C1→C4 | P4 | SW-1-4 |
| C1→C5 | P5 | SW-1-5 |
| C1→C6 | P6 | SW-1-6 |
| C1→C7 | P7 | SW-1-7 |
| C1→C8 | P8 | SW-1-8 |
| C2→C1 | P1 | SW-1-2 |
| C2→C3 | P3 | SW-2-3 |
| C2→C4 | P4 | SW-2-4 |
| C2→C5 | P5 | SW-2-5 |
| C2→C6 | P6 | SW-2-6 |
| C2→C7 | P7 | SW-2-7 |
| C2→C8 | P8 | SW-2-8 |
| C3→C1 | P1 | SW-1-3 |
| C3→C2 | P4 | SW-2-3 |
| C3→C4 | P2 | SW-3-4 |
| C3→C5 | P5 | SW-3-5 |
| C3→C6 | P6 | SW-3-6 |
| C3→C7 | P7 | SW-3-7 |
| C3→C8 | P8 | SW-3-8 |
| C4→C1 | P1 | SW-1-4 |
| C4→C2 | P4 | SW-2-4 |
| C4→C3 | P2 | SW-3-4 |
| C4→C5 | P5 | SW-4-5 |
| C4→C6 | P6 | SW-4-6 |
| C4→C7 | P7 | SW-4-7 |
| C4→C8 | P8 | SW-4-8 |
| C5→C1 | P1 | SW-1-5 |
| C5→C2 | P2 | SW-2-5 |
| C5→C3 | P5 | SW-3-5 |
| C5→C4 | P6 | SW-4-5 |
| C5→C6 | P3 | SW-5-6 |
| C5→C7 | P7 | SW-5-7 |
| C5→C8 | P8 | SW-5-8 |
| C6→C1 | P1 | SW-1-6 |
| C6→C2 | P2 | SW-2-6 |
| C6→C3 | P5 | SW-3-6 |
| C6→C4 | P6 | SW-4-6 |
| C6→C5 | P3 | SW-5-6 |
| C6→C7 | P7 | SW-6-7 |
| C6→C8 | P8 | SW-6-8 |
| C7→C1 | P1 | SW-1-7 |
| C7→C2 | P2 | SW-2-7 |
| C7→C3 | P3 | SW-3-7 |
| C7→C4 | P4 | SW-4-7 |
| C7→C5 | P7 | SW-5-7 |
| C7→C6 | P8 | SW-6-7 |
| C7→C8 | P5 | SW-7-8 |
| C8→C1 | P1 | SW-1-8 |
| C8→C2 | P2 | SW-2-8 |
| C8→C3 | P3 | SW-3-8 |
| C8→C4 | P4 | SW-4-8 |
| C8→C5 | P7 | SW-5-8 |
| C8→C6 | P8 | SW-6-8 |
| C8→C7 | P5 | SW-7-8 |

---

# 5 SW 转发表

## 5.1 生成规则

1. **邻接**：Cluster a 的 `NPU-CaS1..S64` + Cluster b 的 `NPU-CbS1..S64`。  
2. **本地端口编号**（仿真约定）：  
   - 口 `0..63`：`NPU-CaSy` → `port = S-1`（S=1..64）  
   - 口 `64..127`：`NPU-CbSy` → `port = 64 + (S-1)`  
3. **FIB**：目的 ∈ 邻接 → 出端口 = 接入口；否则不可达。  
4. **业务允许的转发**：  
   - **非 `-S`（`SW-a-b`）**：仅跨侧 a↔b。  
   - **`-S`**：仅同侧 a→a、b→b（内聚）；**不做** a↔b。

```text
port_of(sw, NPU-CxSy):
  if x == sw.a: return Sy - 1
  if x == sw.b: return 64 + (Sy - 1)
  else: unreachable
```

## 5.2 32 台 SW 一览

| SW | Cluster a | a 侧上联 | Cluster b | b 侧上联 | 类型 | 业务转发 |
| --- | ---: | --- | ---: | --- | --- | --- |
| SW-1-2 | 1 | P1 | 2 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-2-S | 1 | P2 | 2 | P2 | 副 SW（`-S`） | 仅 a 内 + b 内（同侧） |
| SW-1-3 | 1 | P3 | 3 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-4 | 1 | P4 | 4 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-5 | 1 | P5 | 5 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-6 | 1 | P6 | 6 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-7 | 1 | P7 | 7 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-1-8 | 1 | P8 | 8 | P1 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-3-4 | 3 | P2 | 4 | P2 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-3-4-S | 3 | P3 | 4 | P3 | 副 SW（`-S`） | 仅 a 内 + b 内（同侧） |
| SW-2-3 | 2 | P3 | 3 | P4 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-2-4 | 2 | P4 | 4 | P4 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-2-5 | 2 | P5 | 5 | P2 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-2-6 | 2 | P6 | 6 | P2 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-2-7 | 2 | P7 | 7 | P2 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-2-8 | 2 | P8 | 8 | P2 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-5-6 | 5 | P3 | 6 | P3 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-5-6-S | 5 | P4 | 6 | P4 | 副 SW（`-S`） | 仅 a 内 + b 内（同侧） |
| SW-3-5 | 3 | P5 | 5 | P5 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-3-6 | 3 | P6 | 6 | P5 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-3-7 | 3 | P7 | 7 | P3 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-3-8 | 3 | P8 | 8 | P3 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-4-5 | 4 | P5 | 5 | P6 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-4-6 | 4 | P6 | 6 | P6 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-4-7 | 4 | P7 | 7 | P4 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-4-8 | 4 | P8 | 8 | P4 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-7-8 | 7 | P5 | 8 | P5 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-7-8-S | 7 | P6 | 8 | P6 | 副 SW（`-S`） | 仅 a 内 + b 内（同侧） |
| SW-5-7 | 5 | P7 | 7 | P7 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-5-8 | 5 | P8 | 8 | P7 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-6-7 | 6 | P7 | 7 | P8 | 主/唯一 SW | 仅 a↔b（跨侧） |
| SW-6-8 | 6 | P8 | 8 | P8 | 主/唯一 SW | 仅 a↔b（跨侧） |

## 5.3 实例：SW-1-2（跨 Cluster C1↔C2）

- 邻接：全部 `NPU-C1S*`（口 0..63）+ 全部 `NPU-C2S*`（口 64..127）。  
- 上联：C1 各 NPU 的 **P1**；C2 各 NPU 的 **P1**。  
- 业务：仅 C1↔C2；同侧目的不应经本 SW（由 NPU 路由保证）。

| 目的 | 出端口 |
| --- | ---: |
| NPU-C1S1 | 0 |
| NPU-C1S64 | 63 |
| NPU-C2S1 | 64 |
| NPU-C2S64 | 127 |
| 其它 Cluster | 不可达 |

例：`NPU-C1S10` 经 P1 入 SW-1-2 → 目的 `NPU-C2S30` → 出端口 `64+29=93`。

## 5.4 实例：SW-1-2-S（C1 / C2 内聚）

- 邻接与端口编号 **同 SW-1-2**。  
- 上联：C1/C2 各 NPU 的 **P2**。  
- 业务：**仅** 同侧内聚（C1→C1、C2→C2）；**不** 做 C1↔C2。

| 入侧 | 目的 | 业务合法 |
| --- | --- | --- |
| C1 | C1 其它 Server | 是 |
| C2 | C2 其它 Server | 是 |
| C1 | C2 | **否**（异 Cluster 应走 SW-1-2） |
| C2 | C1 | **否** |

例：`NPU-C1S10` 经 P2 入 SW-1-2-S → 目的 `NPU-C1S40` → 出端口 `39`（同侧 hairpin）。

## 5.5 其余 SW

对一览表每行套用同一 `port_of`；`-S` 行只开同侧业务，非 `-S` 行只开跨侧业务。全量 32×128=4096 项可由规则生成。

---

# 6 端到端路径小结

| 流量类 | NPU 出端口 | SW |
| --- | --- | --- |
| 同 Server、异 Cluster | `PFM{Cd}` | 无 |
| 同 Cluster、异 Server | 内聚 `Pz` | `SW-*-S`（同侧） |
| 异 Cluster、异 Server | 唯一 `Pz` | `SW-a-b`（跨侧） |

---

# 7 附录：校验结论

| 检查项 | 结果 |
| --- | --- |
| 规模 8×64=512 | 通过 |
| SW=32；每 Cluster P1..P8 唯一 | 通过 |
| 每对异 Cluster 恰 1 条非 `-S` 路径 | 通过 |
| 每 Cluster 恰 1 个内聚 `-S` 口 | 通过 |
| 无多路径 / 异 Cluster 不走 `-S` | 通过（生成约束） |

原稿未改：[[场景4：Sparse CLOS 512P+32xSW.md]]。
