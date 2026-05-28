#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

OUTPUT_DIR="${INSPOLY_EVENT_PERF_OUTPUT_DIR:-event_forensic_performance_outputs}"
STAMP="$(/bin/date -u +%Y%m%d_%H%M%S)"

mkdir -p "$OUTPUT_DIR"

python3 tools/event_forensic_performance_inventory.py \
  --root . \
  --output "$OUTPUT_DIR/event_forensic_performance_inventory_$STAMP.json"

python3 tools/event_forensic_performance_audit.py \
  --input-dir event_forensic_outputs \
  --output-dir "$OUTPUT_DIR"

echo "Event Forensic performance probe completed."
echo "This probe reads saved outputs only; it does not change scoring, gates, reports, or storage."
