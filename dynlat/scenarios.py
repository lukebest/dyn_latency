"""Scenario definitions and per-phase runner.

A "phase" is a byte matrix M[src][dst] (dispatch: i->expert j; combine: expert
j->origin i). The *receiver* of a flow is always ``flow.dst``.

Scenarios (SHMEM-POP技术分档 §1.12.4-5):
  * oracle    : VoQ, infinite buffer, no backpressure-to-source  -> incast floor
  * baseline  : uncoordinated kernel-direct; FIFO source (HOL), shallow lossy
                switch buffer + retransmit -> classic incast collapse
  * shmempop  : VoQ isolation + receiver credit (BDP) pacing + 1xRTT push phase
                -> approaches the floor without buffer overflow
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .fabric import Fabric, FabricConfig, Flow


@dataclass
class PhaseResult:
    name: str
    scenario: str
    makespan: float
    floor: float                      # analytical incast floor (serialize+static)
    incast_serialize: float           # bottleneck-link serialization (unoptimizable)
    static: float
    recv_done: np.ndarray             # per-receiver completion time
    bottleneck_bytes: float
    bytes_total: float
    buffer_bytes: float               # per-output-port switch buffer used
    credit_bytes: float               # receiver credit window (0 if none)


def analytical_floor(cfg: FabricConfig, M: np.ndarray) -> tuple[float, float]:
    """Return (floor_makespan, incast_serialize_time)."""
    C = cfg.link_Bps * cfg.n_planes   # effective per-endpoint capacity over planes
    up = M.sum(axis=1).max()          # busiest source uplink bytes
    down = M.sum(axis=0).max()        # busiest dst downlink bytes (incast)
    bottleneck = max(up, down)
    incast_serialize = bottleneck / C
    floor = incast_serialize + cfg.static_chunk_latency
    return floor, incast_serialize


def base_phys(n_planes: int = 1, n_nodes: int = 16) -> FabricConfig:
    return FabricConfig(
        n_nodes=n_nodes, n_planes=n_planes, link_bps=200e9, chunk_bytes=4096,
        d_prop=100e-9, l_switch=300e-9,
    )


def _bdp(cfg: FabricConfig) -> float:
    return cfg.link_Bps * RTT


RTT = 1.0e-6  # platform-calibrated POP round trip (SHMEM-POP §1.8)

# buffer-sizing constants
BASE_FIXED_BUF = 128 * 1024   # reference fixed per-port buffer ("fixed" mode)
BASE_MATCH_ALPHA = 1.0        # matched buffer = ALPHA * BDP * per-plane fan-in
SHMEM_BUF_BDP = 4             # receiver-paced: O(BDP) buffer regardless of N,P


def matched_buffer(cfg: FabricConfig, n_nodes: int) -> float:
    """Lossless buffer that absorbs the per-plane incast fan-in.

    A hot output port receives from up to (N-1) sources, striped over P planes,
    so per-plane fan-in = ceil((N-1)/P). A buffer of one BDP per concurrent
    sender removes link-level backpressure entirely -> baseline reaches the
    floor, at the cost of buffer that grows like O(N/P)."""
    fanin = max(1, math.ceil((n_nodes - 1) / cfg.n_planes))
    return BASE_MATCH_ALPHA * _bdp(cfg) * fanin


def make_config(scenario: str, n_planes: int = 1, n_nodes: int = 16,
                buffer_mode: str = "fixed",
                baseline_buffer_bytes: float | None = None) -> tuple[FabricConfig, float]:
    """Return (FabricConfig, push_delay).

    buffer_mode: "fixed"   -> baseline uses a fixed reference buffer (128KB)
                 "matched" -> baseline buffer follows the (P,N) fan-in (BDP-based)
    baseline_buffer_bytes: if set, overrides buffer_mode for baseline buffer size
    """
    cfg = base_phys(n_planes, n_nodes)
    if scenario == "oracle":
        return replace(cfg, discipline="voq", buffer_bytes=None,
                       credit_bytes=None, lossy=False), 0.0
    if scenario == "baseline":
        # uncoordinated kernel-direct, but on the SAME lossless CBFC fabric as
        # SHMEM-POP: single FIFO source send queue (HOL) + finite per-port buffer
        # with link-level backpressure. No receiver pacing, no VoQ isolation.
        if baseline_buffer_bytes is not None:
            buf = baseline_buffer_bytes
        elif buffer_mode == "matched":
            buf = matched_buffer(cfg, n_nodes)
        else:
            buf = BASE_FIXED_BUF
        return replace(cfg, discipline="fifo", buffer_bytes=buf,
                       credit_bytes=None, lossy=False), 0.0
    if scenario == "shmempop":
        bdp = _bdp(cfg)
        # receiver-paced: buffer stays O(BDP) no matter how large N,P grow
        return replace(cfg, discipline="voq", buffer_bytes=SHMEM_BUF_BDP * bdp,
                       credit_bytes=bdp, lossy=False), RTT  # 1xRTT push
    raise ValueError(scenario)


def run_phase(name: str, scenario: str, M: np.ndarray, n_planes: int = 1,
              buffer_mode: str = "fixed",
              baseline_buffer_bytes: float | None = None) -> PhaseResult:
    N = M.shape[0]
    cfg, push = make_config(scenario, n_planes, n_nodes=N, buffer_mode=buffer_mode,
                            baseline_buffer_bytes=baseline_buffer_bytes)
    flows: list[Flow] = []
    for i in range(N):
        for j in range(N):
            b = float(M[i, j])
            if b <= 0:
                continue
            plane = (i * N + j) % cfg.n_planes
            flows.append(Flow(src=i, dst=j, nbytes=b, start=push, plane=plane))
    fab = Fabric(cfg, flows)
    fab.run()

    recv = np.zeros(N)
    for f in flows:
        recv[f.dst] = max(recv[f.dst], f.done_time)
    makespan = recv.max() if len(flows) else 0.0
    floor, incast = analytical_floor(cfg, M)
    buf = math.inf if cfg.buffer_bytes is None else float(cfg.buffer_bytes)
    cred = 0.0 if cfg.credit_bytes is None else float(cfg.credit_bytes)
    return PhaseResult(
        name=name, scenario=scenario, makespan=makespan, floor=floor,
        incast_serialize=incast, static=cfg.static_chunk_latency,
        recv_done=recv, bottleneck_bytes=max(M.sum(0).max(), M.sum(1).max()),
        bytes_total=float(M.sum()),
        buffer_bytes=buf, credit_bytes=cred,
    )
