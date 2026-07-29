#!/usr/bin/env python3
"""Generate node/topology/routing CSV for UB_RG packet experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write_network_attribute(out: Path) -> None:
    # Buffer sizing: 256KB per 400Gbps port/VL (exclusive CBFC).
    # CbfcInitCreditCell = floor(256KiB / 160B cell) = 1638.
    # CbfcCtrlCrdRtrThldCell must stay well under that credit: dispatch is
    # unidirectional, so credit can only come back via forced control frames.
    out.write_text(
        """default ns3::UbApp::EnableMultiPath "false"
default ns3::UbApp::UseShortestPaths "true"
default ns3::UbApp::UsePacketSpray "false"
default ns3::UbLink::Delay "+50ns"
default ns3::UbPort::UbDataRate "400Gbps"
default ns3::UbPort::UbInterframeGap "+0ns"
default ns3::UbPort::CbfcInitCreditCell "1638"
default ns3::UbPort::CbfcCtrlCrdRtrThldCell "192"
default ns3::UbPort::PfcUpThld "204800"
default ns3::UbPort::PfcLowThld "163840"
default ns3::UbQueueManager::ReservePerQueueBytes "262144"
default ns3::UbQueueManager::SharedPoolBytes "0"
default ns3::UbSwitch::FlowControl "CBFC"
default ns3::UbSwitch::InPortProcessingDelay "+150ns"
default ns3::UbSwitchAllocator::AllocationTime "+10ns"
default ns3::UbTransportChannel::EnableRetrans "false"
default ns3::UbTransportChannel::UsePacketSpray "false"
default ns3::UbTransportChannel::UseShortestPaths "true"
default ns3::UbJetty::UbJettyInflightMax "100000"
global UB_CC_ENABLED "false"
global UB_TRACE_ENABLE "false"
global UB_TASK_TRACE_ENABLE "false"
global UB_PACKET_TRACE_ENABLE "false"
global UB_PORT_TRACE_ENABLE "false"
global UB_PARSE_TRACE_ENABLE "false"
global UB_QUEUE_TRACE_ENABLE "false"
""",
        encoding="utf-8",
    )


def write_traffic_stub(out_dir: Path) -> None:
    (out_dir / "traffic.csv").write_text(
        "taskId,sourceNode,destNode,dataSize(Byte),opType,priority,delay,phaseId,dependOnPhases\n",
        encoding="utf-8",
    )


def gen_scenario1(out_dir: Path, n: int = 128) -> None:
    """Single-layer: N NPUs x 8 uplinks -> 8 x N-port switches."""
    out_dir.mkdir(parents=True, exist_ok=True)
    planes = 8
    sw0 = n
    with (out_dir / "node.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,nodeType,portNum,allocationDelay,forwardDelay\n")
        f.write(f"0..{n-1},DEVICE,{planes},10ns,150ns\n")
        f.write(f"{sw0}..{sw0+planes-1},SWITCH,{n},10ns,150ns\n")
    with (out_dir / "topology.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId1,portId1,nodeId2,portId2,bandwidth,delay\n")
        for i in range(n):
            for p in range(planes):
                f.write(f"{i},{p},{sw0+p},{i},400Gbps,50ns\n")
    with (out_dir / "routing_table.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,dstNodeId,dstPortId,outPorts,metrics\n")
        for p in range(planes):
            sw = sw0 + p
            for d in range(n):
                f.write(f"{sw},{d},0,{d},3\n")
        ports = " ".join(str(p) for p in range(planes))
        metrics = " ".join(["3"] * planes)
        for i in range(n):
            for d in range(n):
                if i == d:
                    continue
                f.write(f"{i},{d},0,{ports},{metrics}\n")
    write_network_attribute(out_dir / "network_attribute.txt")
    write_traffic_stub(out_dir)
    print(f"Wrote scenario1 n={n} -> {out_dir}")


def gen_scenario1_mini(out_dir: Path) -> None:
    """4 NPU x 2 planes x SW4 — protocol smoke topology."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n, planes = 4, 2
    sw0 = n
    with (out_dir / "node.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,nodeType,portNum,allocationDelay,forwardDelay\n")
        f.write(f"0..{n-1},DEVICE,{planes},10ns,150ns\n")
        f.write(f"{sw0}..{sw0+planes-1},SWITCH,{n},10ns,150ns\n")
    with (out_dir / "topology.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId1,portId1,nodeId2,portId2,bandwidth,delay\n")
        for i in range(n):
            for p in range(planes):
                f.write(f"{i},{p},{sw0+p},{i},400Gbps,50ns\n")
    with (out_dir / "routing_table.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,dstNodeId,dstPortId,outPorts,metrics\n")
        for p in range(planes):
            for d in range(n):
                f.write(f"{sw0+p},{d},0,{d},3\n")
        for i in range(n):
            for d in range(n):
                if i == d:
                    continue
                ports = " ".join(str(p) for p in range(planes))
                metrics = " ".join(["3"] * planes)
                f.write(f"{i},{d},0,{ports},{metrics}\n")
    write_network_attribute(out_dir / "network_attribute.txt")
    write_traffic_stub(out_dir)
    print(f"Wrote mini topology -> {out_dir}")


def gen_clos(out_dir: Path, npu: int = 1024, isolated_planes: bool = False) -> None:
    """Two-tier Clos: npu + 128 leaf + 64 spine. Leaf 64 down / 64 up."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n_leaf, n_spine = 128, 64
    leaf0 = npu
    spine0 = npu + n_leaf
    with (out_dir / "node.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,nodeType,portNum,allocationDelay,forwardDelay\n")
        f.write(f"0..{npu-1},DEVICE,8,10ns,150ns\n")
        f.write(f"{leaf0}..{leaf0+n_leaf-1},SWITCH,128,10ns,150ns\n")
        f.write(f"{spine0}..{spine0+n_spine-1},SWITCH,128,10ns,150ns\n")
    with (out_dir / "topology.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId1,portId1,nodeId2,portId2,bandwidth,delay\n")
        for n in range(npu):
            g = n // 64
            m = n % 64
            for p in range(8):
                leaf = leaf0 + 8 * g + p
                f.write(f"{n},{p},{leaf},{m},400Gbps,50ns\n")
        for li in range(n_leaf):
            leaf = leaf0 + li
            for s in range(n_spine):
                f.write(f"{leaf},{64+s},{spine0+s},{li},400Gbps,50ns\n")
    with (out_dir / "routing_table.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,dstNodeId,dstPortId,outPorts,metrics\n")
        for li in range(n_leaf):
            leaf = leaf0 + li
            g = li // 8
            plane = li % 8
            # local NPUs
            for m in range(64):
                d = g * 64 + m
                if d >= npu:
                    continue
                f.write(f"{leaf},{d},0,{m},3\n")
            if isolated_planes:
                # Stay in-plane: only spines with s%8 == plane
                spine_ports = " ".join(str(64 + s) for s in range(n_spine) if s % 8 == plane)
                spine_metrics = " ".join(["3"] * (n_spine // 8))
            else:
                spine_ports = " ".join(str(64 + s) for s in range(n_spine))
                spine_metrics = " ".join(["3"] * n_spine)
            for dg in range(16):
                if dg == g:
                    continue
                d0 = dg * 64
                d1 = min(npu, dg * 64 + 64) - 1
                if d0 >= npu:
                    continue
                f.write(f"{leaf},{d0}..{d1},0,{spine_ports},{spine_metrics}\n")
        for s in range(n_spine):
            spine = spine0 + s
            for d in range(npu):
                g = d // 64
                if isolated_planes:
                    plane = s % 8
                else:
                    plane = d % 8
                leaf_idx = 8 * g + plane
                f.write(f"{spine},{d},0,{leaf_idx},3\n")
        if isolated_planes:
            # Single preferred plane uplink per (src,dst)
            for n in range(npu):
                for d in range(npu):
                    if n == d:
                        continue
                    plane = ((n // 64) + (d // 64)) % 8
                    f.write(f"{n},{d},0,{plane},3\n")
        else:
            ports = " ".join(str(p) for p in range(8))
            metrics = " ".join(["3"] * 8)
            f.write(f"0..{npu-1},0..{npu-1},0,{ports},{metrics}\n")
    write_network_attribute(out_dir / "network_attribute.txt")
    write_traffic_stub(out_dir)
    tag = "scenario3-isolated" if isolated_planes else "scenario2"
    print(f"Wrote {tag} npu={npu} -> {out_dir}")


def gen_sparse_clos(out_dir: Path, npu: int = 512) -> None:
    """Scenario 4 Sparse CLOS: 8 Cluster × 64 Server, 32×SW128, 15 ports/NPU.

    NPU id = cluster*64 + server (cluster,server in 0..7 / 0..63), matching
    behavioral ClusterOf/ServerOf. Ports: 0..6 = PFM to other clusters on the
    same server; 7..14 = uplink P1..P8. See docs/场景4_Sparse_CLOS_512P_设计说明.md.
    """
    if npu <= 0 or npu > 512:
        raise SystemExit("sparse clos ep-size must be in 1..512")
    out_dir.mkdir(parents=True, exist_ok=True)
    n_cluster, n_server = 8, 64
    full_n = n_cluster * n_server
    # (a,b,is_S,p_a,p_b) — 0-indexed clusters; p_* are 1..8 uplink indices
    sw_edges = [
        (0, 1, False, 1, 1),
        (0, 1, True, 2, 2),
        (0, 2, False, 3, 1),
        (0, 3, False, 4, 1),
        (0, 4, False, 5, 1),
        (0, 5, False, 6, 1),
        (0, 6, False, 7, 1),
        (0, 7, False, 8, 1),
        (2, 3, False, 2, 2),
        (2, 3, True, 3, 3),
        (1, 2, False, 3, 4),
        (1, 3, False, 4, 4),
        (1, 4, False, 5, 2),
        (1, 5, False, 6, 2),
        (1, 6, False, 7, 2),
        (1, 7, False, 8, 2),
        (4, 5, False, 3, 3),
        (4, 5, True, 4, 4),
        (2, 4, False, 5, 5),
        (2, 5, False, 6, 5),
        (2, 6, False, 7, 3),
        (2, 7, False, 8, 3),
        (3, 4, False, 5, 6),
        (3, 5, False, 6, 6),
        (3, 6, False, 7, 4),
        (3, 7, False, 8, 4),
        (6, 7, False, 5, 5),
        (6, 7, True, 6, 6),
        (4, 6, False, 7, 7),
        (4, 7, False, 8, 7),
        (5, 6, False, 7, 8),
        (5, 7, False, 8, 8),
    ]
    assert len(sw_edges) == 32
    # Intra-cluster uplink P index (1..8) per cluster
    intra_p = {0: 2, 1: 2, 2: 3, 3: 3, 4: 4, 5: 4, 6: 6, 7: 6}

    def npu_id(c: int, s: int) -> int:
        return c * n_server + s

    def pfm_port(src_c: int, dst_c: int) -> int:
        # Compact the other-7 clusters into ports 0..6
        assert src_c != dst_c
        return dst_c if dst_c < src_c else dst_c - 1

    def uplink_port(p: int) -> int:
        return 6 + p  # P1..P8 -> ports 7..14

    sw0 = full_n
    # node.csv: always declare full 512 NPUs + 32 SW; ep-size clips active traffic.
    with (out_dir / "node.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,nodeType,portNum,allocationDelay,forwardDelay\n")
        f.write(f"0..{full_n - 1},DEVICE,15,10ns,150ns\n")
        f.write(f"{sw0}..{sw0 + 31},SWITCH,128,10ns,150ns\n")

    # Topology: PFM mesh per server + NPU↔SW uplinks
    with (out_dir / "topology.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId1,portId1,nodeId2,portId2,bandwidth,delay\n")
        for s in range(n_server):
            for c1 in range(n_cluster):
                for c2 in range(n_cluster):
                    if c1 >= c2:
                        continue
                    a, b = npu_id(c1, s), npu_id(c2, s)
                    f.write(
                        f"{a},{pfm_port(c1, c2)},{b},{pfm_port(c2, c1)},400Gbps,50ns\n"
                    )
        for sw_i, (ca, cb, _is_s, pa, pb) in enumerate(sw_edges):
            sw = sw0 + sw_i
            for s in range(n_server):
                # side A: ports 0..63, side B: ports 64..127
                f.write(
                    f"{npu_id(ca, s)},{uplink_port(pa)},{sw},{s},400Gbps,50ns\n"
                )
                f.write(
                    f"{npu_id(cb, s)},{uplink_port(pb)},{sw},{64 + s},400Gbps,50ns\n"
                )

    # Cross (src_c,dst_c) -> (uplink P, sw_index) for non-S edges
    cross: dict[tuple[int, int], tuple[int, int]] = {}
    intra_sw: dict[int, int] = {}
    for sw_i, (ca, cb, is_s, pa, pb) in enumerate(sw_edges):
        if is_s:
            intra_sw[ca] = sw_i
            intra_sw[cb] = sw_i
            continue
        cross[(ca, cb)] = (pa, sw_i)
        cross[(cb, ca)] = (pb, sw_i)

    with (out_dir / "routing_table.csv").open("w", encoding="utf-8") as f:
        f.write("nodeId,dstNodeId,dstPortId,outPorts,metrics\n")
        # SW: local downlinks only (unique path)
        for sw_i, (ca, cb, _is_s, _pa, _pb) in enumerate(sw_edges):
            sw = sw0 + sw_i
            for s in range(n_server):
                f.write(f"{sw},{npu_id(ca, s)},0,{s},3\n")
                f.write(f"{sw},{npu_id(cb, s)},0,{64 + s},3\n")
        # NPU routes (only among first npu endpoints used by experiments)
        for src in range(npu):
            sc, ss = src // n_server, src % n_server
            for dst in range(npu):
                if src == dst:
                    continue
                dc, ds = dst // n_server, dst % n_server
                if ss == ds and sc != dc:
                    out_p = pfm_port(sc, dc)
                elif sc == dc and ss != ds:
                    out_p = uplink_port(intra_p[sc])
                else:
                    out_p = uplink_port(cross[(sc, dc)][0])
                f.write(f"{src},{dst},0,{out_p},3\n")

    write_network_attribute(out_dir / "network_attribute.txt")
    write_traffic_stub(out_dir)
    print(f"Wrote sparse-clos scenario4 npu={npu} (full fabric 512) -> {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", type=int, choices=[1, 2, 3, 4, 0], default=1,
                    help="0=mini, 1/2/3/4 as experiment design")
    ap.add_argument("--ep-size", type=int, default=0)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()
    base = ROOT / "ns-3-ub" / "scratch" / "ub_rg_cases"
    if args.scenario == 0:
        out = Path(args.out) if args.out else base / "mini_4npu"
        gen_scenario1_mini(out)
    elif args.scenario == 1:
        n = args.ep_size if args.ep_size else 128
        out = Path(args.out) if args.out else base / f"s1_n{n}"
        gen_scenario1(out, n)
    elif args.scenario == 2:
        n = args.ep_size if args.ep_size else 1024
        out = Path(args.out) if args.out else base / f"s2_n{n}"
        gen_clos(out, n, isolated_planes=False)
    elif args.scenario == 3:
        n = args.ep_size if args.ep_size else 1024
        out = Path(args.out) if args.out else base / f"s3_n{n}"
        gen_clos(out, n, isolated_planes=True)
    elif args.scenario == 4:
        n = args.ep_size if args.ep_size else 512
        out = Path(args.out) if args.out else base / f"s4_n{n}"
        gen_sparse_clos(out, n)
    else:
        raise SystemExit("bad scenario")


if __name__ == "__main__":
    main()
