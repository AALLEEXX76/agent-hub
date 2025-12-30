#!/usr/bin/env python3
import os, json, subprocess, sys

BASE = os.environ["N8N_BASE_URL"].rstrip("/")
KEY  = os.environ["N8N_API_KEY"]

WF_NAME = "СВЯЗЬ ИИ С Н8Н - Agent Task API"
CODE_NODE_NAME = "Build Agent Task"

NEW_JS = r'''
// Webhook в n8n отдаёт структуру {headers, params, query, body}.
// Нам нужен именно body как payload задачи.
const envelope = $json || {};
const payload = (envelope.body && typeof envelope.body === 'object') ? envelope.body : envelope;

const task = (payload.task ?? "").toString().trim();

return [{
  json: {
    ...payload,
    task,
    // если хочешь сохранять метаданные запроса — раскомментируй:
    // _meta: { headers: envelope.headers, params: envelope.params, query: envelope.query }
  }
}];
'''.strip()

def curl_json(args):
    out = subprocess.check_output(args, text=True)
    return json.loads(out) if out.strip() else None

def api_get(path):
    return curl_json(["curl","-sS","-H",f"X-N8N-API-KEY: {KEY}", f"{BASE}{path}"])

def api_post(path):
    return curl_json(["curl","-sS","-X","POST","-H",f"X-N8N-API-KEY: {KEY}", f"{BASE}{path}"])

def api_put(path, body):
    return curl_json([
        "curl","-sS","-X","PUT",
        "-H",f"X-N8N-API-KEY: {KEY}",
        "-H","Content-Type: application/json",
        "--data-binary", json.dumps(body, ensure_ascii=False),
        f"{BASE}{path}"
    ])

def main():
    wfs = api_get("/workflows")
    data = (wfs or {}).get("data", [])
    wid = None
    for wf in data:
        if wf.get("name") == WF_NAME:
            wid = wf.get("id")
            break
    if not wid:
        print(f"[fix_builder] ERROR: workflow not found: {WF_NAME}")
        sys.exit(2)

    wf_full = api_get(f"/workflows/{wid}")
    if not wf_full:
        print("[fix_builder] ERROR: can't load workflow json")
        sys.exit(3)

    changed = 0
    for n in (wf_full.get("nodes", []) or []):
        if n.get("type") == "n8n-nodes-base.code" and n.get("name") == CODE_NODE_NAME:
            params = n.get("parameters", {}) or {}
            params["jsCode"] = NEW_JS
            n["parameters"] = params
            changed += 1

    if changed == 0:
        print(f"[fix_builder] ERROR: code node not found: {CODE_NODE_NAME}")
        sys.exit(4)

    clean = {
        "name": wf_full.get("name"),
        "nodes": wf_full.get("nodes", []),
        "connections": wf_full.get("connections", {}),
        "settings": wf_full.get("settings", {}),
    }

    api_put(f"/workflows/{wid}", clean)
    print("[fix_builder] PUT OK")

    api_post(f"/workflows/{wid}/activate")
    print("[fix_builder] ACTIVATE OK")
    print("[fix_builder] DONE. workflow_id=", wid)

if __name__ == "__main__":
    main()
