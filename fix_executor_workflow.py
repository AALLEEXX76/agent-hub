#!/usr/bin/env python3
import os, json, subprocess, sys

BASE = os.environ.get("N8N_BASE_URL","").rstrip("/")
KEY  = os.environ.get("N8N_API_KEY","")
if not BASE or not KEY:
    print("ERR: set N8N_BASE_URL and N8N_API_KEY (source .agent_env)", file=sys.stderr)
    sys.exit(2)

WF_NAME = "Agent Executor v1 (Webhook → SSH → Respond + TG optional)"
WEBHOOK_PATH = "agent-exec"

# Use known existing credentials by ID+name (already present on your n8n)
CRED_SSH_ID = "ibD9UOMY08GalRvM"
CRED_SSH_NAME = "SSH Private Key account"
CRED_TG_ID = "NTt0aN3D7XmoUaIc"
CRED_TG_NAME = "ИИ БОТ АГЕНТ НОУТБУК"

def curl_json(method, url, data=None):
    cmd = ["curl","-sS","-X",method, url, "-H", f"X-N8N-API-KEY: {KEY}", "-H","Content-Type: application/json"]
    if data is not None:
        cmd += ["--data-binary", json.dumps(data, ensure_ascii=False)]
    out = subprocess.check_output(cmd, text=True)
    return json.loads(out)

def list_workflows():
    return curl_json("GET", f"{BASE}/workflows").get("data", [])

def create_workflow(body):
    return curl_json("POST", f"{BASE}/workflows", body)

def update_workflow(wid, body):
    return curl_json("PUT", f"{BASE}/workflows/{wid}", body)

def activate(wid):
    return curl_json("POST", f"{BASE}/workflows/{wid}/activate")

wf = {
  "name": WF_NAME,
  "nodes": [
    {
      "id": "wh1",
      "name": "Webhook In",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "parameters": {
        "path": WEBHOOK_PATH,
        "httpMethod": "POST",
        "responseMode": "responseNode",
        "options": {}
      }
    },
    {
      "id": "code_parse",
      "name": "Parse Task",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [460, 300],
      "parameters": {
        "jsCode": """// Accepts JSON body with fields: task, telegram.chatId (optional) or chatId (optional)
const body = $json.body || $json;
const taskRaw = String(body.task || '').trim();
const lower = taskRaw.toLowerCase();

const chatId = body.chatId ?? body.telegram?.chatId ?? null;

const allowed = ['docker_status','healthz','backup_now','restart_n8n','caddy_logs'];

function normalizeAction(t) {
  // formats: "ssh: docker_status" OR "docker_status" OR "/status" etc.
  let x = t.trim();
  if (x.toLowerCase().startsWith('ssh:')) x = x.slice(4).trim();
  x = x.replace(/^\\/+/, '').split(/\\s+/)[0]; // first token
  x = x.replace(/@.+$/, ''); // strip @bot
  // map telegram-ish commands
  if (x === 'status') return 'docker_status';
  if (x === 'ping' || x === 'health') return 'healthz';
  if (x === 'backup') return 'backup_now';
  if (x === 'restart') return 'restart_n8n';
  if (x === 'logs' || (x === 'caddy' && lower.includes('logs')) || lower.includes('caddy logs')) return 'caddy_logs';
  return x;
}

const action = normalizeAction(taskRaw);
const ok = allowed.includes(action);

const help =
`Не понял команду.

Доступные:
ssh: docker_status  (или /status)
ssh: healthz        (или /health, /ping)
ssh: backup_now     (или /backup)
ssh: restart_n8n    (или /restart)
ssh: caddy_logs     (или "caddy logs")`;

return [{
  json: {
    task: taskRaw,
    action,
    ok,
    chatId,
    cmd: ok ? `sudo /usr/local/sbin/iibot ${action}` : null,
    help
  }
}];"""
      }
    },
    {
      "id": "if_ok",
      "name": "IF Known Action",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2,
      "position": [680, 300],
      "parameters": {
        "conditions": {
          "conditions": [
            {
              "leftValue": "={{$json.ok}}",
              "operator": { "type": "boolean", "operation": "true" }
            }
          ],
          "combinator": "and"
        }
      }
    },
    {
      "id": "ssh1",
      "name": "SSH Execute",
      "type": "n8n-nodes-base.ssh",
      "typeVersion": 1,
      "position": [900, 240],
      "credentials": {
        "sshPrivateKey": { "id": CRED_SSH_ID, "name": CRED_SSH_NAME }
      },
      "parameters": {
        "command": "={{$json.cmd}}"
      }
    },
    {
      "id": "code_out_ok",
      "name": "Build Output",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [1120, 240],
      "parameters": {
        "jsCode": """const stdout = String($json.stdout ?? '').trim();
const stderr = String($json.stderr ?? '').trim();
const text = (stdout || stderr || 'ok').toString().slice(0, 3800);

return [{
  json: {
    ok: true,
    action: $node['Parse Task'].json.action,
    stdout,
    stderr,
    text,
    chatId: $node['Parse Task'].json.chatId
  }
}];"""
      }
    },
    {
      "id": "code_out_bad",
      "name": "Build Help",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [900, 380],
      "parameters": {
        "jsCode": """return [{
  json: {
    ok: false,
    action: $node['Parse Task'].json.action,
    text: $node['Parse Task'].json.help,
    chatId: $node['Parse Task'].json.chatId
  }
}];"""
      }
    },
    {
      "id": "if_chat",
      "name": "IF chatId",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2,
      "position": [1320, 300],
      "parameters": {
        "conditions": {
          "conditions": [
            {
              "leftValue": "={{$json.chatId}}",
              "operator": { "type": "string", "operation": "notEmpty" }
            }
          ],
          "combinator": "and"
        }
      }
    },
    {
      "id": "tg_send",
      "name": "Telegram: Send (optional)",
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1,
      "position": [1540, 240],
      "credentials": {
        "telegramApi": { "id": CRED_TG_ID, "name": CRED_TG_NAME }
      },
      "parameters": {
        "resource": "message",
        "operation": "sendMessage",
        "chatId": "={{$json.chatId}}",
        "text": "={{$json.text}}"
      }
    },
    {
      "id": "resp",
      "name": "Respond",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1,
      "position": [1540, 380],
      "parameters": {
        "responseBody": "={{$json}}",
        "options": {}
      }
    }
  ],
  "connections": {
    "Webhook In": { "main": [[{ "node": "Parse Task", "type": "main", "index": 0 }]] },
    "Parse Task": { "main": [[{ "node": "IF Known Action", "type": "main", "index": 0 }]] },
    "IF Known Action": {
      "main": [
        [{ "node": "SSH Execute", "type": "main", "index": 0 }],
        [{ "node": "Build Help", "type": "main", "index": 0 }]
      ]
    },
    "SSH Execute": { "main": [[{ "node": "Build Output", "type": "main", "index": 0 }]] },
    "Build Output": { "main": [[{ "node": "IF chatId", "type": "main", "index": 0 }, { "node": "Respond", "type": "main", "index": 0 }]] },
    "Build Help":   { "main": [[{ "node": "IF chatId", "type": "main", "index": 0 }, { "node": "Respond", "type": "main", "index": 0 }]] },
    "IF chatId": {
      "main": [
        [{ "node": "Telegram: Send (optional)", "type": "main", "index": 0 }],
        []
      ]
    }
  },
  "settings": {}
}

# upsert
existing = [w for w in list_workflows() if w.get("name") == WF_NAME]
if existing:
    wid = existing[0]["id"]
    print(f"[fix_executor] updating workflow id={wid}")
    resp = update_workflow(wid, wf)
else:
    print("[fix_executor] creating workflow")
    resp = create_workflow(wf)
    wid = resp["id"]

print("[fix_executor] PUT/POST OK, id=", wid)
act = activate(wid)
print("[fix_executor] ACTIVATE OK, active=", act.get("active"))
print("[fix_executor] DONE. webhook:", f"{BASE.replace('/api/v1','')}/webhook/{WEBHOOK_PATH}")
