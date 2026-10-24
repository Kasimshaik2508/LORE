#!/bin/sh
# Keep LORE online on a Mac: prevents sleep while it runs and restarts it if it ever exits.
# Logs go to data/agents.log.   Usage: sh scripts/run_forever.sh   (Ctrl-C twice to stop)
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
while true; do
  echo "$(date '+%F %T') starting LORE agents" | tee -a data/agents.log
  # -i idle sleep, -m disk sleep, -s system sleep (on AC power). Closing the lid still sleeps.
  caffeinate -ims "$PY" -u run_agents.py 2>&1 | tee -a data/agents.log
  echo "$(date '+%F %T') LORE exited; restarting in 5s" | tee -a data/agents.log
  sleep 5
done
