#!/usr/bin/env bash
set -euo pipefail

./tools/test_sites_fix.sh
./tools/test_all_fix.sh
./tools/test_recovery_all_fix.sh

echo "OK: all e2e tests passed"
