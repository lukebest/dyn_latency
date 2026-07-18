"""Grain-level event simulation of UB Request/Grant (docs/ub_request_grant.md).

Two topologies:
  * single : N NPUs x P planes, each plane one SW (radix >= N). Path = 2 hops.
             Conflict point: SW downlink (plane, dst).
  * two    : N NPUs (N % 64 == 0), groups of 64; leaves = 8*groups (leaf (g,p));
             64 spines. NPU (g,m) port p -> Leaf (g,p) downlink m. Path = 4 hops.
             Conflict points: Leaf_s->Spine, Spine->Leaf_d, Leaf_d->NPU.

Two modes:
  * rg   : request/grant per the doc. Per-shard scheduler: every tau_g each
           egress grants <=1 grain (RR over sources with per-(shard,src) credit
           C). Two-layer grants pin spine (rotation) and inject port
           ((spine+member) mod 8). Data injected on grant arrival, FCFS.
  * base : traditional free injection: all grains queued at t_start, path
           pinned up-front (flow-hash ECMP or per-token spray), switches queue
           (infinite buffer = optimistic assumption of doc §8.3).

All times in ns. One grain = one fixed-size packet (default 7168 B @ 50 GB/s
=> tau_g = 143.36 ns).
"""
from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------- parameters

@dataclass
class Params:
    topology: str = "single"          # "single" | "two"
    n_nodes: int = 128
    n_planes: int = 8                 # single-layer planes / two-layer NPU ports (=8)
    mode: str = "rg"                  # "rg" | "base"
    # physics
    grain_bytes: int = 7168
    rate_GBps: float = 50.0           # effective per-link bandwidth
    prop_ns: float = 50.0             # per-link propagation (10 m)
    pipe_ns: float = 150.0            # switch cut-through pipeline
    dma_ns: float = 100.0             # source fetch/injection overhead
    dma_jit_ns: float = 50.0          # uniform jitter on dma
    req_delay_ns: float = 250.0       # REQ endpoint->scheduler (set ~500 for two-layer)
    gnt_delay_ns: float = 200.0       # GNT scheduler->endpoint (set ~500 for two-layer)
    sync_hop_ns: float = 200.0        # one control hop for SYNC accounting
    # protocol
    credit: int = 4                   # per-(shard, src) in-flight window C
    precomp: bool = False             # per-source delay pre-compensation (§2.10)
    matching: str = "lqf"             # "lqf" (critical-first, ~BvN) | "rr" (naive)
    # heterogeneity
    skew_max_ns: float = 0.0          # per-node cable-length skew, uniform [0, max]
    start_skew_ns: float = 200.0      # BSP entry skew, uniform [0, max]
    # baseline path selection
    base_path: str = "hash"           # "hash" (flow-bound ECMP) | "spray" (per-token)
    seed: int = 0

    @property
    def tau(self) -> float:
        return self.grain_bytes / self.rate_GBps  # ns


@dataclass
class Traffic:
    """Flattened grains: one entry per grain (multi-grain tokens pre-expanded)."""
    src: np.ndarray                   # int32 [G]
    dst: np.ndarray                   # int32 [G]

    @property
    def n(self) -> int:
        return len(self.src)


# ---------------------------------------------------------------- traffic gen

def balanced_tokens(N: int, per_pair: int) -> Traffic:
    """Each src sends `per_pair` grains to every other node, dst-interleaved."""
    src, dst = [], []
    for i in range(N):
        for t in range(per_pair * (N - 1)):
            d = (i + 1 + (t % (N - 1))) % N
            src.append(i); dst.append(d)
    return Traffic(np.array(src, np.int32), np.array(dst, np.int32))


def uniform_tokens(N: int, M: int, seed: int = 0) -> Traffic:
    """Each src sends M grains to uniformly random other nodes."""
    rng = np.random.default_rng(seed)
    src = np.repeat(np.arange(N, dtype=np.int32), M)
    d = rng.integers(0, N - 1, size=N * M).astype(np.int32)
    d = d + (d >= src)                # exclude self
    return Traffic(src, d)


def hotspot_tokens(N: int, M: int, rho: float, hot: int = 0, seed: int = 0) -> Traffic:
    """Fraction rho of each src's grains go to `hot`, rest uniform."""
    rng = np.random.default_rng(seed)
    src = np.repeat(np.arange(N, dtype=np.int32), M)
    d = rng.integers(0, N - 1, size=N * M).astype(np.int32)
    d = d + (d >= src)
    mask = (rng.random(N * M) < rho) & (src != hot)
    d[mask] = hot
    return Traffic(src, d)


def incast_tokens(N: int, K: int, dst0: int = 0) -> Traffic:
    """Every node != dst0 sends K grains to dst0."""
    src = np.repeat(np.array([i for i in range(N) if i != dst0], np.int32), K)
    return Traffic(src, np.full(len(src), dst0, np.int32))


def overload_tokens(N: int, M_bg: int, hot_src: int, M_hot: int, seed: int = 0) -> Traffic:
    """Uniform background M_bg per src; hot_src additionally sends M_hot uniform."""
    bg = uniform_tokens(N, M_bg, seed)
    rng = np.random.default_rng(seed + 1)
    d = rng.integers(0, N - 1, size=M_hot).astype(np.int32)
    d = d + (d >= hot_src)
    src = np.concatenate([bg.src, np.full(M_hot, hot_src, np.int32)])
    dst = np.concatenate([bg.dst, d])
    return Traffic(src, dst)


# ---------------------------------------------------------------- simulator

# event kinds
EV_TICK, EV_REQ, EV_GNT, EV_HOP, EV_DONE = 0, 1, 2, 3, 4


class Sim:
    def __init__(self, p: Params, tr: Traffic):
        self.p = p
        self.tr = tr
        rng = np.random.default_rng(p.seed + 7777)
        G = tr.n
        N = p.n_nodes
        self.tau = p.tau
        self.skew = rng.uniform(0.0, p.skew_max_ns, N) if p.skew_max_ns > 0 else np.zeros(N)
        self.t_start = rng.uniform(0.0, p.start_skew_ns, N) if p.start_skew_ns > 0 else np.zeros(N)
        self.dma = np.full(G, p.dma_ns)
        if p.dma_jit_ns > 0:
            self.dma += rng.uniform(0.0, p.dma_jit_ns, G)

        # per-grain path fields
        self.g_port = np.zeros(G, np.int32)
        self.g_plane = np.zeros(G, np.int32)   # single: plane; two: dst-side plane p
        self.g_spine = np.zeros(G, np.int32)   # two-layer only
        # per-grain timestamps
        self.t_issue = np.full(G, np.nan)      # grant issue (rg)
        self.t_net0 = np.full(G, np.nan)       # start of injection serialization
        self.t_deliver = np.full(G, np.nan)
        self.wait_net = np.zeros(G)            # queueing wait downstream of source port

        if p.topology == "two":
            assert N % 64 == 0 and p.n_planes == 8
            self.groups = N // 64
            self.n_leaf = 8 * self.groups
            self.n_spine = 64
            self.n_shard = self.n_leaf
            self.n_egress = 64
            self.stages = 4
        else:
            self.n_shard = p.n_planes
            self.n_egress = N
            self.stages = 2

        # dst-side plane chosen by the sender at request time (§3.3/§5.2):
        # (src + dst) spreads each src's grains AND each dst's arrivals across
        # planes; per-(src,dst) counter rotates repeat grains of the same pair.
        self.per_src_idx = np.zeros(G, np.int64)
        self.pair_idx = np.zeros(G, np.int64)
        cnt = np.zeros(N, np.int64)
        pair_cnt: dict[int, int] = {}
        for i in range(G):
            s = tr.src[i]
            self.per_src_idx[i] = cnt[s]
            cnt[s] += 1
            key = int(s) * N + int(tr.dst[i])
            c = pair_cnt.get(key, 0)
            self.pair_idx[i] = c
            pair_cnt[key] = c + 1
        self.g_plane[:] = (tr.src + tr.dst + self.pair_idx) % p.n_planes

        if p.mode == "base":
            self._pin_baseline(rng)

        # servers: free_at per stage
        P = p.n_planes
        if p.topology == "two":
            sizes = [N * 8, self.n_leaf * 64, self.n_spine * self.n_leaf, self.n_leaf * 64]
        else:
            sizes = [N * P, P * N]
        self.free_at = [np.zeros(s) for s in sizes]
        self.stage_wait_max = np.zeros(self.stages)
        self.stage_wait_sum = np.zeros(self.stages)
        self.stage_cnt = np.zeros(self.stages, np.int64)

        # scheduler state (rg)
        if p.mode == "rg":
            self.pend = [dict() for _ in range(self.n_shard)]           # (egr<<20|src) -> deque[gid]
            self.pcnt = [np.zeros((N, self.n_egress), np.int32) for _ in range(self.n_shard)]
            self.row_rem = [np.zeros(N, np.int64) for _ in range(self.n_shard)]
            self.col_rem = [np.zeros(self.n_egress, np.int64) for _ in range(self.n_shard)]
            self.credit = [np.full(N, p.credit, np.int32) for _ in range(self.n_shard)]
            self.next_ok = [np.zeros(self.n_egress) for _ in range(self.n_shard)]
            # offset per egress so the <=64 grants of one round pin distinct spines
            self.spine_ptr = [np.arange(self.n_egress, dtype=np.int64)
                              for _ in range(self.n_shard)]
            self.rr_ptr = [np.zeros(self.n_egress, np.int64) for _ in range(self.n_shard)]
            self.pending_tot = np.zeros(self.n_shard, np.int64)
            self.active = np.zeros(self.n_shard, bool)
        self.last_forward = np.zeros(self.n_shard)

        self.heap: list = []
        self.seq = 0
        self.done = 0

    # -------------------------------------------------------- helpers
    def _push(self, t: float, kind: int, a: int = 0, b: int = 0) -> None:
        heapq.heappush(self.heap, (t, self.seq, kind, a, b))
        self.seq += 1

    def _pin_baseline(self, rng) -> None:
        p, tr = self.p, self.tr
        h = (tr.src.astype(np.int64) * 2654435761 + tr.dst.astype(np.int64) * 40503
             + p.seed * 97) & 0x7FFFFFFF
        if p.topology == "two":
            member = tr.src % 64
            if p.base_path == "hash":     # flow-bound ECMP: spine & dst-plane by flow hash
                self.g_spine[:] = h % 64
                self.g_plane[:] = (h >> 8) % 8
                self.g_port[:] = (h >> 16) % 8
            else:                          # per-token spraying (same balance as rg)
                self.g_spine[:] = (tr.src + tr.dst + self.per_src_idx) % 64
                self.g_plane[:] = (tr.src + tr.dst + self.pair_idx) % 8
                self.g_port[:] = (self.g_spine + member) % 8
        else:
            if p.base_path == "hash":
                self.g_plane[:] = h % p.n_planes
            self.g_port[:] = self.g_plane

    def _server_idx(self, stage: int, g: int) -> int:
        tr, p = self.tr, self.p
        if p.topology == "single":
            if stage == 0:
                return tr.src[g] * p.n_planes + self.g_port[g]
            return self.g_plane[g] * p.n_nodes + tr.dst[g]
        s, d = tr.src[g], tr.dst[g]
        if stage == 0:
            return s * 8 + self.g_port[g]
        if stage == 1:                       # Leaf_s uplink to spine
            src_leaf = (s >> 6) * 8 + self.g_port[g]
            return src_leaf * 64 + self.g_spine[g]
        dst_leaf = (d >> 6) * 8 + self.g_plane[g]
        if stage == 2:                       # Spine downlink to Leaf_d
            return self.g_spine[g] * self.n_leaf + dst_leaf
        return dst_leaf * 64 + (d % 64)      # Leaf_d downlink to NPU

    def _shard_of(self, g: int) -> tuple[int, int]:
        """(shard, egress) of grain g's scheduled conflict point."""
        if self.p.topology == "single":
            return self.g_plane[g], self.tr.dst[g]
        d = self.tr.dst[g]
        return (d >> 6) * 8 + self.g_plane[g], d % 64

    # -------------------------------------------------------- run
    def run(self) -> dict:
        p, tr = self.p, self.tr
        if p.mode == "rg":
            self._emit_requests()
        else:
            for g in range(tr.n):
                self._push(self.t_start[tr.src[g]], EV_HOP, g, 0)

        heap = self.heap
        while heap:
            t, _, kind, a, b = heapq.heappop(heap)
            if kind == EV_HOP:
                self._on_hop(t, a, b)
            elif kind == EV_TICK:
                self._on_tick(t, a)
            elif kind == EV_DONE:
                self._on_done(t, a)
            elif kind == EV_GNT:
                self._on_gnt(t, a)
            elif kind == EV_REQ:
                self._on_req(t, a, b)
        return self._results()

    # -------------------------------------------------------- rg control plane
    def _emit_requests(self) -> None:
        """Group grains by (src, shard); one REQ event per group."""
        p, tr = self.p, self.tr
        self.req_groups: dict[tuple[int, int], list[int]] = {}
        for g in range(tr.n):
            shard, _ = self._shard_of(g)
            self.req_groups.setdefault((tr.src[g], shard), []).append(g)
        self.req_list = list(self.req_groups.items())
        for idx, ((s, shard), _) in enumerate(self.req_list):
            t = self.t_start[s] + p.req_delay_ns + self.skew[s]
            self._push(t, EV_REQ, idx, shard)

    def _on_req(self, t: float, idx: int, shard: int) -> None:
        (s, _), grains = self.req_list[idx]
        pend = self.pend[shard]
        pcnt, row, col = self.pcnt[shard], self.row_rem[shard], self.col_rem[shard]
        for g in grains:
            _, egr = self._shard_of(g)
            key = (egr << 20) | s
            dq = pend.get(key)
            if dq is None:
                pend[key] = dq = deque()
            dq.append(g)
            pcnt[s, egr] += 1
            row[s] += 1
            col[egr] += 1
        self.pending_tot[shard] += len(grains)
        if not self.active[shard]:
            self.active[shard] = True
            self._push(t, EV_TICK, shard)

    def _on_tick(self, t: float, shard: int) -> None:
        """One scheduling round: per-egress arbitration with a per-round
        accept phase (each src <=1 grant/round).  matching == "lqf" serves
        egresses in decreasing remaining-load order and picks for each the
        feasible src with the largest remaining row load - a greedy
        approximation of the critical (BvN / Koenig) permutation (§6.3(2))."""
        p = self.p
        pend = self.pend[shard]
        pcnt, row, col = self.pcnt[shard], self.row_rem[shard], self.col_rem[shard]
        credit, next_ok = self.credit[shard], self.next_ok[shard]
        sptr, rrp = self.spine_ptr[shard], self.rr_ptr[shard]
        gnt_base = p.gnt_delay_ns
        taken = np.zeros(p.n_nodes, bool)   # accept phase (§6.4)

        eligible = [e for e in range(self.n_egress)
                    if col[e] > 0 and t + 1e-6 >= next_ok[e]]
        if p.matching == "lqf":
            eligible.sort(key=lambda e: -col[e])
        for egr in eligible:
            crow = pcnt[:, egr]
            cand = np.nonzero((crow > 0) & (credit > 0) & ~taken)[0]
            if len(cand) == 0:
                continue
            if p.matching == "lqf":
                s = int(cand[np.argmax(row[cand])])
            else:                       # plain RR scan
                ptr = rrp[egr]
                rel = (cand - ptr) % p.n_nodes
                s = int(cand[np.argmin(rel)])
                rrp[egr] = s + 1
            g = pend[(egr << 20) | s].popleft()
            credit[s] -= 1
            taken[s] = True
            pcnt[s, egr] -= 1
            row[s] -= 1
            col[egr] -= 1
            self.pending_tot[shard] -= 1
            # pin path (§5.2)
            if p.topology == "two":
                sp = int(sptr[egr]) % 64
                sptr[egr] += 1
                self.g_spine[g] = sp
                self.g_port[g] = (sp + (self.tr.src[g] % 64)) % 8
            else:
                self.g_port[g] = shard
            self.t_issue[g] = t
            skew = 0.0 if p.precomp else self.skew[s]
            self._push(t + gnt_base + skew, EV_GNT, g)
            next_ok[egr] = t + self.tau
        if self.pending_tot[shard] > 0:
            self._push(t + self.tau, EV_TICK, shard)
        else:
            self.active[shard] = False

    def _on_gnt(self, t: float, g: int) -> None:
        self._push(t + self.dma[g], EV_HOP, g, 0)

    # -------------------------------------------------------- data plane
    def _on_hop(self, t: float, g: int, stage: int) -> None:
        p = self.p
        idx = self._server_idx(stage, g)
        fa = self.free_at[stage]
        start = t if t >= fa[idx] else fa[idx]
        dep = start + self.tau
        fa[idx] = dep
        w = start - t
        if w > self.stage_wait_max[stage]:
            self.stage_wait_max[stage] = w
        self.stage_wait_sum[stage] += w
        self.stage_cnt[stage] += 1
        if stage == 0:
            self.t_net0[g] = start
        else:
            self.wait_net[g] += w
        if stage == self.stages - 1:
            self._push(dep, EV_DONE, g)
        else:
            hop = p.prop_ns + p.pipe_ns
            if stage == 0:
                hop += self.skew[self.tr.src[g]]      # cable skew on the NPU uplink
            self._push(dep + hop, EV_HOP, g, stage + 1)

    def _on_done(self, t: float, g: int) -> None:
        """Grain departs the final (scheduled) egress: account + deliver."""
        p = self.p
        shard, _ = self._shard_of(g) if p.mode == "rg" else (0, 0)
        if p.mode == "rg":
            s = self.tr.src[g]
            self.credit[shard][s] += 1
            if self.last_forward[shard] < t:
                self.last_forward[shard] = t
            if self.pending_tot[shard] > 0 and not self.active[shard]:
                self.active[shard] = True
                self._push(t, EV_TICK, shard)
        self.t_deliver[g] = t + p.prop_ns + self.skew[self.tr.dst[g]]
        self.done += 1

    # -------------------------------------------------------- results
    def _results(self) -> dict:
        p, tr = self.p, self.tr
        tau = self.tau
        # per-conflict-point load (grain count) -> Koenig bound
        if p.topology == "single":
            loads = np.zeros((self.n_shard, self.n_egress), np.int64)
            np.add.at(loads, (self.g_plane, tr.dst), 1)
            port_loads = np.zeros((p.n_nodes, p.n_planes), np.int64)
            np.add.at(port_loads, (tr.src, self.g_port), 1)
        else:
            dst_leaf = (tr.dst >> 6) * 8 + self.g_plane
            loads = np.zeros((self.n_leaf, 64), np.int64)
            np.add.at(loads, (dst_leaf, tr.dst % 64), 1)
            port_loads = np.zeros((p.n_nodes, 8), np.int64)
            np.add.at(port_loads, (tr.src, self.g_port), 1)
        koenig_ns = max(loads.max(), port_loads.max()) * tau

        lat = self.t_deliver - self.t_net0                       # network latency after injection start
        makespan = float(np.nanmax(self.t_deliver))
        res = {
            "mode": p.mode, "topology": p.topology, "n_nodes": p.n_nodes,
            "grains": tr.n, "tau_ns": tau,
            "makespan_ns": makespan,
            "first_deliver_ns": float(np.nanmin(self.t_deliver)),
            "koenig_bound_ns": float(koenig_ns),
            "max_egress_load": int(loads.max()),
            "max_port_load": int(port_loads.max()),
            "net_lat_mean_ns": float(np.nanmean(lat)),
            "net_lat_p50_ns": float(np.nanpercentile(lat, 50)),
            "net_lat_p99_ns": float(np.nanpercentile(lat, 99)),
            "net_lat_max_ns": float(np.nanmax(lat)),
            "net_lat_std_ns": float(np.nanstd(lat)),
            "wait_net_mean_ns": float(self.wait_net.mean()),
            "wait_net_p99_ns": float(np.percentile(self.wait_net, 99)),
            "wait_net_max_ns": float(self.wait_net.max()),
            "stage_wait_max_ns": self.stage_wait_max.tolist(),
            "stage_wait_mean_ns": (self.stage_wait_sum
                                   / np.maximum(self.stage_cnt, 1)).tolist(),
            "stage_backlog_max_grain": (self.stage_wait_max / tau + 1.0).tolist(),
            "done": int(self.done),
        }
        # per-destination completion (for HOL-spreading checks)
        per_dst = np.zeros(p.n_nodes)
        np.maximum.at(per_dst, tr.dst, self.t_deliver)
        res["per_dst_done_ns"] = per_dst
        # spine link balance (two-layer)
        if p.topology == "two":
            up = np.zeros((self.n_leaf, 64), np.int64)
            src_leaf = (tr.src >> 6) * 8 + self.g_port
            np.add.at(up, (src_leaf, self.g_spine), 1)
            down = np.zeros((64, self.n_leaf), np.int64)
            np.add.at(down, (self.g_spine, dst_leaf), 1)
            res["spine_up_max"] = int(up.max()); res["spine_up_mean"] = float(up.mean())
            res["spine_down_max"] = int(down.max()); res["spine_down_mean"] = float(down.mean())
        # barrier (rg: cursor/SYNC per §2.9/§4.9; base: added by caller)
        if p.mode == "rg":
            if p.topology == "single":
                res["barrier_ns"] = float(self.last_forward.max() + p.sync_hop_ns)
            else:
                arrive = self.last_forward + 2 * p.sync_hop_ns
                res["barrier_ns"] = float(arrive.max() + 3 * p.sync_hop_ns)
            res["rtt_rg_ns"] = p.req_delay_ns + p.gnt_delay_ns
            issued = self.t_issue[~np.isnan(self.t_issue)]
            res["grant_span_ns"] = float(issued.max() - issued.min()) if len(issued) else 0.0
        return res


def simulate(p: Params, tr: Traffic) -> dict:
    return Sim(p, tr).run()
