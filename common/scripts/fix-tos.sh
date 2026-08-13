#!/bin/bash
set -euo pipefail

echo "=== TOS cleanup ==="

echo "[1/3] Killing zombie thinkorswim/java processes..."
pkill -f 'jxbrowser' 2>/dev/null && echo "  killed jxbrowser processes" || echo "  no jxbrowser processes"
pkill -f 'thinkorswim' 2>/dev/null && echo "  killed thinkorswim processes" || echo "  no thinkorswim processes"
sleep 1

echo "[2/3] Clearing conflicting browser data dirs..."
rm -rf ~/.thinkorswim/login-browser-data-v29-0
rm -rf ~/.thinkorswim/login-browser-data-v29-1
rm -rf ~/thinkorswim/jxbrowser/v29/tmp/*
echo "  done"

echo "[3/3] Removing stale error workspace..."
rm -f ~/thinkorswim/workspace.jw_0cqqcvn26ona.tos.prod.err.xml
echo "  done"

echo ""
echo "TOS cleanup complete. You can now relaunch Thinkorswim."
