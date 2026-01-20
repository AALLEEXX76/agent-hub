#!/usr/bin/env python3
import json, sys

p = sys.argv[1] if len(sys.argv) > 1 else None
if not p:
    print("Usage: tools/print_report.py <path_to_report.json>", file=sys.stderr)
    raise SystemExit(2)

with open(p, "r", encoding="utf-8") as f:
    r = json.load(f)

br = r.get("brain_report")

# Если brain_report уже содержит итог (sites/summary/results) — печатаем целиком
if isinstance(br, dict):
    print(json.dumps(br, ensure_ascii=False, indent=2))
elif isinstance(br, list):
    print(json.dumps(br, ensure_ascii=False, indent=2))
else:
    print(json.dumps({"brain_report": br, "top": {k: r.get(k) for k in ("ok","exit_code","summary","task","ts_utc")}}, ensure_ascii=False, indent=2))
