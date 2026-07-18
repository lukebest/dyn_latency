"""Verification experiments V1..V7 for docs/ub_request_grant.md.

Mapping to document chapters:
  V1  §1.3      Koenig lower bound attainment (balanced all-to-all)
  V2  §2.10     skew insensitivity: backlog bound & pre-compensation
  V3  §3        single-layer 128x8: completion time, backlog bound, jitter,
                hotspot non-spreading
  V4  §4        two-layer 1024: completion time, three-segment backlog bounds,
                spine balance
  V5  §2.7/§6   credit window C: RTT hiding, incast 1023->1, source overload
                (work conservation, no HOL spreading)
  V6  §2.9/§4.9 BSP cursor barrier release latency
  V7  §7/§8     R/G vs free-injection baseline: step time min/mean/p99, jitter,
                switch buffer O(1) vs O(M)

Usage: python3 -m rg_sim.run_verify [--quick]
Outputs: results_rg/verify.json + PNGs
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from rg_sim.sim import (Params, simulate, balanced_tokens, uniform_tokens,
                        hotspot_tokens, incast_tokens, overload_tokens)

OUT = os.path.join(os.path.dirname(__file__), "..", "results_rg")
US = 1e-3  # ns -> us


def _p(topology: str, N: int, mode: str, **kw) -> Params:
    # C matched to the measured grant->egress-forward loop (doc §2.10 item 5):
    # single ~6 tau_g, two-layer ~13 tau_g
    base = dict(topology=topology, n_nodes=N, n_planes=8, mode=mode,
                credit=8 if topology == "single" else 14)
    if topology == "two":
        base.update(req_delay_ns=550.0, gnt_delay_ns=550.0)
    base.update(kw)
    return Params(**base)


def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if not isinstance(v, np.ndarray)}


# ------------------------------------------------------------------ V1

def v1_koenig(quick: bool) -> dict:
    """Balanced all-to-all: RG makespan should hit Koenig bound + O(RTT)."""
    print("V1: Koenig bound attainment")
    out = []
    for N, per in [(32, 1), (32, 4), (64, 2), (128, 1)]:
        tr = balanced_tokens(N, per)
        r = simulate(_p("single", N, "rg", start_skew_ns=0.0, skew_max_ns=0.0,
                        dma_jit_ns=0.0), tr)
        overhead = r["makespan_ns"] - r["koenig_bound_ns"]
        out.append({"N": N, "per_pair": per, "grains": tr.n,
                    "koenig_us": r["koenig_bound_ns"] * US,
                    "makespan_us": r["makespan_ns"] * US,
                    "overhead_us": overhead * US,
                    "wait_net_max_ns": r["wait_net_max_ns"]})
        print(f"  N={N} per={per}: koenig={r['koenig_bound_ns']*US:.2f}us "
              f"makespan={r['makespan_ns']*US:.2f}us overhead={overhead*US:.2f}us "
              f"net_wait_max={r['wait_net_max_ns']:.0f}ns")
    return {"rows": out}


# ------------------------------------------------------------------ V2

def v2_skew(quick: bool) -> dict:
    """Cable-skew sweep with/without pre-compensation (§2.10)."""
    print("V2: skew insensitivity")
    N, M = 64, 128
    skews = [0, 100, 200, 400, 800]
    rows = []
    for sk in skews:
        for pre in (False, True):
            tr = uniform_tokens(N, M, seed=3)
            C = 8
            r = simulate(_p("single", N, "rg", credit=C, skew_max_ns=float(sk),
                            precomp=pre, seed=3), tr)
            tau = r["tau_ns"]
            bound = (C + np.ceil(sk / tau) + 1) * tau
            rows.append({"skew_ns": sk, "precomp": pre,
                         "makespan_us": r["makespan_ns"] * US,
                         "egress_wait_max_ns": r["stage_wait_max_ns"][-1],
                         "egress_backlog_grain": r["stage_wait_max_ns"][-1] / tau,
                         "bound_grain": C + np.ceil(sk / tau) + 1,
                         "net_lat_std_ns": r["net_lat_std_ns"],
                         "within_bound": bool(r["stage_wait_max_ns"][-1] <= bound)})
            print(f"  skew={sk}ns precomp={pre}: makespan={r['makespan_ns']*US:.2f}us "
                  f"egress_backlog={r['stage_wait_max_ns'][-1]/tau:.1f}g "
                  f"(bound {C + np.ceil(sk/tau) + 1:.0f}g) "
                  f"lat_std={r['net_lat_std_ns']:.0f}ns")
    return {"rows": rows}


# ------------------------------------------------------------------ V3

def v3_single_layer(quick: bool) -> dict:
    """Single-layer 128x8 (§3): EP128 case + hotspot non-spreading."""
    print("V3: single-layer 128x8")
    N = 128
    M = 256 if quick else 1024
    tr = uniform_tokens(N, M, seed=5)
    rr = simulate(_p("single", N, "rg", seed=5), tr)
    rb = simulate(_p("single", N, "base", seed=5), tr)
    tau = rr["tau_ns"]
    doc_pred_us = (M / 8) * tau * US  # doc §3.6: 128 grain/port -> 18.3us serialize
    ep = {"M": M, "koenig_us": rr["koenig_bound_ns"] * US,
          "rg_makespan_us": rr["makespan_ns"] * US,
          "base_makespan_us": rb["makespan_ns"] * US,
          "doc_serialize_floor_us": doc_pred_us,
          "rg_egress_backlog_grain": rr["stage_wait_max_ns"][-1] / tau,
          "base_egress_backlog_grain": rb["stage_wait_max_ns"][-1] / tau,
          "rg_net_lat_p99_us": rr["net_lat_p99_ns"] * US,
          "rg_net_lat_std_ns": rr["net_lat_std_ns"],
          "rg_barrier_release_us": (rr["barrier_ns"] - rr["makespan_ns"]) * US}
    print(f"  EP128 M={M}: koenig={ep['koenig_us']:.1f}us rg={ep['rg_makespan_us']:.1f}us "
          f"base={ep['base_makespan_us']:.1f}us  rg_backlog={ep['rg_egress_backlog_grain']:.1f}g "
          f"base_backlog={ep['base_egress_backlog_grain']:.0f}g")

    # hotspot: completion of cold destinations must not degrade (no spreading)
    hot_rows = []
    Mh = 128 if quick else 256
    for rho in (0.0, 0.2, 0.5):
        trh = hotspot_tokens(N, Mh, rho, hot=0, seed=6)
        r = simulate(_p("single", N, "rg", seed=6), trh)
        per = r["per_dst_done_ns"]
        cold = np.delete(per, 0)
        hot_load = int((trh.dst == 0).sum())
        hot_rows.append({"rho": rho, "hot_load_grain": hot_load,
                         "hot_done_us": per[0] * US,
                         "hot_floor_us": hot_load / 8 * tau * US,
                         "cold_p99_us": float(np.percentile(cold, 99)) * US,
                         "cold_mean_us": float(cold.mean()) * US})
        print(f"  hotspot rho={rho}: hot_load={hot_load}g hot_done={per[0]*US:.1f}us "
              f"(floor {hot_load/8*tau*US:.1f}us) cold_p99={np.percentile(cold,99)*US:.1f}us")
    return {"ep128": ep, "hotspot": hot_rows}


# ------------------------------------------------------------------ V4

def v4_two_layer(quick: bool) -> dict:
    """Two-layer 1024 NPU (§4): EP1024 case, backlog bounds, spine balance."""
    print("V4: two-layer 1024 NPU")
    N = 1024
    M = 64 if quick else 1024
    tr = uniform_tokens(N, M, seed=7)
    t0 = time.time()
    C = 14
    rr = simulate(_p("two", N, "rg", credit=C, seed=7), tr)
    rb = simulate(_p("two", N, "base", base_path="hash", seed=7), tr)
    tau = rr["tau_ns"]
    # doc §4.5 bounds with delta <= 2 tau: uplink C+d+2, spine d+2, downlink C+d+1
    bounds = [None, C + 4, 4, C + 3]
    row = {"M": M, "grains": tr.n, "sim_s": round(time.time() - t0, 1),
           "koenig_us": rr["koenig_bound_ns"] * US,
           "rg_makespan_us": rr["makespan_ns"] * US,
           "base_hash_makespan_us": rb["makespan_ns"] * US,
           "rg_stage_backlog_grain": [w / tau for w in rr["stage_wait_max_ns"]],
           "doc_backlog_bound_grain": bounds,
           "rg_spine_up_max": rr["spine_up_max"], "rg_spine_up_mean": rr["spine_up_mean"],
           "rg_spine_down_max": rr["spine_down_max"], "rg_spine_down_mean": rr["spine_down_mean"],
           "base_spine_up_max": rb["spine_up_max"], "base_spine_down_max": rb["spine_down_max"],
           "rg_net_lat_p99_us": rr["net_lat_p99_ns"] * US,
           "rg_barrier_release_us": (rr["barrier_ns"] - rr["makespan_ns"]) * US}
    print(f"  EP1024 M={M}: koenig={row['koenig_us']:.1f}us rg={row['rg_makespan_us']:.1f}us "
          f"base_hash={row['base_hash_makespan_us']:.1f}us")
    print(f"  rg stage backlog (grain): {[f'{x:.1f}' for x in row['rg_stage_backlog_grain']]} "
          f"vs doc bounds {row['doc_backlog_bound_grain']}")
    print(f"  spine load rg up/down max {row['rg_spine_up_max']}/{row['rg_spine_down_max']} "
          f"(mean {row['rg_spine_up_mean']:.1f}) | base hash {row['base_spine_up_max']}/{row['base_spine_down_max']}")
    return {"row": row}


# ------------------------------------------------------------------ V5

def v5_credit(quick: bool) -> dict:
    """Credit window sweep + incast + source overload (§2.7, §6.3, §6.8)."""
    print("V5: credit window / incast / overload")
    # (a) C sweep on two-layer: RTT hiding needs C >= ceil(RTT/tau) ~ 8
    N = 128
    M = 64
    tr = uniform_tokens(N, M, seed=9)
    c_rows = []
    for C in (1, 2, 4, 8, 12, 16):
        r = simulate(_p("two", N, "rg", credit=C, seed=9), tr)
        c_rows.append({"C": C, "makespan_us": r["makespan_ns"] * US,
                       "koenig_us": r["koenig_bound_ns"] * US})
        print(f"  C={C}: makespan={r['makespan_ns']*US:.2f}us (koenig {r['koenig_bound_ns']*US:.2f}us)")

    # (b) incast 127->1 on single-layer: dst receives at 8x line rate, bounded buffer
    tri = incast_tokens(128, 16)
    ri = simulate(_p("single", 128, "rg", seed=9), tri)
    tau = ri["tau_ns"]
    incast = {"grains": tri.n, "koenig_us": ri["koenig_bound_ns"] * US,
              "makespan_us": ri["makespan_ns"] * US,
              "egress_backlog_grain": ri["stage_wait_max_ns"][-1] / tau}
    print(f"  incast 127->1x16: koenig={incast['koenig_us']:.1f}us "
          f"makespan={incast['makespan_us']:.1f}us backlog={incast['egress_backlog_grain']:.1f}g")

    # (c) overload: src 0 oversubscribed (all its 8 ports full); others unaffected
    N = 128
    tro = overload_tokens(N, M_bg=32, hot_src=0, M_hot=2048, seed=9)
    ro = simulate(_p("single", N, "rg", seed=9), tro)
    # completion of grains NOT from hot source
    others = ro["per_dst_done_ns"]  # per-dst; instead compare vs no-overload run
    tr_no = uniform_tokens(N, 32, seed=9)
    rn = simulate(_p("single", N, "rg", seed=9), tr_no)
    over = {"hot_src_load_grain": int((tro.src == 0).sum()),
            "makespan_us": ro["makespan_ns"] * US,
            "koenig_us": ro["koenig_bound_ns"] * US,
            "baseline_no_hot_makespan_us": rn["makespan_ns"] * US,
            "koenig_no_hot_us": rn["koenig_bound_ns"] * US}
    print(f"  overload src0={over['hot_src_load_grain']}g: makespan={over['makespan_us']:.1f}us "
          f"(koenig {over['koenig_us']:.1f}us); no-hot ref makespan={over['baseline_no_hot_makespan_us']:.1f}us")
    return {"credit_sweep": c_rows, "incast": incast, "overload": over}


# ------------------------------------------------------------------ V6

def v6_barrier(quick: bool) -> dict:
    """Cursor barrier release latency after last grain (§2.9/§3.7/§4.9)."""
    print("V6: barrier release latency")
    rows = []
    for topo, N, M in [("single", 128, 128), ("two", 128, 64), ("two", 1024, 32)]:
        tr = uniform_tokens(N, M, seed=11)
        r = simulate(_p(topo, N, "rg", seed=11), tr)
        rel = (r["barrier_ns"] - r["makespan_ns"]) * US
        rows.append({"topology": topo, "N": N, "M": M,
                     "makespan_us": r["makespan_ns"] * US,
                     "barrier_us": r["barrier_ns"] * US,
                     "release_us": rel})
        print(f"  {topo} N={N}: last-grain->barrier = {rel:.2f}us")
    return {"rows": rows}


# ------------------------------------------------------------------ V7

def v7_compare(quick: bool) -> dict:
    """R/G vs free injection: step-time stats over seeds (§8)."""
    print("V7: R/G vs traditional free injection")
    rng = np.random.default_rng(0)
    n_seed = 4 if quick else 10
    groups = [("single", 128, 16), ("single", 128, 64), ("single", 128, 1024),
              ("two", 1024, 16), ("two", 1024, 64)]
    if not quick:
        groups.append(("two", 1024, 256))
    rows = []
    for topo, N, M in groups:
        seeds = range(n_seed if (topo == "single" or M <= 64) else max(3, n_seed // 3))
        rec: dict[str, list] = {k: [] for k in
                                ("rg_land", "rg_step", "b_land", "b_step",
                                 "rg_buf", "b_buf")}
        for sd in seeds:
            tr = uniform_tokens(N, M, seed=100 + sd)
            rr = simulate(_p(topo, N, "rg", seed=sd), tr)
            rb = simulate(_p(topo, N, "base",
                             base_path="hash" if topo == "two" else "spray",
                             seed=sd), tr)
            tau = rr["tau_ns"]
            # software barrier for baseline (doc §8.3/§8.8 assumptions)
            sw = rng.triangular(*((1500, 2000, 3000) if topo == "single"
                                  else (3000, 4000, 6000)))
            rec["rg_land"].append(rr["makespan_ns"] * US)
            rec["rg_step"].append(rr["barrier_ns"] * US)
            rec["b_land"].append(rb["makespan_ns"] * US)
            rec["b_step"].append((rb["makespan_ns"] + sw) * US)
            rec["rg_buf"].append(max(rr["stage_wait_max_ns"][1:]) / tau)
            rec["b_buf"].append(max(rb["stage_wait_max_ns"][1:]) / tau)
        row = {"topology": topo, "N": N, "M": M, "seeds": len(rec["rg_land"])}
        for k, v in rec.items():
            a = np.array(v)
            row[k] = {"min": float(a.min()), "mean": float(a.mean()),
                      "p99": float(np.percentile(a, 99)), "std": float(a.std())}
        rows.append(row)
        print(f"  {topo} N={N} M={M}: step rg mean={row['rg_step']['mean']:.1f} "
              f"p99={row['rg_step']['p99']:.1f} std={row['rg_step']['std']:.2f} | "
              f"base mean={row['b_step']['mean']:.1f} p99={row['b_step']['p99']:.1f} "
              f"std={row['b_step']['std']:.2f} | buf(g) rg={row['rg_buf']['mean']:.1f} "
              f"base={row['b_buf']['mean']:.0f}")
    return {"rows": rows}


# ------------------------------------------------------------------ plots

def make_plots(res: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # P1: V2 skew
    rows = res["V2"]["rows"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for pre, c in ((False, "#d62728"), (True, "#2ca02c")):
        sel = [r for r in rows if r["precomp"] == pre]
        x = [r["skew_ns"] for r in sel]
        axes[0].plot(x, [r["egress_backlog_grain"] for r in sel], "o-", color=c,
                     label=f"precomp={pre}")
        axes[1].plot(x, [r["net_lat_std_ns"] for r in sel], "s-", color=c,
                     label=f"precomp={pre}")
    axes[0].plot([r["skew_ns"] for r in rows if not r["precomp"]],
                 [r["bound_grain"] for r in rows if not r["precomp"]],
                 "k--", label="bound C+ceil(sk/tau)+1")
    axes[0].set_xlabel("cable skew max (ns)"); axes[0].set_ylabel("egress backlog (grain)")
    axes[0].set_title("V2 egress backlog vs skew"); axes[0].legend(); axes[0].grid(alpha=.3)
    axes[1].set_xlabel("cable skew max (ns)"); axes[1].set_ylabel("net latency std (ns)")
    axes[1].set_title("V2 latency jitter vs skew"); axes[1].legend(); axes[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "v2_skew.png"), dpi=130); plt.close(fig)

    # P2: V5 credit sweep
    rows = res["V5"]["credit_sweep"]
    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.plot([r["C"] for r in rows], [r["makespan_us"] for r in rows], "o-",
            color="#1f77b4", label="RG makespan")
    ax.axhline(rows[0]["koenig_us"], ls="--", color="k", label="Koenig bound")
    ax.set_xlabel("credit window C"); ax.set_ylabel("makespan (us)")
    ax.set_title("V5 RTT hiding: makespan vs credit window (two-layer, N=128, M=64)")
    ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "v5_credit.png"), dpi=130); plt.close(fig)

    # P3: V7 step comparison
    rows = res["V7"]["rows"]
    labels = [f"{r['topology'][0].upper()}{r['N']}\nM={r['M']}" for r in rows]
    x = np.arange(len(rows)); w = 0.35
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    axes[0].bar(x - w/2, [r["rg_step"]["mean"] for r in rows], w, color="#1f77b4",
                label="R/G step mean")
    axes[0].bar(x + w/2, [r["b_step"]["mean"] for r in rows], w, color="#d62728",
                label="baseline step mean")
    axes[0].errorbar(x - w/2, [r["rg_step"]["mean"] for r in rows],
                     yerr=[r["rg_step"]["std"] for r in rows], fmt="none", ecolor="k")
    axes[0].errorbar(x + w/2, [r["b_step"]["mean"] for r in rows],
                     yerr=[r["b_step"]["std"] for r in rows], fmt="none", ecolor="k")
    axes[0].set_xticks(x); axes[0].set_xticklabels(labels, fontsize=8)
    axes[0].set_ylabel("complete cursor step (us)"); axes[0].set_yscale("log")
    axes[0].set_title("V7 step time (mean +/- std)"); axes[0].legend(); axes[0].grid(alpha=.3)
    axes[1].bar(x - w/2, [r["rg_buf"]["mean"] for r in rows], w, color="#1f77b4",
                label="R/G switch backlog")
    axes[1].bar(x + w/2, [r["b_buf"]["mean"] for r in rows], w, color="#d62728",
                label="baseline switch backlog")
    axes[1].set_xticks(x); axes[1].set_xticklabels(labels, fontsize=8)
    axes[1].set_ylabel("max switch backlog (grain)"); axes[1].set_yscale("log")
    axes[1].set_title("V7 switch buffer need: O(1) vs O(M)")
    axes[1].legend(); axes[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "v7_compare.png"), dpi=130); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    res = {"V1": v1_koenig(args.quick), "V2": v2_skew(args.quick),
           "V3": v3_single_layer(args.quick), "V4": v4_two_layer(args.quick),
           "V5": v5_credit(args.quick), "V6": v6_barrier(args.quick),
           "V7": v7_compare(args.quick)}
    with open(os.path.join(OUT, "verify.json"), "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    make_plots(res)
    print(f"\nDone in {time.time()-t0:.0f}s -> results_rg/verify.json + PNGs")


if __name__ == "__main__":
    main()
