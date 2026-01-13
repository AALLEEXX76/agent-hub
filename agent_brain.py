#!/usr/bin/env python3
import os
import json
from datetime import datetime, timezone
from pathlib import Path

import re
import sys
from typing import Any, Dict, List, Optional

import httpx
import subprocess
from dotenv import load_dotenv
from anthropic import Anthropic


# Hand v2 manifests cache (self-discovery)
HANDV2_MANIFESTS_CACHE = Path(__file__).resolve().parent / "artifacts" / "handv2_manifests_cache.json"

def load_handv2_manifests_cache() -> Optional[List[Dict[str, Any]]]:
    try:
        import json as _json
        data = _json.loads(HANDV2_MANIFESTS_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def index_handv2_manifests(manifests: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Build quick lookup index: action_name -> manifest dict."""
    idx: Dict[str, Dict[str, Any]] = {}
    if not manifests:
        return idx
    for m in manifests:
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        if isinstance(name, str) and name.strip():
            idx[name.strip()] = m
    return idx


def _extract_manifests_from_list_actions(resp: Any) -> Optional[List[Dict[str, Any]]]:
    try:
        arts = (resp or {}).get("artifacts") or []
        for a in arts:
            if isinstance(a, dict) and a.get("type") == "json" and a.get("name") == "manifests":
                v = a.get("value")
                if isinstance(v, list):
                    return v
    except Exception:
        return None
    return None

def refresh_handv2_manifests(agent_exec_url: str, chat_id: Optional[int]) -> Optional[List[Dict[str, Any]]]:
    try:
        out = call_agent_exec(
            agent_exec_url,
            "ssh: run",
            chat_id,
            params={"action": "list_actions", "mode": "check", "args": {}},
            timeout_s=30,
        )
    except Exception:
        return None

    try:
        norm = normalize_exec_response("ssh: run", out)
    except Exception:
        norm = out

    manifests = _extract_manifests_from_list_actions(norm)
    if not manifests:
        return None

    try:
        import json as _json
        HANDV2_MANIFESTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HANDV2_MANIFESTS_CACHE.write_text(_json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

    return manifests


def _parse_direct_ssh_run(task_text: str) -> Optional[Dict[str, Any]]:
    """Direct CLI mode: ssh: run action=... mode=check|plan|apply [args=<json-no-spaces>]."""
    t = (task_text or "").strip()
    m = re.match(r"^ssh\s*:\s*run\b\s*:?(.*)$", t, flags=re.IGNORECASE)
    if not m:
        return None
    rest = (m.group(1) or "").strip()
    kv: Dict[str, str] = {}
    for part in rest.split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        kv[k.strip().lower()] = v.strip()

    action = kv.get("action")
    if not action:
        return None
    mode = (kv.get("mode") or "check").strip().lower()
    if mode not in {"check","plan","apply"}:
        mode = "check"

    args = {}
    if "args" in kv:
        try:
            args = json.loads(kv["args"])
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {}

    confirm = (kv.get("confirm") or "").strip()

    params = {"action": action, "mode": mode, "args": args}
    if confirm:
        params["confirm"] = confirm

    return {"task": "ssh: run", "params": params}

ALLOWED_TASKS = {
    "ssh: docker_status",
    "ssh: healthz",
    "ssh: backup_now",
    "ssh: caddy_logs",
    "ssh: list_actions",
    "ssh: restart_n8n",
    "ssh: run",
    # n8n api (read-only by default; write gated by N8N_ALLOW_WRITE)
    "n8n: self_test",
    "n8n: workflows_get",
    "n8n: get_workflow",
    "n8n: list_workflows",
    "n8n: workflows_update",
    "n8n: workflows_update_dryrun",
    "n8n: workflows_get_dryrun",
    "n8n: executions_list",
    "ssh: compose_ps",
}
DANGEROUS_TASKS = {"ssh: restart_n8n"}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def load_env() -> None:
    # Загружаем твой эталонный env (как ты описал)
    load_dotenv(os.path.expanduser("~/agent-hub/.agent_env"), override=False)
    # На всякий случай поддержим .env рядом со скриптом
    load_dotenv(override=False)


def get_text_from_message(message) -> str:
    # anthropic SDK возвращает content blocks
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
        # На всякий случай: некоторые версии SDK могут давать dict
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def extract_json(s: str) -> Dict[str, Any]:
    # 1) пробуем как есть
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) выдёргиваем первый JSON-объект из текста
    m = re.search(r"\{.*\}", s, flags=re.S)
    if not m:
        raise ValueError("Claude output does not contain JSON object.")
    candidate = m.group(0)
    return json.loads(candidate)


def validate_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("Plan must contain non-empty 'actions' list.")

    normalized = []
    for i, a in enumerate(actions, start=1):
        if not isinstance(a, dict):
            raise ValueError(f"Action #{i} must be an object.")
        task = a.get("task")
        if task not in ALLOWED_TASKS:
            raise ValueError(f"Action #{i} has invalid task: {task}. Allowed: {sorted(ALLOWED_TASKS)}")
        reason = a.get("reason", "")
        if reason is None:
            reason = ""
        params = a.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"Action #{i} params must be an object.")
        normalized.append({"task": task, "reason": str(reason), "params": params})
    return normalized




def wants_conditional_logs(user_task: str) -> bool:
    """
    Если в задаче явно сказано "только если проблема/если есть проблема" — не запускаем caddy_logs по умолчанию.
    """
    t = (user_task or "").lower()
    markers = [
        "только если есть проблема",
        "только если проблема",
        "если есть проблема",
        "если проблема",
        "only if",
        "if problem",
    ]
    return any(x in t for x in markers)


def normalize_exec_response(task: str, out: Any) -> Dict[str, Any]:
    """
    Приводим ответ webhook к стабильному формату:
    ok, action, stdout, stderr, text, exit_code (+ остальное сохраняем как есть).
    """
    if not isinstance(out, dict):
        return {"ok": False, "action": task, "stdout": "", "stderr": "", "text": str(out), "exit_code": None}

    d = dict(out)
    d.setdefault("ok", False)
    d.setdefault("action", d.get("action") or task)
    d["stdout"] = d.get("stdout") or ""
    d["stderr"] = d.get("stderr") or ""
    d["text"] = d.get("text") or d["stdout"] or ""
    d.setdefault("exit_code", d.get("exit_code", d.get("code", None)))
    if d.get("exit_code") is None:
        d["exit_code"] = 0 if d.get("ok") else 1
    return d
# --- SSH FALLBACK HELPERS (Recovery/self-ops) ---
def _ssh_fallback_actions() -> set[str]:
    raw = os.environ.get("RECOVERY_SSH_ACTIONS", "compose_up,compose_restart,compose_ps,compose_logs")
    return {x.strip() for x in raw.split(",") if x.strip()}

def _call_handv2_via_ssh(params: Dict[str, Any], timeout_s: int = 180) -> Dict[str, Any]:
    """Out-of-band recovery path: Brain -> SSH -> iibotv2. Works even if webhook is down."""
    import subprocess, time, random
    ssh_host = os.environ.get("HANDV2_SSH_HOST", "ii-bot-nout")
    base_cmd = os.environ.get("HANDV2_SSH_CMD", "/usr/local/sbin/iibotv2")
    remote_cmd = f"ALLOW_DANGEROUS=1 {base_cmd}" if str(os.environ.get("ALLOW_DANGEROUS","0")).strip() == "1" else base_cmd
    rid = f"rq_sshfb_{int(time.time())}_{random.randint(1000,9999)}"
    payload = {"task": "ssh: run", "request_id": rid, "params": params}
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", ssh_host, remote_cmd],
            input=(json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
    except Exception as ex:
        msg = f"SSH fallback failed: {ex}"
        return {"ok": False, "action": "ssh: run", "stdout": "", "stderr": msg, "text": msg, "exit_code": 1, "request_id": rid, "_fallback": "ssh"}
    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0 and not stdout.strip():
        msg = (stderr.strip() or f"ssh exit_code={proc.returncode}")
        return {"ok": False, "action": "ssh: run", "stdout": "", "stderr": msg, "text": msg, "exit_code": 1, "request_id": rid, "_fallback": "ssh"}
    try:
        out = json.loads(stdout) if stdout.strip() else {}
        if isinstance(out, dict):
            out.setdefault("request_id", rid)
            out["_fallback"] = "ssh"
            return out
    except Exception:
        pass
    msg = (stderr.strip() or "SSH fallback returned non-JSON")
    return {"ok": False, "action": "ssh: run", "stdout": stdout, "stderr": msg, "text": msg, "exit_code": 1, "request_id": rid, "_fallback": "ssh"}

def call_agent_exec(agent_exec_url: str, task: str, chat_id: Optional[int], timeout_s: int = 30, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"task": task}
    if chat_id is not None:
        payload["chatId"] = chat_id
    if params is not None:
        payload["params"] = params
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.post(agent_exec_url, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as ex:
        # Recovery SSH fallback (only for ssh: run + allowlisted actions)
        if task == "ssh: run" and isinstance(params, dict):
            action = str(params.get("action", "")).strip()
            if action and action in _ssh_fallback_actions():
                print(f"[recovery] webhook unavailable, using ssh fallback for action={action}", file=sys.stderr)

                return _call_handv2_via_ssh(params)
        msg = f"agent-exec call failed: {ex}"
        return {"ok": False, "action": task, "stdout": "", "stderr": msg, "text": msg, "exit_code": 1}

def _n8n_allowlist() -> set[str]:
    raw = os.environ.get("N8N_ALLOW_WORKFLOW_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}

def _n8n_base() -> str:
    base = (os.environ.get("N8N_BASE_URL") or "https://ii-bot-nout.ru/api/v1").rstrip("/")
    return base

def _n8n_key() -> str:
    return os.environ.get("N8N_API_KEY", "")


def _n8n_allow_write() -> bool:
    return str(os.environ.get("N8N_ALLOW_WRITE", "0")).strip() in {"1","true","yes","on"}

def call_n8n(task: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Минимальный n8n API клиент внутри brain.
    READ-only по умолчанию; WRITE будет добавлен позже и включается только при N8N_ALLOW_WRITE=1.
    Возвращает стандартный формат: ok, action, stdout, stderr, text, exit_code.
    """
    base = _n8n_base()
    key = _n8n_key()
    if not key:
        return {"ok": False, "action": task, "stdout": "", "stderr": "N8N_API_KEY not set", "text": "N8N_API_KEY not set", "exit_code": 1}

    allow = _n8n_allowlist()

    def req(method: str, path: str, json_body: Any = None) -> Dict[str, Any]:
        headers = {"X-N8N-API-KEY": key}
        with httpx.Client(timeout=30) as client:
            r = client.request(method, base + path, headers=headers, json=json_body)
            try:
                data = r.json()
                body_txt = json.dumps(data, ensure_ascii=False)
            except Exception:
                body_txt = r.text or ""
            ok = 200 <= r.status_code < 300
            return {
                "ok": ok,
                "action": task,
                "stdout": body_txt if ok else "",
                "stderr": "" if ok else f"{r.status_code} {r.reason_phrase}: {body_txt}",
                "text": body_txt if body_txt else (f"{r.status_code} {r.reason_phrase}"),
                "exit_code": 0 if ok else 1,
                "_http_code": r.status_code,
            }

    if task == "n8n: self_test":
        # легкая проверка: получить 1 workflow
        return req("GET", "/workflows?limit=1")

    if task == "n8n: list_workflows":
        # Возвращаем ТОЛЬКО allowlist (не листаем весь n8n).
        if not allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": "N8N_ALLOW_WORKFLOW_IDS is empty", "text": "N8N_ALLOW_WORKFLOW_IDS is empty", "exit_code": 1}

        items = []
        errors = []
        for wid in sorted(allow):
            r = req("GET", f"/workflows/{wid}")
            if r.get("ok"):
                try:
                    items.append(json.loads(r.get("stdout") or "{}"))
                except Exception:
                    items.append({"id": wid, "raw": r.get("stdout", "")})
            else:
                errors.append({"id": wid, "error": r.get("stderr") or r.get("text")})

        ok = len(errors) == 0
        out_obj = {"workflows": items, "errors": errors}
        txt = json.dumps(out_obj, ensure_ascii=False)
        return {
            "ok": ok,
            "action": task,
            "stdout": txt if ok else "",
            "stderr": "" if ok else txt,
            "text": txt,
            "exit_code": 0 if ok else 1,
        }


    if task == "n8n: executions_list":
        # Read-only: список последних исполнений по workflow_id
        wid = (params or {}).get("workflow_id") or (params or {}).get("id")
        if not wid:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow_id required", "text": "params.workflow_id required", "exit_code": 1}
        if allow and wid not in allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": f"workflow_id not in allowlist: {wid}", "text": f"workflow_id not in allowlist: {wid}", "exit_code": 1}
        limit = int((params or {}).get("limit") or 5)
        if limit < 1: limit = 1
        if limit > 20: limit = 20
        # n8n API: /executions?workflowId=...&limit=...
        return req("GET", f"/executions?workflowId={wid}&limit={limit}")

    if task == "n8n: workflows_get_dryrun":
        # Read-only: GET workflow и посчитать sha256 payload (как если бы делали update), без записи.
        wid = (params or {}).get("workflow_id") or (params or {}).get("id")
        if not wid:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow_id required", "text": "params.workflow_id required", "exit_code": 1}
        if allow and wid not in allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": f"workflow_id not in allowlist: {wid}", "text": f"workflow_id not in allowlist: {wid}", "exit_code": 1}
        r = req("GET", f"/workflows/{wid}")
        if not r.get("ok"):
            return r
        try:
            wf = json.loads(r.get("stdout") or "{}")
        except Exception:
            return {"ok": False, "action": task, "stdout": "", "stderr": "Failed to parse workflow JSON", "text": "Failed to parse workflow JSON", "exit_code": 1}
        # используем ту же логику, что dryrun
        wf2 = dict(wf)
        # id is read-only in n8n API; never send it in body
        wf2.pop("id", None)
        body = json.dumps(wf2, ensure_ascii=False, sort_keys=True)
        import hashlib
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        out_obj = {"workflow_id": wid, "bytes": len(body.encode("utf-8")), "sha256": sha, "note": "get+dryrun ok (no write)"}
        txt = json.dumps(out_obj, ensure_ascii=False)
        return {"ok": True, "action": task, "stdout": txt, "stderr": "", "text": txt, "exit_code": 0}

    if task == "n8n: get_workflow":
        task = "n8n: workflows_get"

    if task == "n8n: workflows_update_dryrun":
        # DRY-RUN: проверка payload для PUT без записи в n8n.
        wid = (params or {}).get("workflow_id") or (params or {}).get("id")
        if not wid:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow_id required", "text": "params.workflow_id required", "exit_code": 1}
        if allow and wid not in allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": f"workflow_id not in allowlist: {wid}", "text": f"workflow_id not in allowlist: {wid}", "exit_code": 1}
        wf = (params or {}).get("workflow") or (params or {}).get("data")
        # allow passing workflow via local JSON file path (params.file)
        if (wf is None or wf == {}) and (params or {}).get("file"):
            try:
                from pathlib import Path
                wf = json.loads(Path(str((params or {}).get("file"))).read_text(encoding="utf-8"))
            except Exception as ex:
                return {"ok": False, "action": task, "stdout": "", "stderr": f"failed to load params.file: {ex}", "text": f"failed to load params.file: {ex}", "exit_code": 1}
        # n8n PUT schema is strict: keep only allowed keys
        if isinstance(wf, dict):
            wf = {k: wf.get(k) for k in ("name","nodes","connections","settings") if k in wf}
            if "settings" not in wf or wf.get("settings") is None:
                wf["settings"] = {}
        if not isinstance(wf, dict) or not wf:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow (object) required", "text": "params.workflow (object) required", "exit_code": 1}
        if "id" in wf and str(wf.get("id")) != str(wid):
            return {"ok": False, "action": task, "stdout": "", "stderr": "workflow.id mismatch with params.workflow_id", "text": "workflow.id mismatch with params.workflow_id", "exit_code": 1}
        wf2 = dict(wf)
        # id is read-only in n8n API; never send it in body
        wf2.pop("id", None)
        body = json.dumps(wf2, ensure_ascii=False, sort_keys=True)
        import hashlib
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        out_obj = {"workflow_id": wid, "bytes": len(body.encode("utf-8")), "sha256": sha, "note": "dry-run ok (no write)"}
        txt = json.dumps(out_obj, ensure_ascii=False)
        return {"ok": True, "action": task, "stdout": txt, "stderr": "", "text": txt, "exit_code": 0}

    if task == "n8n: workflows_update":
        # WRITE-GATE: разрешено только если N8N_ALLOW_WRITE=1 и workflow_id в allowlist.
        if not _n8n_allow_write():
            return {"ok": False, "action": task, "stdout": "", "stderr": "WRITE disabled (set N8N_ALLOW_WRITE=1)", "text": "WRITE disabled (set N8N_ALLOW_WRITE=1)", "exit_code": 1}
        wid = (params or {}).get("workflow_id") or (params or {}).get("id")
        if not wid:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow_id required", "text": "params.workflow_id required", "exit_code": 1}
        if allow and wid not in allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": f"workflow_id not in allowlist: {wid}", "text": f"workflow_id not in allowlist: {wid}", "exit_code": 1}
        wf = (params or {}).get("workflow") or (params or {}).get("data")
        # allow passing workflow via local JSON file path (params.file)
        if (wf is None or wf == {}) and (params or {}).get("file"):
            try:
                from pathlib import Path
                wf = json.loads(Path(str((params or {}).get("file"))).read_text(encoding="utf-8"))
            except Exception as ex:
                return {"ok": False, "action": task, "stdout": "", "stderr": f"failed to load params.file: {ex}", "text": f"failed to load params.file: {ex}", "exit_code": 1}
        # n8n PUT schema is strict: keep only allowed keys
        if isinstance(wf, dict):
            wf = {k: wf.get(k) for k in ("name","nodes","connections","settings") if k in wf}
            if "settings" not in wf or wf.get("settings") is None:
                wf["settings"] = {}
        if not isinstance(wf, dict) or not wf:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow (object) required", "text": "params.workflow (object) required", "exit_code": 1}
        # Безопасность: не позволяем менять другой id внутри тела.
        if "id" in wf and str(wf.get("id")) != str(wid):
            return {"ok": False, "action": task, "stdout": "", "stderr": "workflow.id mismatch with params.workflow_id", "text": "workflow.id mismatch with params.workflow_id", "exit_code": 1}
        wf2 = dict(wf)
        wf2.pop("id", None)
        return req("PUT", f"/workflows/{wid}", json_body=wf2)
    if task == "n8n: workflows_get":
        wid = (params or {}).get("workflow_id") or (params or {}).get("id")
        if not wid:
            return {"ok": False, "action": task, "stdout": "", "stderr": "params.workflow_id required", "text": "params.workflow_id required", "exit_code": 1}
        if allow and wid not in allow:
            return {"ok": False, "action": task, "stdout": "", "stderr": f"workflow_id not in allowlist: {wid}", "text": f"workflow_id not in allowlist: {wid}", "exit_code": 1}
        return req("GET", f"/workflows/{wid}")

    return {"ok": False, "action": task, "stdout": "", "stderr": f"Unsupported n8n task: {task}", "text": f"Unsupported n8n task: {task}", "exit_code": 1}
def plan_with_claude(client: Anthropic, model: str, user_task: str) -> Dict[str, Any]:
    system = (
        "Ты — планировщик действий для DevOps-агента. "
        "Твоя задача: превратить запрос пользователя в минимальный безопасный план действий.\n\n"
        "СТРОГОЕ ТРЕБОВАНИЕ: верни ТОЛЬКО валидный JSON-объект, без markdown и без пояснений вокруг.\n\n"
        "Разрешённые действия (task):\n"
        "- ssh: docker_status\n"
        "- ssh: run\n"
        "- ssh: healthz\n"
        "- ssh: backup_now\n"
        "- ssh: caddy_logs\n"        "- ssh: restart_n8n\n"
        "- n8n: self_test\n"
        "- n8n: workflows_get (params: workflow_id)\n- n8n: workflows_get_dryrun (params: workflow_id, no write)\n\n"
        "Формат ответа JSON:\n"
        "{\n"
        '  "summary": "коротко что делаем",\n'
        '  "actions": [ {"task":"ssh: healthz","reason":"почему"} ],\n'
        '  "finish": {"status":"done|need_more_info","message":"короткий итог","questions":[...]}\n'
        "}\n\n"
        "Правила:\n"
        "- Любые n8n действия выполняй ТОЛЬКО по workflow_id из N8N_ALLOW_WORKFLOW_IDS.\n"
        "- Пока N8N_ALLOW_WRITE=0: НЕ предлагай изменений в n8n, только чтение/self_test.\n"
        "- Для списка workflow используй ТОЛЬКО task 'n8n: list_workflows' (он читает allowlist сам).\n- Если просят sha256/dry-run/hash для workflow: используй ТОЛЬКО task 'n8n: workflows_get_dryrun' (одна action, без передачи данных между actions).\n"
        "- Task 'n8n: workflows_get' / 'n8n: get_workflow' ВСЕГДА требует params.workflow_id и не подходит для 'списка'.\n"
        "- Если в запросе есть фраза \"только если есть проблема / only if problem\": НЕ ставь need_more_info. Всегда выполни базовые проверки (docker_status и healthz), а caddy_logs добавляй ТОЛЬКО если базовые проверки показали проблему.\n"
        "- Делай МИНИМУМ действий, которые реально нужны.\n"
        "- НИКОГДА не возвращай пустой actions: минимум 1 действие всегда.\n"
        "- Если пользователь просит WRITE, но N8N_ALLOW_WRITE=0: добавь read-only действие n8n: get_workflow (с params.workflow_id), а в finish.message объясни, что WRITE заблокирован.\n"
        "- Для docker compose ps используй ТОЛЬКО task \"ssh: compose_ps\" (без params), он по умолчанию проверяет проект \"/opt/n8n\".\n"
        "- Для task \"ssh: run\" поле params ОБЯЗАТЕЛЬНО: {\\\"action\\\":...,\\\"mode\\\":\\\"check|plan|apply\\\",\\\"args\\\":{...}}.\n"
        "- Для docker compose ps используй ТОЛЬКО task \"ssh: run\" с params: {\\\"action\\\":\\\"compose_ps\\\",\\\"mode\\\":\\\"check\\\",\\\"args\\\":{\\\"project_dir\\\": \\\"/opt/n8n\\\"}}. Если путь указан пользователем — подставь его в args.project_dir.\n"
        "- Не придумывай новые task.\n"
        "- Если не хватает данных — ставь finish.status=need_more_info и задай вопросы.\n"
    )

    msg = client.messages.create(
        model=model,
        max_tokens=700,
        messages=[{"role": "user", "content": user_task}],
        system=system,
    )
    text = get_text_from_message(msg)
    return extract_json(text)



def sanitize_response(task: str, out: dict) -> dict:
    """
    Если ответ большой (особенно caddy_logs) — сохраняем полный текст в artifacts/*.log,
    а в JSON оставляем короткую обрезку + путь _saved_to.
    """
    from pathlib import Path
    from datetime import datetime, timezone

    MAX_KEEP = 800
    ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

    def _truncate(text: str) -> str:
        if not text:
            return ""
        if len(text) <= MAX_KEEP:
            return text
        return text[:MAX_KEEP] + "\n...[truncated]...\n"

    def _safe_name(x: str) -> str:
        return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in x)

    stdout = ""
    stderr = ""
    text = ""
    try:
        stdout = out.get("stdout") or ""
        stderr = out.get("stderr") or ""
        text = out.get("text") or ""
    except Exception:
        return out

    needs_save = (task == "ssh: caddy_logs") or (len(stdout) > MAX_KEEP) or (len(stderr) > MAX_KEEP) or (len(text) > MAX_KEEP)
    if not needs_save:
        return out

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fname = f"{ts}_{_safe_name(task.replace(' ', '_').replace(':', '_'))}.log"
    fp = ARTIFACTS_DIR / fname

    parts = []
    if stdout:
        parts.append("=== STDOUT ===\n" + stdout)
    if stderr:
        parts.append("=== STDERR ===\n" + stderr)
    if text and text not in (stdout, stderr):
        parts.append("=== TEXT ===\n" + text)

    fp.write_text("\n\n".join(parts) + "\n", encoding="utf-8", errors="replace")

    out2 = dict(out)
    if stdout:
        out2["stdout"] = _truncate(stdout)
    if stderr:
        out2["stderr"] = _truncate(stderr)
    if text:
        out2["text"] = _truncate(text)
    out2["_saved_to"] = str(fp)
    return out2


def validate_handv2_args(action: str, args: Any, manifests: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """
    Lightweight args validation based on Hand v2 manifests args_schema (subset of JSON Schema).
    Returns error string or None if ok.
    """
    if args in (None, ""):
        args = {}
    if not isinstance(args, dict):
        return "params.args must be an object (dict)"

    mf = None
    if isinstance(manifests, list):
        for m in manifests:
            if isinstance(m, dict) and str(m.get("name", "")).strip() == str(action).strip():
                mf = m
                break
    if not mf:
        # unknown schema => don't block execution
        return None

    schema = mf.get("args_schema") or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    additional = schema.get("additionalProperties", True)

    for r in required:
        if r not in args:
            return f"missing required arg: {r}"

    if additional is False:
        extra = [k for k in args.keys() if k not in props]
        if extra:
            return "unknown args: " + ", ".join(extra)

    for k, v in args.items():
        spec = props.get(k)
        if not isinstance(spec, dict):
            continue
        t = spec.get("type")

        if t == "integer":
            if not isinstance(v, int):
                return f"arg '{k}' must be integer"
            mn = spec.get("minimum")
            mx = spec.get("maximum")
            if isinstance(mn, int) and v < mn:
                return f"arg '{k}' must be >= {mn}"
            if isinstance(mx, int) and v > mx:
                return f"arg '{k}' must be <= {mx}"

        elif t == "string":
            if not isinstance(v, str):
                return f"arg '{k}' must be string"

        elif t == "boolean":
            if not isinstance(v, bool):
                return f"arg '{k}' must be boolean"

    return None


def main() -> int:
    load_env()

    task_text = ' '.join(sys.argv[1:]).strip()

    # Common runtime params (needed for self-discovery and direct ssh: run)
    agent_exec_url = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")
    chat_id_env = os.environ.get("TG_CHAT_ID")
    chat_id = int(chat_id_env) if (chat_id_env and str(chat_id_env).isdigit()) else None

    # DIRECT_SSH_RUN: bypass LLM planning for strict CLI command "ssh: run action=... mode=..."
    _direct = _parse_direct_ssh_run(task_text)
    if _direct:
        # HANDV2_ARGS_VALIDATE
        _p = _direct.get('params') or {}
        _action = str(_p.get('action','')).strip()
        _args = _p.get('args') or {}
        handv2_manifests = refresh_handv2_manifests(agent_exec_url, chat_id) or load_handv2_manifests_cache()
        handv2_index = index_handv2_manifests(handv2_manifests)
        handv2_actions = sorted(handv2_index.keys())

        # apply Hand v2 args defaults from manifest BEFORE validation (direct mode)
        try:
            if not isinstance(_args, dict):
                _args = {}
                _p['args'] = _args
            _m = (handv2_index or {}).get(_action) or {}
            _schema = (_m.get('args_schema') or {}) if isinstance(_m, dict) else {}
            _props = (_schema.get('properties') or {}) if isinstance(_schema, dict) else {}
            if isinstance(_props, dict):
                for _k, _spec in _props.items():
                    if _k not in _args and isinstance(_spec, dict) and 'default' in _spec:
                        _args[_k] = _spec.get('default')
        except Exception:
            pass

        _err = validate_handv2_args(_action, _args, handv2_manifests)
        if _err:
            report = {
                'ok': False,
                'exit_code': 1,
                'summary': f"ssh: run → {_action} rejected: {_err}",
                'results': [{
                    'task': 'ssh: run',
                    'params': _p,
                    'response': {
                        'ok': False,
                        'action': _action,
                        'mode': _p.get('mode','check'),
                        'stdout': '',
                        'stderr': _err,
                        'text': _err,
                        'exit_code': 1,
                    }
                }]
            }
            print(f"[plan] summary: {report['summary']}")
            print("\n[exec] running actions: 1")
            print("\n[exec #1] ssh: run (direct)")
            print("\n[report] done.")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

        resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=_direct.get("params"))
        resp = normalize_exec_response("ssh: run", resp)
        report = {
            "ok": bool(resp.get("ok")),
            "exit_code": int(resp.get("exit_code", 0) or 0),
            "summary": f"ssh: run → {(_direct.get('params') or {}).get('action')} ({(_direct.get('params') or {}).get('mode','check')})",
            "results": [{"task": "ssh: run", "params": _direct.get("params"), "response": resp}],
        }
        print(f"[plan] summary: {report['summary']}")
        print("\n[exec] running actions: 1")
        print("\n[exec #1] ssh: run (direct)")
        print("\n[report] done.")
        print(json.dumps(report, ensure_ascii=False))
        # post-apply health-check (direct mode; runs only after successful apply)
        try:
            _mode = str((_direct.get("params") or {}).get("mode","check")).strip().lower()
            if _mode == "apply" and report.get("ok", False):
                hc = str(Path(__file__).with_name("tools") / "remote_healthcheck.sh")
                if Path(hc).exists():
                    print(f"[exec #1] post-apply healthcheck: {hc}")
                    import subprocess
                    subprocess.run([hc], check=False)
                else:
                    print(f"[exec #1] post-apply healthcheck skipped (missing): {hc}")
        except Exception as _ex:
            print(f"[exec #1] post-apply healthcheck failed: {_ex}")
        raise SystemExit(0 if report["ok"] else 1)


    # Hand v2 self-discovery (refresh manifests; fallback to cache)
    # Hand v2 self-discovery (refresh manifests; fallback to cache)
    handv2_manifests = refresh_handv2_manifests(agent_exec_url, chat_id) or load_handv2_manifests_cache() or []
    handv2_index = index_handv2_manifests(handv2_manifests)
    handv2_actions = sorted(handv2_index.keys())

    if handv2_actions:
        print("[brain] handv2_actions=" + ",".join(handv2_actions))
    else:
        print("[brain] handv2_actions=UNKNOWN (no manifests)")



    user_task = " ".join(sys.argv[1:]).strip()
    if not user_task:
        eprint('Usage: ./agent_brain.py "твоя задача текстом"')
        return 2

    # --- Monitoring shortcuts (rule-based, no LLM) ---

    try:

        _t = user_task.strip()

        _tl = _t.lower()


        def _parse_json_maybe(x):

            try:

                import json as _json

                return _json.loads(x) if x else None

            except Exception:

                return None


        # 1) monitoring: zabbix quickcheck  -> Hand v2 zabbix_quickcheck (verbose JSON)

        if _tl.startswith("monitoring:") and ("zabbix quickcheck" in _tl or "zabbix_quickcheck" in _tl):

            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")

            _chat_id_env = os.environ.get("TG_CHAT_ID")

            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None

            _params = {"action": "zabbix_quickcheck", "mode": "check", "args": {}}

            resp = call_agent_exec(_aeu, "ssh: run", _chat_id, params=_params)

            resp = normalize_exec_response("ssh: run", resp)

            import json as _json

            status = 'OK' if resp.get('ok') else 'FAIL'
            print(f"[plan] summary: zabbix quickcheck {status}")
            print(_json.dumps(resp, ensure_ascii=False))
            raise SystemExit(0 if resp.get('ok') else 1)


        # 1b) monitoring: zabbix status -> alias to zabbix_quickcheck (short OK/FAIL + reason)


        if _tl.startswith("monitoring:") and ("zabbix status" in _tl or "zabbix_status" in _tl):


            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")


            _chat_id_env = os.environ.get("TG_CHAT_ID")


            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None


            _params = {"action": "zabbix_quickcheck", "mode": "check", "args": {}}


            resp = call_agent_exec(_aeu, "ssh: run", _chat_id, params=_params)


            resp = normalize_exec_response("ssh: run", resp)



            out = str(resp.get("stdout") or resp.get("text") or "").strip()


            obj = _parse_json_maybe(out) if out else None


            reason = None


            if isinstance(obj, dict):


                reason = obj.get("reason") or obj.get("summary")


            if not reason:


                arts = resp.get("artifacts") or []


                if isinstance(arts, list):


                    for a in arts:


                        if isinstance(a, dict) and a.get("name") == "zabbix_quickcheck":


                            v = a.get("value")


                            if isinstance(v, dict):


                                reason = v.get("reason") or v.get("summary")


                            break



            ok = bool(resp.get("ok"))


            status = "OK" if ok else "FAIL"


            msg = (str(reason).strip() if reason else "unknown")



            # summary for agent_runner.py


            print(f"[plan] summary: zabbix status {status}")



            # short human output


            print("OK" if ok else f"FAIL: {msg}")



            # final JSON for runner parser (must start at line-beginning with '{')


            import json as _json


            print(_json.dumps({"ok": ok, "status": status, "reason": (None if ok else msg), "source_action": "zabbix_quickcheck"}, ensure_ascii=False))


            raise SystemExit(0 if ok else 1)



        # 2) monitoring: zabbix agent info -> Hand v2 zabbix_agent_info (pretty JSON)

        if _tl.startswith("monitoring:") and ("zabbix agent info" in _tl or "zabbix-agent info" in _tl):

            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")

            _chat_id_env = os.environ.get("TG_CHAT_ID")

            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None

            _params = {"action": "zabbix_agent_info", "mode": "check", "args": {}}

            resp = call_agent_exec(_aeu, "ssh: run", _chat_id, params=_params)

            resp = normalize_exec_response("ssh: run", resp)


            out = str(resp.get("stdout") or resp.get("text") or "").strip()

            obj = _parse_json_maybe(out) if out else None

            if obj is None:

                obj = resp


            import json as _json

            status = 'OK' if resp.get('ok') else 'FAIL'
            print(f"[plan] summary: zabbix agent info {status}")
            print(_json.dumps(obj, ensure_ascii=False))
            raise SystemExit(0 if resp.get('ok') else 1)


    except SystemExit:

        raise

    except Exception as _ex:

        print(f"[monitoring] shortcut failed: {_ex}")

    # --- /Monitoring shortcuts ---


    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        eprint("ERROR: ANTHROPIC_API_KEY not found. Add it to ~/agent-hub/.agent_env")
        return 1

    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    agent_exec_url = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")
    allow_dangerous = os.environ.get("ALLOW_DANGEROUS", "0") == "1"

    # опционально: если хочешь, чтобы ответы дублировались тебе в TG автоматически
    chat_id_env = os.environ.get("TG_CHAT_ID")
    chat_id = int(chat_id_env) if (chat_id_env and chat_id_env.isdigit()) else None

    client = Anthropic(api_key=anthropic_key)

    print(f"[brain] model={model}")
    print(f"[brain] agent_exec_url={agent_exec_url}")
    if chat_id:
        print(f"[brain] TG_CHAT_ID={chat_id}")

    plan = plan_with_claude(client, model, user_task)

    summary = plan.get("summary", "")
    finish = plan.get("finish", {}) if isinstance(plan.get("finish"), dict) else {}
    print("\n[plan] summary:", summary)

    try:
        actions = validate_plan(plan)
    except Exception as ex:
        eprint("\n[plan] INVALID:", ex)
        eprint("[plan raw]:", json.dumps(plan, ensure_ascii=False, indent=2))
        return 1

    if finish.get("status") == "need_more_info" and not wants_conditional_logs(user_task):
        print("\n[plan] need_more_info:", finish.get("message", ""))
        qs = finish.get("questions", [])
        if isinstance(qs, list) and qs:
            print("[plan] questions:")
            for q in qs:
                print(" -", q)
        return 0

    # --- EXEC ---
    conditional_logs = wants_conditional_logs(user_task)

    # если план включает caddy_logs, но это "только если проблема" — выкинем его из базового списка
    base_actions = [a for a in actions if a["task"] != "ssh: caddy_logs"] if conditional_logs else actions

    print("\n[exec] running actions:", len(base_actions))
    results = []
    issue_found = False

    for i, a in enumerate(base_actions, start=1):
        task = a.get('task')
        params = a.get('params') or {}
        reason = a.get('reason', '')

        # ssh: run (Hand v2 preferred; legacy fallback)
        if task == 'ssh: run':
            action = (params or {}).get('action')
            mode = str((params or {}).get('mode') or 'check').strip().lower()
            args = (params or {}).get('args') or {}

            if not action:
                issue_found = True
                results.append({'task': 'ssh: run', 'response': {'ok': False, 'action': 'ssh: run', 'stdout': '', 'stderr': 'params.action required for ssh: run', 'text': 'params.action required for ssh: run', 'exit_code': 1}})
                eprint(f"[exec #{i}] ERROR: params.action required for ssh: run")
                continue

            if mode not in ('check','plan','apply'):
                issue_found = True
                results.append({'task': 'ssh: run', 'response': {'ok': False, 'action': 'ssh: run', 'stdout': '', 'stderr': 'invalid params.mode (use check|plan|apply)', 'text': 'invalid params.mode (use check|plan|apply)', 'exit_code': 1}})
                eprint(f"[exec #{i}] ERROR: invalid params.mode for ssh: run")
                continue

            if not isinstance(args, dict):
                issue_found = True
                results.append({'task': 'ssh: run', 'response': {'ok': False, 'action': 'ssh: run', 'stdout': '', 'stderr': 'params.args must be an object', 'text': 'params.args must be an object', 'exit_code': 1}})
                eprint(f"[exec #{i}] ERROR: params.args must be an object")
                continue

            raw_action = str(action).strip()

            action = raw_action

            hv2_action = raw_action

            if raw_action.startswith('ssh:'):

                hv2_action = raw_action.split(':', 1)[1].strip()


            # Decide whether to use Hand v2 (ssh: run)
            # If args is provided — MUST use Hand v2 (legacy ssh:* has no args support).
            use_hv2 = bool(args)

            try:
                hv2 = set(handv2_index.keys())
            except Exception:
                hv2 = set()

            if hv2 and action in hv2:
                use_hv2 = True

            if use_hv2:
                print(f"\n[exec #{i}] ssh: run → {action} ({mode})")
                if reason:
                    print(f"[exec #{i}] reason: {reason}")

                # apply Hand v2 args defaults from manifest args_schema.properties.*.default

                try:

                    _m = (handv2_index or {}).get(hv2_action) or {}

                    _schema = (_m.get('args_schema') or {}) if isinstance(_m, dict) else {}

                    _props = (_schema.get('properties') or {}) if isinstance(_schema, dict) else {}

                    if isinstance(_props, dict):

                        for _k, _spec in _props.items():

                            if _k not in args and isinstance(_spec, dict) and 'default' in _spec:

                                args[_k] = _spec.get('default')

                except Exception:

                    pass


                out_raw = call_agent_exec(
                    agent_exec_url,
                    "ssh: run",
                    chat_id,
                    params={"action": hv2_action, "mode": mode, "args": args},
                )
                out_norm = normalize_exec_response("ssh: run", out_raw)
                out = sanitize_response("ssh: run", out_norm)
                results.append({"task": "ssh: run", "params": {"action": hv2_action, "mode": mode, "args": args}, "response": out})

                print(f"[exec #{i}] ok={out.get('ok')} action={out.get('action')}")
                stdout = (out.get('stdout') or '')
                stderr = (out.get('stderr') or '')
                if stdout:
                    print(f"[exec #{i}] stdout:", stdout[:600])
                if stderr:
                    print(f"[exec #{i}] stderr:", stderr[:600])
                if not out.get('ok', False):
                    issue_found = True                # post-apply health-check (runs only after successful apply)
                if mode == 'apply' and out.get('ok', False):
                    try:
                        hc = str(Path(__file__).with_name('tools') / 'remote_healthcheck.sh')
                        if Path(hc).exists():
                            print(f"[exec #{i}] post-apply healthcheck: {hc}")
                            subprocess.run([hc], check=False)
                        else:
                            print(f"[exec #{i}] post-apply healthcheck skipped (missing): {hc}")
                    except Exception as _ex:
                        print(f"[exec #{i}] post-apply healthcheck failed: {_ex}")

                continue

            # Legacy fallback (no args support)
            if args not in (None, {}, ''):
                issue_found = True
                results.append({'task': 'ssh: run', 'response': {'ok': False, 'action': 'ssh: run', 'stdout': '', 'stderr': 'legacy ssh:* fallback does not support params.args', 'text': 'legacy ssh:* fallback does not support params.args', 'exit_code': 1}})
                eprint(f"[exec #{i}] ERROR: legacy ssh:* fallback does not support params.args")
                continue

            resolved_task = action if action.startswith('ssh:') else f"ssh: {action}"
            if resolved_task not in ALLOWED_TASKS:
                issue_found = True
                results.append({'task': 'ssh: run', 'resolved_task': resolved_task, 'response': {'ok': False, 'action': resolved_task, 'stdout': '', 'stderr': f"unsupported ssh: run action: {action}", 'text': f"unsupported ssh: run action: {action}", 'exit_code': 1}})
                eprint(f"[exec #{i}] ERROR: unsupported ssh: run action: {action}")
                continue

            task = resolved_task
            params = {}
            print(f"[exec #{i}] ssh: run → {task} (legacy)")

        print(f"\n[exec #{i}] {task}")
        if reason:
            print(f"[exec #{i}] reason: {reason}")

        if task in DANGEROUS_TASKS and not allow_dangerous:
            print(f"[exec #{i}] SKIP (dangerous). Set ALLOW_DANGEROUS=1 to allow.")
            results.append({'task': task, 'skipped': True, 'why': 'dangerous'})
            issue_found = True
            continue

        try:
            out_raw = call_n8n(task, params) if task.startswith('n8n:') else call_agent_exec(agent_exec_url, task, chat_id)
            out_norm = normalize_exec_response(task, out_raw)
            out = sanitize_response(task, out_norm)
            results.append({'task': task, 'response': out})
            print(f"[exec #{i}] ok={out.get('ok')} action={out.get('action')}")
            stdout = (out.get('stdout') or '')
            stderr = (out.get('stderr') or '')
            if stdout:
                print(f"[exec #{i}] stdout:", stdout[:600])
            if stderr:
                print(f"[exec #{i}] stderr:", stderr[:600])
            if not out.get('ok', False):
                issue_found = True
        except Exception as ex:
            issue_found = True
            results.append({'task': task, 'error': str(ex)})
            eprint(f"[exec #{i}] ERROR:", ex)

    # если это был режим "только если проблема" и проблема есть — тогда берём caddy_logs
    if conditional_logs and issue_found:
        print("\n[exec] issue detected → fetching caddy_logs")
        try:
            out_raw = call_agent_exec(agent_exec_url, "ssh: caddy_logs", chat_id)
            out_norm = normalize_exec_response("ssh: caddy_logs", out_raw)
            out = sanitize_response("ssh: caddy_logs", out_norm)
            results.append({"task": "ssh: caddy_logs", "response": out})
            print("[exec] caddy_logs ok=", out.get("ok"), "saved_to=", out.get("_saved_to"))
        except Exception as ex:
            results.append({"task": "ssh: caddy_logs", "error": str(ex)})
            eprint("[exec] caddy_logs ERROR:", ex)

    print("\n[report] done.")
    overall_ok = True
    for it in results:
        if isinstance(it, dict) and it.get("error"):
            overall_ok = False
            break
        if isinstance(it, dict) and it.get("skipped"):
            overall_ok = False
            break
        resp = it.get("response") if isinstance(it, dict) else None
        if isinstance(resp, dict) and resp.get("ok") is False:
            overall_ok = False
            break
    report = {"ok": overall_ok, "exit_code": 0 if overall_ok else 1, "summary": summary, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report["exit_code"]
if __name__ == "__main__":
    raise SystemExit(main())
