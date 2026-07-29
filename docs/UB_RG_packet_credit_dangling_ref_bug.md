# UB_RG 逐包仿真：Credit 归账悬挂引用 Bug

## 现象

Packet 引擎、场景 1（S1）、`ub_rg`、batch=16、zipf=0、nsk=0：

| 指标 | 观察值 |
|---|---|
| 完成 token | **4192 / 16384**（约 1/4） |
| GLOBAL SYNC | **0 / 128** |
| 上报 step | ≈ **353.5 µs**（watchdog 半截收尾，非健康 CCT） |
| 对照行为级 | ≈ **8.3 µs**（全量完成） |

管道在约一个 credit 窗口轮次后停死，不是链路排队把整次 job 拖到 350 µs。

## 根因

`UbRgScheduler::AccountInflight` 在归还 credit 时，对 `m_inflight` 中元素持有 **const 引用**，却先 `erase` 再读 `rec.src`：

```cpp
// OnDataEgress
AccountInflight(it->first, it->second);  // 传入 map 节点引用

void AccountInflight(uint64_t ikey, const InflightRec& rec) {
    m_inflight.erase(ikey);              // 销毁 rec 指向的节点
    m_credit[rec.src] += 1;              // 未定义行为：src 实际几乎全变成 0
}
```

`erase` 后继续使用引用是 **未定义行为**。实测结果：所有 credit 归还都记到 **src 0**，其它源窗口耗尽后无法再获 GNT。

### 为何恰好卡在 4192？

- S1 credit 窗口 = **4**
- 调度器数 = **8**，源 NPU = **128**
- 每个源大约只能完成窗口次授权：\(8 \times 128 \times 4 = 4192\)

与 stall 完成数一致。

## 运行时证据

| 证据 | 结论 |
|---|---|
| Hit 日志 `recSrc` = 20 / 36 / 53 … | 匹配瞬间 map 里源号正确 |
| 同一次调用的 `account_inflight` 全是 `src: 0` | erase 后读到的源号已坏 |
| `grantSrcs=128`，`accountSrcs=1`，`account0=4192` | 授信分散、归账只进源 0 |
| `inflightOverwrite=0` | 不是 inflight key 覆盖 |
| `grantsIssued == accountInflight == 4192` | token 匹配本身成功；错在归账 `src` |
| `reclaimStale=0` | 不是超时强收路径 |

## 排除项

- **不是**「GNT 按包而非按 grain」：末片 `GetLastPacket()` 已对齐 grain 关闭。
- **不是** IPv4 src / FlowId 导致无法命中 inflight（tokenId 键可命中）。
- **不是** 网络 hop 时延异常（单 grain 延迟正常量级）。

## 修复

`AccountInflight` 改为 **按值** 传入 `InflightRec`，在 `erase` 前完成拷贝，再用拷贝上的 `src` 还 credit：

```cpp
void AccountInflight(uint64_t ikey, InflightRec rec);  // by value
```

涉及文件：

- `ns-3-ub/src/unified-bus/model/protocol/ub-rg-scheduler.h`
- `ns-3-ub/src/unified-bus/model/protocol/ub-rg-scheduler.cc`

## 一句话

DATA 命中 inflight 后还 credit 时，先 erase 再解引用 map 元素，导致 **credit 全部还给 src 0**，其它源耗尽窗口后全局 stall 在 4192/16384。
