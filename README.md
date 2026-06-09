# dyn_latency — MoE dispatch/combine 动态时延优化上限仿真

事件级仿真，量化「1 分组交换机 + 16/64/128 端侧节点 + 200 Gbps + 多平面 P，
全程无损 CBFC」拓扑下 MoE EP dispatch/combine 的**网络动态时延**：incast 不可
优化下界、关键路径可优化上限、以及 SHMEM‑POP 相对该下界的 gap。

方法学对齐 `docs/SHMEM-POP技术分档.md` §1.12。完整分析见
**[`docs/MoE-dispatch-combine动态时延优化上限-仿真.md`](docs/MoE-dispatch-combine动态时延优化上限-仿真.md)**。

## 运行

```bash
pip install -r requirements.txt
python3 run.py
```

生成 `results/summary.json` 与 `decomp.png / sweep.png / perrank.png`。

## 核心结论

- **incast 串行是硬墙**（dispatch 受热点 rank 下行链路、combine 受其上行链路约束），占网络动态时延绝大部分，不可优化。
- **关键路径上可优化上限仅 ~4–8%**；SHMEM‑POP 把 makespan 做到距 incast 下界 **<1.1 µs（≈O(RTT)）**，吃掉 95–97%。
- **真正大块的可优化时延是基线的拥塞扩散**（无损 CBFC 下更毒）：冷 rank 被 CBFC 反压 + FIFO HOL 顶到 ~11×，SHMEM‑POP（VoQ 隔离 + ESC 信用配速）将其拉回 Oracle 水平。
- **多平面 floor∝1/P**（P=1→8: 371→47 µs），**单交换机 floor∝N**（N=16→128: 371→2572 µs）；SHMEM‑POP gap 恒为 ~0.84 µs。降 incast 硬墙靠加平面，调度负责清零硬墙之上的拥塞。

## 结构

| 文件 | 作用 |
|------|------|
| `dynlat/engine.py` | 离散事件内核 |
| `dynlat/fabric.py` | 链路/交换：输出排队、有限/无限缓存、无损反压、VoQ vs FIFO‑HOL、接收端信用、丢包重传 |
| `dynlat/workload.py` | MoE 路由抽样（热点）→ dispatch/combine 字节矩阵 |
| `dynlat/scenarios.py` | Oracle/Baseline/SHMEM‑POP 配置 + 解析 floor + runner |
| `run.py` | 扫描 ρ_h、出表/图、写 summary.json |
