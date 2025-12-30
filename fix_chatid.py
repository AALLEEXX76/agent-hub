#!/usr/bin/env python3
import os, sys, json, urllib.request, urllib.error

def http_json(method: str, url: str, api_key: str, body: dict | None = None):
    headers = {
        "X-N8N-API-KEY": api_key,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw

def main():
    if len(sys.argv) < 2:
        print("USAGE: fix_chatid.py <workflow_id> [--activate]", file=sys.stderr)
        sys.exit(2)

    wid = sys.argv[1].strip()
    do_activate = ("--activate" in sys.argv[2:])

    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    key  = os.environ.get("N8N_API_KEY", "")
    if not base or not key:
        print("ERROR: N8N_BASE_URL / N8N_API_KEY not set (source your .agent_env)", file=sys.stderr)
        sys.exit(2)

    # 1) GET workflow
    url_get = f"{base}/workflows/{wid}"
    code, raw = http_json("GET", url_get, key)
    if code < 200 or code >= 300:
        print(f"ERROR GET {url_get} -> {code}\n{raw[:500]}", file=sys.stderr)
        sys.exit(1)

    wf = json.loads(raw)
    nodes = wf.get("nodes", []) or []
    conns = wf.get("connections", {}) or {}
    settings = wf.get("settings", {}) or {}

    # найти имя Telegram Trigger
    trigger = next((n for n in nodes if n.get("type") == "n8n-nodes-base.telegramTrigger"), None)
    if not trigger:
        print("ERROR: telegramTrigger node not found in workflow", file=sys.stderr)
        sys.exit(1)

    trigger_name = trigger.get("name", "Telegram Trigger")
    expr = f'={{$node["{trigger_name}"].json.message.chat.id}}'

    # 2) PATCH nodes in-memory: all Telegram nodes (sendMessage) -> set chatId
    changed = 0
    for n in nodes:
        if n.get("type") != "n8n-nodes-base.telegram":
            continue
        params = n.get("parameters") or {}
        # chatId field exists for sendMessage; set it anyway (harmless)
        old = params.get("chatId")
        if old != expr:
            params["chatId"] = expr
            n["parameters"] = params
            changed += 1

    print(f"[fix_chatid] workflow='{wf.get('name')}' id={wid}")
    print(f"[fix_chatid] trigger='{trigger_name}' expr={expr}")
    print(f"[fix_chatid] telegram nodes updated: {changed}")

    if changed == 0:
        print("[fix_chatid] nothing to change")

    # 3) PUT workflow (ВАЖНО: только разрешённые поля)
    url_put = f"{base}/workflows/{wid}"
    put_body = {
        "name": wf.get("name") or "II-BOT Executor",
        "nodes": nodes,
        "connections": conns,
        "settings": settings,
    }
    code, raw = http_json("PUT", url_put, key, put_body)
    if code < 200 or code >= 300:
        print(f"ERROR PUT {url_put} -> {code}\n{raw[:800]}", file=sys.stderr)
        sys.exit(1)

    print(f"[fix_chatid] PUT OK ({code})")

    # 4) activate (optional)
    if do_activate:
        url_act = f"{base}/workflows/{wid}/activate"
        code, raw = http_json("POST", url_act, key)
        if code < 200 or code >= 300:
            print(f"ERROR ACTIVATE {url_act} -> {code}\n{raw[:500]}", file=sys.stderr)
            sys.exit(1)
        print(f"[fix_chatid] ACTIVATE OK ({code})")

if __name__ == "__main__":
    main()
