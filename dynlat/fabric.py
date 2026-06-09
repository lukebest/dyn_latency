"""Single group-switch fabric model.

Topology: N endpoint nodes, each with one uplink (node->switch) and one
downlink (switch->node) per plane. The switch is a non-blocking, output-queued
crossbar with a finite (or infinite) per-output-port buffer and lossless
backpressure (PFC/CBFC style): an uplink may not dispatch a chunk toward an
output whose committed buffer would overflow, nor toward a destination whose
receiver credit window is exhausted.

Two ingress disciplines model the difference between an uncoordinated baseline
and SHMEM-POP:

* ``fifo`` (baseline / kernel-direct): one ordered send queue per source. The
  head-of-line chunk blocks everything behind it when its output is congested
  -> HOL blocking + congestion spreading onto cold flows.
* ``voq``  (oracle / SHMEM-POP): per-destination virtual output queues at the
  source. A congested destination only stalls its own VoQ; cold flows proceed.

Receiver-driven credit (``credit_bytes``) models the SHMEM-POP ESC pull-grant
window (a BDP-sized cap on in-flight bytes per destination), which keeps the
switch output buffer from ever building up under incast.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .engine import Engine


@dataclass
class FabricConfig:
    n_nodes: int = 16
    n_planes: int = 1
    link_bps: float = 200e9           # 200 Gbps per link
    chunk_bytes: int = 4096           # pull_credit_size (SHMEM-POP §1.8)
    d_prop: float = 100e-9            # one-way propagation per link
    l_switch: float = 300e-9          # switch pipeline (store-and-forward min)
    buffer_bytes: float | None = None  # per output port; None = infinite
    discipline: str = "voq"           # "voq" or "fifo"
    credit_bytes: float | None = None  # per-dst in-flight cap; None = none
    lossy: bool = False               # drop on buffer overflow + retransmit
    rto: float = 5e-6                 # retransmit timeout (lossy mode)

    @property
    def link_Bps(self) -> float:
        return self.link_bps / 8.0

    def serialize(self, nbytes: float) -> float:
        return nbytes / self.link_Bps

    @property
    def static_chunk_latency(self) -> float:
        """One chunk crossing an otherwise empty network."""
        s = self.serialize(self.chunk_bytes)
        return s + self.d_prop + self.l_switch + s + self.d_prop


@dataclass
class Flow:
    src: int
    dst: int
    nbytes: float
    start: float = 0.0          # injectable time (after push phase for SHMEM-POP)
    plane: int = 0
    # runtime
    chunks_total: int = 0
    chunks_done: int = 0
    done_time: float = -1.0
    first_ready: float = 0.0


@dataclass
class _Chunk:
    flow: Flow
    nbytes: int
    seq: int


class Fabric:
    """Simulate one communication phase (a set of flows) to completion."""

    def __init__(self, cfg: FabricConfig, flows: list[Flow]):
        self.cfg = cfg
        self.eng = Engine()
        self.flows = flows
        N, P = cfg.n_nodes, cfg.n_planes

        # source send structures, per (plane, src)
        # fifo: ordered list; voq: dict dst -> list
        self._fifo: list[list[list[_Chunk]]] = [[[] for _ in range(N)] for _ in range(P)]
        self._voq: list[list[dict[int, list[_Chunk]]]] = [
            [dict() for _ in range(N)] for _ in range(P)
        ]
        self._voq_rr: list[list[int]] = [[0] * N for _ in range(P)]
        self._uplink_busy = [[False] * N for _ in range(P)]

        # switch output: per (plane, dst) queue + committed occupancy
        self._outq: list[list[list[_Chunk]]] = [[[] for _ in range(N)] for _ in range(P)]
        self._occ = [[0.0] * N for _ in range(P)]          # bytes committed to buffer
        self._downlink_busy = [[False] * N for _ in range(P)]

        self._inflight = [[0.0] * N for _ in range(P)]     # bytes left-source, not delivered (credit)

        self._pending = 0  # chunks not yet delivered

    # ---- construction -------------------------------------------------
    def _split(self) -> None:
        cb = self.cfg.chunk_bytes
        for f in self.flows:
            n = max(1, int(-(-int(f.nbytes) // cb)))  # ceil
            f.chunks_total = n
            f.first_ready = f.start
            rem = int(f.nbytes)
            for s in range(n):
                size = cb if rem >= cb else rem
                if size <= 0:
                    size = rem if rem > 0 else cb
                rem -= cb
                ch = _Chunk(flow=f, nbytes=max(1, size), seq=s)
                self.eng.at(f.start, lambda c=ch: self._make_ready(c))
                self._pending += 1

    def _make_ready(self, ch: _Chunk) -> None:
        p, src, dst = ch.flow.plane, ch.flow.src, ch.flow.dst
        if self.cfg.discipline == "fifo":
            self._fifo[p][src].append(ch)
        else:
            self._voq[p][src].setdefault(dst, []).append(ch)
        self._poke_uplink(p, src)

    # ---- eligibility --------------------------------------------------
    def _eligible(self, p: int, dst: int, nbytes: int) -> bool:
        cfg = self.cfg
        # in lossy mode the buffer is NOT an admission constraint: the source
        # blasts open-loop and overflow is handled by drop+retransmit.
        if (not cfg.lossy and cfg.buffer_bytes is not None
                and self._occ[p][dst] + nbytes > cfg.buffer_bytes + 1e-9):
            return False
        if cfg.credit_bytes is not None and self._inflight[p][dst] + nbytes > cfg.credit_bytes + 1e-9:
            return False
        return True

    # ---- uplink scheduler --------------------------------------------
    def _poke_uplink(self, p: int, src: int) -> None:
        if self._uplink_busy[p][src]:
            return
        ch = self._pick_uplink(p, src)
        if ch is None:
            return
        self._uplink_busy[p][src] = True
        # lossless: reserve buffer at dispatch. lossy: buffer charged on arrival.
        if not self.cfg.lossy:
            self._occ[p][ch.flow.dst] += ch.nbytes
        self._inflight[p][ch.flow.dst] += ch.nbytes
        dur = self.cfg.serialize(ch.nbytes)
        self.eng.after(dur, lambda: self._uplink_done(p, src, ch))

    def _pick_uplink(self, p: int, src: int) -> _Chunk | None:
        if self.cfg.discipline == "fifo":
            q = self._fifo[p][src]
            if not q:
                return None
            head = q[0]
            if self._eligible(p, head.flow.dst, head.nbytes):
                return q.pop(0)
            return None  # HOL block
        # voq: round-robin over destinations with an eligible head
        voq = self._voq[p][src]
        if not voq:
            return None
        dsts = sorted(voq.keys())
        if not dsts:
            return None
        start = self._voq_rr[p][src] % len(dsts)
        for k in range(len(dsts)):
            dst = dsts[(start + k) % len(dsts)]
            q = voq[dst]
            if q and self._eligible(p, dst, q[0].nbytes):
                self._voq_rr[p][src] = (start + k + 1)
                ch = q.pop(0)
                if not q:
                    del voq[dst]
                return ch
        return None

    def _uplink_done(self, p: int, src: int, ch: _Chunk) -> None:
        self._uplink_busy[p][src] = False
        # chunk traverses uplink prop + switch pipeline, then enters output queue
        self.eng.after(self.cfg.d_prop + self.cfg.l_switch,
                       lambda: self._enter_outq(p, ch))
        self._poke_uplink(p, src)

    # ---- switch output / downlink ------------------------------------
    def _enter_outq(self, p: int, ch: _Chunk) -> None:
        dst = ch.flow.dst
        if self.cfg.lossy and self.cfg.buffer_bytes is not None:
            if self._occ[p][dst] + ch.nbytes > self.cfg.buffer_bytes + 1e-9:
                # buffer overflow -> drop, free credit, retransmit after RTO
                self._inflight[p][dst] -= ch.nbytes
                self._wake_uplinks_for_dst(p, dst)
                self.eng.after(self.cfg.rto, lambda: self._make_ready(ch))
                return
            self._occ[p][dst] += ch.nbytes
        self._outq[p][dst].append(ch)
        self._poke_downlink(p, dst)

    def _poke_downlink(self, p: int, dst: int) -> None:
        if self._downlink_busy[p][dst]:
            return
        q = self._outq[p][dst]
        if not q:
            return
        ch = q.pop(0)
        self._downlink_busy[p][dst] = True
        dur = self.cfg.serialize(ch.nbytes)
        self.eng.after(dur, lambda: self._downlink_done(p, dst, ch))

    def _downlink_done(self, p: int, dst: int, ch: _Chunk) -> None:
        self._downlink_busy[p][dst] = False
        # free switch buffer now (chunk transmitted out of switch)
        self._occ[p][dst] -= ch.nbytes
        # delivery to node after downlink propagation
        self.eng.after(self.cfg.d_prop, lambda: self._deliver(p, dst, ch))
        # buffer freed -> previously HOL-blocked uplinks may proceed
        self._wake_uplinks_for_dst(p, dst)
        self._poke_downlink(p, dst)

    def _deliver(self, p: int, dst: int, ch: _Chunk) -> None:
        # free credit (receiver consumed) -> wake uplinks
        self._inflight[p][dst] -= ch.nbytes
        self._wake_uplinks_for_dst(p, dst)
        f = ch.flow
        f.chunks_done += 1
        if f.chunks_done >= f.chunks_total:
            f.done_time = self.eng.now
        self._pending -= 1

    def _wake_uplinks_for_dst(self, p: int, dst: int) -> None:
        # any source that has traffic to dst (or is HOL-blocked) may now proceed
        for src in range(self.cfg.n_nodes):
            if not self._uplink_busy[p][src]:
                self._poke_uplink(p, src)

    # ---- run ----------------------------------------------------------
    def run(self) -> None:
        self._split()
        self.eng.run()
        if self._pending != 0:
            raise RuntimeError(f"deadlock: {self._pending} chunks undelivered "
                               f"(buffer/credit too small?)")
