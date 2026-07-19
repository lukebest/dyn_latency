#!/usr/bin/env python3
"""Generate node/topology/routing CSV for UB_RG packet experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write_network_attribute(out: Path) -> None:
    out.write_text(
        """default ns3::UbApp::EnableMultiPath "false"
default ns3::UbApp::UseShortestPaths "true"
default ns3::UbApp::UsePacketSpray "false"
default ns3::UbLink::Delay "+50ns"
default ns3::UbPort::UbDataRate "400Gbps"
default ns3::UbPort::UbInterframeGap "+0ns"
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", type=int, choices=[1, 2, 3, 0], default=1,
                    help="0=mini, 1/2/3 as experiment design")
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
    else:
        raise SystemExit("bad scenario")


if __name__ == "__main__":
    main()
