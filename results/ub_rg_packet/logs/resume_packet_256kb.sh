#!/bin/bash
set -euo pipefail
cd /home/luke/workspace/dyn_latency
export PYTHONUNBUFFERED=1
LOG=results/ub_rg_packet/logs/rerun_256kb_w1_$(date +%Y%m%d_%H%M%S).log
echo "LOG=$LOG workers=1 scenario=4 (resume remaining)"
python3 run_ub_rg_experiments.py --engine packet --workers 1 --scenario 4 2>&1 | tee "$LOG"
echo "RUNNER_EXIT=${PIPESTATUS[0]}"
python3 analyze_ub_rg_experiments.py --engine both
echo "ANALYZE_DONE_$(date +%H%M%S)"
