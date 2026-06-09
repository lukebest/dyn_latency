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


def analytical_floor(cfg: FabricConfig, M: np.ndarray) -> tuple[float, float]:
    """Return (floor_makespan, incast_serialize_time)."""
    C = cfg.link_Bps * cfg.n_planes   # effective per-endpoint capacity over planes
    up = M.sum(axis=1).max()          # busiest source uplink bytes
    down = M.sum(axis=0).max()        # busiest dst downlink bytes (incast)
    bottleneck = max(up, down)
    incast_serialize = bottleneck / C
    floor = incast_serialize + cfg.static_chunk_latency
    return floor, incast_serialize


def base_phys(n_planes: int = 1) -> FabricConfig:
    return FabricConfig(
        n_nodes=16, n_planes=n_planes, link_bps=200e9, chunk_bytes=4096,
        d_prop=100e-9, l_switch=300e-9,
    )


def _bdp(cfg: FabricConfig) -> float:
    return cfg.link_Bps * RTT


RTT = 1.0e-6  # platform-calibrated POP round trip (SHMEM-POP §1.8)


def make_config(scenario: str, n_planes: int = 1) -> tuple[FabricConfig, float]:
    """Return (FabricConfig, push_delay)."""
    cfg = base_phys(n_planes)
    if scenario == "oracle":
        return replace(cfg, discipline="voq", buffer_bytes=None,
                       credit_bytes=None, lossy=False), 0.0
    if scenario == "baseline":
        # uncoordinated: FIFO source send queue (HOL), shallow switch buffer,
        # lossy with retransmit -> incast collapse
        return replace(cfg, discipline="fifo", buffer_bytes=64 * 1024,
                       credit_bytes=None, lossy=True, rto=5e-6), 0.0
    if scenario == "shmempop":
        bdp = _bdp(cfg)
        return replace(cfg, discipline="voq", buffer_bytes=4 * bdp,
                       credit_bytes=bdp, lossy=False), RTT  # 1xRTT push
    raise ValueError(scenario)


def run_phase(name: str, scenario: str, M: np.ndarray, n_planes: int = 1) -> PhaseResult:
    cfg, push = make_config(scenario, n_planes)
    N = cfg.n_nodes
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
    return PhaseResult(
        name=name, scenario=scenario, makespan=makespan, floor=floor,
        incast_serialize=incast, static=cfg.static_chunk_latency,
        recv_done=recv, bottleneck_bytes=max(M.sum(0).max(), M.sum(1).max()),
        bytes_total=float(M.sum()),
    )
