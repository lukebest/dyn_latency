#!/usr/bin/env python3
"""Batch runner for UB_RG experiments 4.2.1 / 4.2.2 / 4.2.3 (pruned matrix)."""

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
RESULTS = ROOT / "results" / "ub_rg"
ZIPF_S = [0.0, 0.3, 0.7, 0.9]
SCHEMES = ["ub_rg", "packet_spray"]
TOPK = 8
SEED = 1


@dataclass(frozen=True)
class Job:
    exp: str
    mode: str
    scenario: int
    scheme: str
    batch: int
    zipf_s: float
    ep_size: int
    seed: int = SEED

    @property
    def run_id(self) -> str:
        return (
            f"s{self.scenario}_{self.scheme}_b{self.batch}"
            f"_z{self.zipf_s:g}_ep{self.ep_size}_sd{self.seed}"
        )

    @property
    def out_dir(self) -> Path:
        return RESULTS / self.exp / self.run_id


def build_jobs() -> list[Job]:
    jobs: list[Job] = []

    # Exp1 dispatch / Exp2 combine
    for exp, mode in [("exp1_dispatch", "dispatch"), ("exp2_combine", "combine")]:
        for scenario in (1, 2, 3):
            batches = [16, 256, 1024]
            if scenario == 1:
                batches = [16, 256, 1024, 4096]
            for batch in batches:
                for zipf_s in ZIPF_S:
                    for scheme in SCHEMES:
                        jobs.append(
                            Job(
                                exp=exp,
                                mode=mode,
                                scenario=scenario,
                                scheme=scheme,
                                batch=batch,
                                zipf_s=zipf_s,
                                ep_size=0,
                            )
                        )

    # Exp3 roundtrip CDF/PDF
    ep_by_scenario = {
        1: [32, 64, 128],
        2: [256, 1024],
        3: [256, 1024],
    }
    for scenario, eps in ep_by_scenario.items():
        for ep in eps:
            for zipf_s in ZIPF_S:
                for scheme in SCHEMES:
                    jobs.append(
                        Job(
                            exp="exp3_roundtrip",
                            mode="roundtrip",
                            scenario=scenario,
                            scheme=scheme,
                            batch=256,
                            zipf_s=zipf_s,
                            ep_size=ep,
                        )
                    )
    return jobs


def find_binary() -> Path:
    build = NS3 / "build" / "scratch"
    for name in (
        "ns3.44-ub_rg-dispatch-experiment-optimized",
        "ns3.44-ub_rg-dispatch-experiment-default",
        "ns3.44-ub_rg-dispatch-experiment",
    ):
        p = build / name
        if p.exists():
            return p
    # fallback via ns3 run
    return Path("")


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
        f"--out-dir={out}",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(NS3),
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"_error": "timeout", "_run_id": job.run_id, "_exp": job.exp}

    elapsed = time.time() - t0
    if proc.returncode != 0 or not summary.exists():
        err = (proc.stderr or "")[-2000:]
        out_err = out / "stderr.txt"
        out_err.write_text(proc.stdout + "\n---\n" + (proc.stderr or ""))
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
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--limit", type=int, default=0, help="Limit jobs (debug)")
    ap.add_argument("--exp", type=str, default="", help="Filter exp name prefix")
    ap.add_argument("--force", action="store_true", help="Re-run even if summary exists")
    args = ap.parse_args()

    binary = find_binary()
    if not binary:
        print("Binary not found; build with:", file=sys.stderr)
        print(
            "  cd ns-3-ub && python3.12 ./ns3 build ub_rg-dispatch-experiment",
            file=sys.stderr,
        )
        return 1

    jobs = build_jobs()
    if args.exp:
        jobs = [j for j in jobs if j.exp.startswith(args.exp)]
    if args.limit:
        jobs = jobs[: args.limit]

    if args.force:
        for j in jobs:
            for f in (j.out_dir / "summary.json", j.out_dir / "hist.csv"):
                if f.exists():
                    f.unlink()

    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"Running {len(jobs)} jobs with {args.workers} workers")
    print(f"Binary: {binary}")

    ok = 0
    fail = 0
    skipped = 0
    t0 = time.time()
    ledger = []

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
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
    ledger_path = RESULTS / "ledger.json"
    with ledger_path.open("w") as f:
        json.dump(
            {
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
