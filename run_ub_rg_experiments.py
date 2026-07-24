#!/usr/bin/env python3
"""Batch runner for UB_RG experiments (behavioral and packet engines).

Matrix (2026-07): scenarios 1 + 4 only; start-skew σ∈{0,2,4,8} µs (Normal);
S1 adds islip.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NS3 = ROOT / "ns-3-ub"
ZIPF_S = [0.0, 0.3, 0.7, 0.9]
# Base schemes; islip is scenario-1 only (single-layer switch scheduler).
SCHEMES_BASE = ["ub_rg", "ub_rg_pop", "packet_spray"]
SCHEMES_S1 = SCHEMES_BASE + ["islip"]
SCENARIOS = (1, 4)
START_SKEW_US = [0.0, 2.0, 4.0, 8.0]
TOPK = 8
SEED = 1

EXP3_PDF_SCENARIO_EPS = {
    1: [32, 64, 128],
    4: [128, 256, 512],
}
EXP3_PDF_DEFAULT_BATCHES = [16, 64, 128, 256, 512]
EXP3_PDF_DEFAULT_SEEDS = 96


@dataclass(frozen=True)
class Job:
    exp: str
    mode: str
    scenario: int
    scheme: str
    batch: int
    zipf_s: float
    ep_size: int
    engine: str
    seed: int = SEED
    start_skew_us: float = 0.0

    @property
    def run_id(self) -> str:
        # Always tag skew (incl. σ=0) so Normal-skew runs never collide with legacy U(0,sk).
        return (
            f"s{self.scenario}_{self.scheme}_b{self.batch}"
            f"_z{self.zipf_s:g}_ep{self.ep_size}_sd{self.seed}"
            f"_nsk{self.start_skew_us:g}"
        )

    @property
    def results_root(self) -> Path:
        return ROOT / "results" / ("ub_rg_packet" if self.engine == "packet" else "ub_rg")

    @property
    def out_dir(self) -> Path:
        return self.results_root / self.exp / self.run_id


def schemes_for(scenario: int) -> list[str]:
    return list(SCHEMES_S1 if scenario == 1 else SCHEMES_BASE)


def build_jobs(engine: str) -> list[Job]:
    jobs: list[Job] = []

    for exp, mode in [("exp1_dispatch", "dispatch"), ("exp2_combine", "combine")]:
        for scenario in SCENARIOS:
            for batch in (16, 256):
                for zipf_s in ZIPF_S:
                    for scheme in schemes_for(scenario):
                        for skew in START_SKEW_US:
                            jobs.append(
                                Job(
                                    exp=exp,
                                    mode=mode,
                                    scenario=scenario,
                                    scheme=scheme,
                                    batch=batch,
                                    zipf_s=zipf_s,
                                    ep_size=0,
                                    engine=engine,
                                    start_skew_us=skew,
                                )
                            )

    ep_by_scenario = {
        1: [32, 64, 128],
        4: [128, 256, 512],
    }
    for scenario, eps in ep_by_scenario.items():
        for ep in eps:
            for zipf_s in ZIPF_S:
                for scheme in schemes_for(scenario):
                    for skew in START_SKEW_US:
                        jobs.append(
                            Job(
                                exp="exp3_roundtrip",
                                mode="roundtrip",
                                scenario=scenario,
                                scheme=scheme,
                                batch=256,
                                zipf_s=zipf_s,
                                ep_size=ep,
                                engine=engine,
                                start_skew_us=skew,
                            )
                        )
    # S1 iSLIP also covers batch 128/512 (same EP/Zipf/skew grid as batch=256).
    for ep in ep_by_scenario[1]:
        for batch in (128, 512):
            for zipf_s in ZIPF_S:
                for skew in START_SKEW_US:
                    jobs.append(
                        Job(
                            exp="exp3_roundtrip",
                            mode="roundtrip",
                            scenario=1,
                            scheme="islip",
                            batch=batch,
                            zipf_s=zipf_s,
                            ep_size=ep,
                            engine=engine,
                            start_skew_us=skew,
                        )
                    )
    jobs.sort(
        key=lambda j: (
            j.batch,
            j.scenario,
            j.start_skew_us,
            j.exp,
            j.zipf_s,
            j.scheme,
        )
    )
    return jobs


def build_exp3_pdf_jobs(
    engine: str,
    seeds: int,
    batches: list[int],
    zipf_list: list[float],
) -> list[Job]:
    """Multi-seed roundtrip sweep for system / E2E CCT PDF."""
    jobs: list[Job] = []
    # PDF uses mid σ=4µs as representative Normal start-skew.
    skew = 4.0
    for scenario, eps in EXP3_PDF_SCENARIO_EPS.items():
        for ep in eps:
            for batch in batches:
                for zipf_s in zipf_list:
                    for scheme in schemes_for(scenario):
                        for sd in range(1, seeds + 1):
                            jobs.append(
                                Job(
                                    exp="exp3_pdf",
                                    mode="roundtrip",
                                    scenario=scenario,
                                    scheme=scheme,
                                    batch=batch,
                                    zipf_s=zipf_s,
                                    ep_size=ep,
                                    engine=engine,
                                    seed=sd,
                                    start_skew_us=skew,
                                )
                            )
    return jobs


def find_binary(engine: str) -> Path | None:
    build = NS3 / "build" / "scratch"
    names = (
        (
            "ns3.44-ub_rg-packet-experiment-optimized",
            "ns3.44-ub_rg-packet-experiment-default",
            "ns3.44-ub_rg-packet-experiment",
        )
        if engine == "packet"
        else (
            "ns3.44-ub_rg-dispatch-experiment-optimized",
            "ns3.44-ub_rg-dispatch-experiment-default",
            "ns3.44-ub_rg-dispatch-experiment",
        )
    )
    for name in names:
        p = build / name
        if p.is_file():
            return p
    return None


def case_path_for(job: Job) -> str:
    base = NS3 / "scratch" / "ub_rg_cases"
    if job.scenario == 1:
        n = job.ep_size if job.ep_size else 128
        return str(base / f"s1_n{n}")
    if job.scenario == 4:
        n = job.ep_size if job.ep_size else 512
        return str(base / f"s4_n{n}")
    n = 1024
    return str(base / f"s{job.scenario}_n{n}")


def ensure_cases(engine: str) -> None:
    if engine != "packet":
        return
    gen = ROOT / "gen_ub_rg_topo.py"
    needed = [
        (1, 128),
        (1, 32),
        (1, 64),
        # Scenario 4 packet cases generated when gen supports --scenario 4.
        (4, 512),
        (4, 256),
        (4, 128),
    ]
    for sc, n in needed:
        out = NS3 / "scratch" / "ub_rg_cases" / (f"s{sc}_n{n}")
        marker = out / "routing_table.csv"
        if marker.exists():
            continue
        if sc == 4 and not _gen_supports_scenario4(gen):
            print(f"Skip generating s{sc}_n{n}: gen_ub_rg_topo.py has no scenario 4 yet")
            continue
        print(f"Generating case s{sc}_n{n} ...")
        subprocess.run(
            [sys.executable, str(gen), "--scenario", str(sc), "--ep-size", str(n)],
            check=True,
        )


def _gen_supports_scenario4(gen: Path) -> bool:
    try:
        text = gen.read_text(encoding="utf-8")
    except OSError:
        return False
    return "scenario == 4" in text or "scenario=4" in text or '"4"' in text


def run_job(job: Job, binary: str) -> dict:
    out = job.out_dir
    out.mkdir(parents=True, exist_ok=True)
    summary = out / "summary.json"
    if summary.exists() and (out / "hist.csv").exists():
        with summary.open() as f:
            data = json.load(f)
        data["_skipped"] = True
        data["_run_id"] = job.run_id
        return data

    cmd = [
        binary,
        f"--scenario={job.scenario}",
        f"--scheme={job.scheme}",
        f"--mode={job.mode}",
        f"--batch={job.batch}",
        f"--zipf-s={job.zipf_s}",
        f"--topk={TOPK}",
        f"--ep-size={job.ep_size}",
        f"--seed={job.seed}",
        f"--start-skew-us={job.start_skew_us}",
        f"--out-dir={out}",
    ]
    if job.engine == "packet":
        cmd.append(f"--case-path={case_path_for(job)}")

    timeout = 3600
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(NS3),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"_error": "timeout", "_run_id": job.run_id, "_exp": job.exp}

    elapsed = time.time() - t0
    if proc.returncode != 0 or not summary.exists():
        err = (proc.stderr or "")[-2000:]
        (out / "stderr.txt").write_text((proc.stdout or "") + "\n---\n" + (proc.stderr or ""))
        return {
            "_error": f"rc={proc.returncode}",
            "_run_id": job.run_id,
            "_exp": job.exp,
            "_stderr": err,
            "_elapsed": elapsed,
        }

    with summary.open() as f:
        data = json.load(f)
    data["_elapsed"] = elapsed
    data["_run_id"] = job.run_id
    data["_exp"] = job.exp
    data["_skipped"] = False
    data["_engine"] = job.engine
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["behavioral", "packet"], default="behavioral")
    ap.add_argument("--workers", type=int, default=0, help="0=auto by engine")
    ap.add_argument("--limit", type=int, default=0, help="Limit jobs (debug)")
    ap.add_argument("--exp", type=str, default="", help="Filter exp name prefix")
    ap.add_argument("--scenario", type=int, default=0, help="Filter scenario")
    ap.add_argument("--force", action="store_true", help="Re-run even if summary exists")
    ap.add_argument(
        "--exp3-pdf",
        action="store_true",
        help="Run only the multi-seed exp3 system-CCT PDF sweep (routes to exp3_pdf/)",
    )
    ap.add_argument(
        "--seeds",
        type=int,
        default=EXP3_PDF_DEFAULT_SEEDS,
        help="Seeds per config for --exp3-pdf (1..N)",
    )
    ap.add_argument(
        "--batches",
        type=str,
        default="",
        help="Comma list of batch sizes for --exp3-pdf (default 16,64,128,256,512)",
    )
    args = ap.parse_args()

    ensure_cases(args.engine)
    binary = find_binary(args.engine)
    if not binary:
        print("Binary not found; build with:", file=sys.stderr)
        tgt = "ub_rg-packet-experiment" if args.engine == "packet" else "ub_rg-dispatch-experiment"
        print(f"  cd ns-3-ub && ./ns3 build {tgt}", file=sys.stderr)
        return 1

    if args.exp3_pdf:
        batches = (
            [int(x) for x in args.batches.split(",") if x.strip()]
            if args.batches
            else EXP3_PDF_DEFAULT_BATCHES
        )
        jobs = build_exp3_pdf_jobs(args.engine, args.seeds, batches, ZIPF_S)
    else:
        jobs = build_jobs(args.engine)
    if args.exp:
        jobs = [j for j in jobs if j.exp.startswith(args.exp)]
    if args.scenario:
        jobs = [j for j in jobs if j.scenario == args.scenario]
    if args.limit:
        jobs = jobs[: args.limit]

    if args.workers > 0:
        workers = args.workers
    elif args.engine == "packet":
        workers = 4
    else:
        workers = max(1, (os.cpu_count() or 2) - 2)

    if args.force:
        for j in jobs:
            for f in (j.out_dir / "summary.json", j.out_dir / "hist.csv"):
                if f.exists():
                    f.unlink()

    results_root = ROOT / "results" / ("ub_rg_packet" if args.engine == "packet" else "ub_rg")
    results_root.mkdir(parents=True, exist_ok=True)
    print(f"Engine={args.engine} jobs={len(jobs)} workers={workers}")
    print(f"Binary: {binary}")

    ok = 0
    fail = 0
    skipped = 0
    t0 = time.time()
    ledger = []

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_job, j, str(binary)): j for j in jobs}
        done = 0
        for fut in as_completed(futs):
            done += 1
            job = futs[fut]
            try:
                data = fut.result()
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"[{done}/{len(jobs)}] FAIL {job.run_id}: {e}")
                ledger.append({"run_id": job.run_id, "exp": job.exp, "error": str(e)})
                continue

            if data.get("_error"):
                fail += 1
                print(f"[{done}/{len(jobs)}] FAIL {job.run_id}: {data['_error']}")
            elif data.get("_skipped"):
                skipped += 1
                if done % 20 == 0 or done == len(jobs):
                    print(f"[{done}/{len(jobs)}] skip {job.run_id}")
            else:
                ok += 1
                print(
                    f"[{done}/{len(jobs)}] ok {job.exp}/{job.run_id} "
                    f"step={data.get('step_us', 0):.2f}us "
                    f"({data.get('_elapsed', 0):.2f}s)"
                )
            ledger.append(data)

    wall = time.time() - t0
    ledger_path = results_root / "ledger.json"
    with ledger_path.open("w") as f:
        json.dump(
            {
                "engine": args.engine,
                "ok": ok,
                "fail": fail,
                "skipped": skipped,
                "wall_s": wall,
                "jobs": len(jobs),
                "results": ledger,
            },
            f,
            indent=2,
        )
    print(
        f"Done: ok={ok} fail={fail} skipped={skipped} wall={wall:.1f}s "
        f"ledger={ledger_path}"
    )
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
