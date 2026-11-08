#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./todo.sh check
./todo.sh smoke
./todo.sh status
./todo.sh improve
