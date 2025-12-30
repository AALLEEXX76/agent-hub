#!/usr/bin/env python3
import os, sys, json, subprocess

BASE = os.environ["N8N_BASE_URL"].rstrip("/")
KEY  = os.environ["N8N_API_KEY"]

TARGET_NAME = "СВЯЗЬ ИИ С Н8Н - Agent Task API"
PATH_WANTED = "agent-task"
METHOD_WANTED = "POST"

def curl_json(args):
    out = subprocess.check_output(args, text=True)
    if not out.strip():
        return None
    return json.loads(out)

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

def find_webhooks(workflows):
    hits = []
    for wf in workflows:
        nodes = wf.get("nodes", []) or []
        for n in nodes:
            if n.get("type") != "n8n-nodes-base.webhook":
                continue
            p = n.get("parameters", {}) or {}
            path = p.get("path")
            method = p.get("httpMethod") or p.get("method")
            if path == PATH_WANTED:
                hits.append({
                    "id": wf.get("id"),
                    "name": wf.get("name"),
                    "active": wf.get("active"),
                    "nodeName": n.get("name"),
                    "method": method,
                })
    return hits

def main():
    wfs = api_get("/workflows")
    data = (wfs or {}).get("data", [])
    hits = find_webhooks(data)

    print(f"[fix_webhook] Found {len(hits)} workflows with webhook path='{PATH_WANTED}':")
    for h in hits:
        print(f" - {h['id']} | active={h['active']} | method={h['method']} | wf='{h['name']}' | node='{h['nodeName']}'")

    # выбрать target workflow
    target_id = None
    for wf in data:
        if wf.get("name") == TARGET_NAME:
            target_id = wf.get("id")
            break

    if not target_id:
        print(f"[fix_webhook] ERROR: target workflow by name not found: {TARGET_NAME}")
        sys.exit(2)

    print(f"[fix_webhook] Target workflow: {TARGET_NAME} id={target_id}")

    # 1) деактивировать все ДРУГИЕ активные workflow с тем же path
    for h in hits:
        if h["id"] != target_id and h["active"]:
            print(f"[fix_webhook] Deactivating conflicting workflow id={h['id']} name='{h['name']}'")
            r = api_post(f"/workflows/{h['id']}/deactivate")
            if not r or not isinstance(r, dict):
                print("[fix_webhook] WARN: deactivate returned empty/non-json")
            else:
                print("[fix_webhook] deactivate OK")

    # 2) скачать полный target workflow
    wf_full = api_get(f"/workflows/{target_id}")
    if not wf_full or not isinstance(wf_full, dict):
        print("[fix_webhook] ERROR: can't load workflow full json")
        sys.exit(3)

    # 3) поправить webhook node (path=agent-task) -> method POST
    changed = 0
    for n in (wf_full.get("nodes", []) or []):
        if n.get("type") != "n8n-nodes-base.webhook":
            continue
        p = n.get("parameters", {}) or {}
        if p.get("path") != PATH_WANTED:
            continue
        old = p.get("httpMethod") or p.get("method")
        p["httpMethod"] = METHOD_WANTED
        n["parameters"] = p
        changed += 1
        print(f"[fix_webhook] node='{n.get('name')}' httpMethod: {old} -> {METHOD_WANTED}")

    if changed == 0:
        print("[fix_webhook] ERROR: no webhook node with matching path found inside target workflow")
        sys.exit(4)

    # 4) PUT (только разрешённые поля)
    clean = {
        "name": wf_full.get("name"),
        "nodes": wf_full.get("nodes", []),
        "connections": wf_full.get("connections", {}),
        "settings": wf_full.get("settings", {}),
    }
    put_resp = api_put(f"/workflows/{target_id}", clean)
    if not put_resp or not isinstance(put_resp, dict):
        print("[fix_webhook] ERROR: PUT failed (empty/non-json)")
        sys.exit(5)
    print("[fix_webhook] PUT OK")

    # 5) переактивировать (чтобы n8n реально пересоздал регистрацию webhook)
    act = api_post(f"/workflows/{target_id}/activate")
    if not act or not isinstance(act, dict):
        print("[fix_webhook] WARN: activate returned empty/non-json (but may still be OK)")
    else:
        print(f"[fix_webhook] ACTIVATE OK active={act.get('active')}")

    print("[fix_webhook] DONE")
    print(f"[fix_webhook] Test: curl -i -X POST https://ii-bot-nout.ru/webhook/{PATH_WANTED} -H 'Content-Type: application/json' -d '{{\"task\":\"ping\"}}'")

if __name__ == "__main__":
    main()
