#!/usr/bin/env python3
import json, sys

p = sys.argv[1] if len(sys.argv) > 1 else None
if not p:
    print("Usage: tools/print_report.py <path_to_report.json>", file=sys.stderr)
    raise SystemExit(2)

with open(p, "r", encoding="utf-8") as f:
    r = json.load(f)

br = r.get("brain_report")

# обычный формат Brain: brain_report.results[0].response
if isinstance(br, dict) and "results" in br and isinstance(br.get("results"), list) and br["results"]:
    resp = br["results"][0].get("response", br)
    print(json.dumps(resp, ensure_ascii=False, indent=2))
# shortcut-формат: brain_report уже готовый dict
elif isinstance(br, (dict, list)):
    print(json.dumps(br, ensure_ascii=False, indent=2))
# если brain_report отсутствует — печатаем что есть
else:
    print(json.dumps({"brain_report": br, "top": {k: r.get(k) for k in ("ok","exit_code","summary","task","ts_utc")}}, ensure_ascii=False, indent=2))
