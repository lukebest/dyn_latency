"""DeepSeek-V4-Pro MoE EP workload generator (dispatch + combine).

Produces a per-(src_rank -> dst_rank) token-expert count matrix from a routing
draw with a configurable hotspot, then derives dispatch and combine byte flows.

Grounded in:
  * DeepSeek-V4-MoE通信完整流程 §3, §5.2 (top-6, H=7168, FP8 dispatch ~7KB,
    BF16 combine ~14KB per token-expert)
  * SHMEM-POP技术分档 §1.12.2 (EP=R ranks, batch B, Zipf/explicit hotspot)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class MoEConfig:
    n_ranks: int = 16          # EP width R == number of nodes
    experts: int = 384
    top_k: int = 6
    batch: int = 32            # tokens per rank (Decode chat)
    hidden: int = 7168         # H
    dispatch_bytes_per_te: int = 7168     # FP8 activation, H bytes
    combine_bytes_per_te: int = 14336     # BF16 output, 2H bytes
    # hotspot: a set of hot experts (placed on a single hot rank) absorbs
    # fraction `rho_h` of all token-expert selections.
    rho_h: float = 0.5
    hot_experts: int = 4
    hot_rank: int = 0
    seed: int = 0

    @property
    def experts_per_rank(self) -> int:
        return self.experts // self.n_ranks


@dataclass
class Routing:
    cfg: MoEConfig
    count: np.ndarray   # [R,R] token-expert count from src rank i to dst rank j

    def dispatch_bytes(self) -> np.ndarray:
        b = self.count.astype(float) * self.cfg.dispatch_bytes_per_te
        np.fill_diagonal(b, 0.0)   # local experts: no network
        return b

    def combine_bytes(self) -> np.ndarray:
        # expert rank j sends results back to origin rank i
        b = self.count.T.astype(float) * self.cfg.combine_bytes_per_te
        np.fill_diagonal(b, 0.0)
        return b

    def tokens_local(self) -> np.ndarray:
        """token-expert items processed by each rank (for expert compute)."""
        return self.count.sum(axis=0)


def expert_to_rank(cfg: MoEConfig) -> np.ndarray:
    epr = cfg.experts_per_rank
    return np.arange(cfg.experts) // epr  # contiguous block placement


def draw_routing(cfg: MoEConfig) -> Routing:
    rng = np.random.default_rng(cfg.seed)
    R = cfg.n_ranks
    e2r = expert_to_rank(cfg)

    # hot expert ids live on hot_rank's block
    epr = cfg.experts_per_rank
    hot_base = cfg.hot_rank * epr
    hot_ids = np.arange(hot_base, min(hot_base + cfg.hot_experts, hot_base + epr))
    all_ids = np.arange(cfg.experts)

    count = np.zeros((R, R), dtype=np.int64)
    for src in range(R):
        for _ in range(cfg.batch):
            chosen: set[int] = set()
            # draw top_k distinct experts with hotspot bias
            guard = 0
            while len(chosen) < cfg.top_k and guard < 1000:
                guard += 1
                if rng.random() < cfg.rho_h and len(hot_ids) > 0:
                    e = int(rng.choice(hot_ids))
                else:
                    e = int(rng.integers(0, cfg.experts))
                chosen.add(e)
            for e in chosen:
                dst = int(e2r[e])
                count[src, dst] += 1
    return Routing(cfg=cfg, count=count)
