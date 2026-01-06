#!/usr/bin/env python3
import json, sys
from pathlib import Path

KEEP = ("name", "nodes", "connections", "settings")
OPTIONAL = ("staticData", "tags", "shared", "active", "createdAt", "updatedAt", "id")

def load_json(p: Path):
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        if len(data) != 1:
            raise SystemExit(f"ERROR: expected 1 workflow in list, got {len(data)}")
        data = data[0]
    if not isinstance(data, dict):
        raise SystemExit("ERROR: workflow JSON must be an object")
    return data

def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: tools/n8n_workflow_put_payload.py <src_export.json> [dst_put.json]")
    src = Path(sys.argv[1]).expanduser()
    dst = Path(sys.argv[2]).expanduser() if len(sys.argv) >= 3 else None

    wf = load_json(src)

    out = {}
    for k in KEEP:
        if k not in wf:
            raise SystemExit(f"ERROR: missing required key for PUT: {k}")
        out[k] = wf[k]

    # keep a few optional keys if present (safe by schema), but DON'T add anything else
    for k in OPTIONAL:
        if k in wf and k not in out:
            out[k] = wf[k]

    s = json.dumps(out, ensure_ascii=False)
    if dst:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(s, encoding="utf-8")
    else:
        sys.stdout.write(s)

if __name__ == "__main__":
    main()
