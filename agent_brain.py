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
    # --- Hand v2 hardening (manifests-only actions) ---
    # relies on global handv2_index built via index_handv2_manifests(...)
    hv2_allowed = set((handv2_index or {}).keys())
    def _fail(msg: str) -> None:
        raise ValueError(msg)

    # validate each action entry
    for a in (plan or {}).get("actions", []) or []:
        task = a.get("task")
        params = a.get("params") or {}
        # forbid confirm inside args (must be top-level params.confirm)
        if task == "ssh: run":
            args = (params.get("args") or {})
            if isinstance(args, dict) and ("confirm" in args):
                _fail("confirm must be params.confirm (not inside params.args)")
            act = params.get("action")
            if hv2_allowed and act and (act not in hv2_allowed):
                _fail(f"unknown Hand v2 action for ssh: run: {act}")
    # --- end Hand v2 hardening ---

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
        # http2=False to reduce rare empty/truncated-body issues we observed with JSON decode
        with httpx.Client(timeout=timeout_s, http2=False, follow_redirects=True) as client:
            r = client.post(agent_exec_url, json=payload)

        body = (r.text or "")
        if not (200 <= r.status_code < 300):
            msg = f"agent-exec http {r.status_code}: {body[:500]}"
            raise RuntimeError(msg)

        if not body.strip():
            raise RuntimeError("agent-exec empty response body")

        try:
            return r.json()
        except Exception:
            return json.loads(body)

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
    base = (os.environ.get("N8N_BASE_URL") or "https://ii-bot-nout.ru").rstrip("/")
    if not base.endswith("/api/v1"):
        base = base + "/api/v1"
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
def plan_with_claude(client: Anthropic, model: str, user_task: str, handv2_actions: Optional[List[str]] = None) -> Dict[str, Any]:
    hv2_actions = sorted(handv2_actions or [])
    hv2_list = "\n".join(["- " + a for a in hv2_actions]) if hv2_actions else "(no manifests cache)"

    system = (
        "Ты — планировщик действий для DevOps-агента. "
        "Твоя задача: превратить запрос пользователя в минимальный безопасный план действий.\n\n"
        "СТРОГОЕ ТРЕБОВАНИЕ: верни ТОЛЬКО валидный JSON-объект, без markdown и без пояснений вокруг.\n\n"
        "Разрешённые Hand v2 actions (ТОЛЬКО для ssh: run params.action):\n"
        f"{hv2_list}\n\n"
        "СТРОГО: если используешь ssh: run — params.action ДОЛЖЕН быть из списка выше. Нельзя придумывать action.\n"
        "СТРОГО: confirm ТОЛЬКО как params.confirm (НЕ внутри args).\n\n"
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
    global json
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

    

        def _call_ssh_action(_action, _args=None):

            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")

            _chat_id_env = os.environ.get("TG_CHAT_ID")

            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None

            _params = {"action": _action, "mode": "check", "args": (_args or {})}

            _resp = call_agent_exec(_aeu, "ssh: run", _chat_id, params=_params)

            return normalize_exec_response("ssh: run", _resp)

    

                # monitoring: all status -> server + sites + n8n + disk (one-shot)
        if _tl.startswith("monitoring:") and ("all status" in _tl or "all_status" in _tl):
            import json as _json, re as _re, subprocess

            def _curl_code(url: str, timeout_s: int = 4) -> int:
                try:
                    p = subprocess.run(
                        ["curl","-ksS","-o","/dev/null","-w","%{http_code}","--max-time",str(timeout_s),url],
                        capture_output=True, text=True
                    )
                    if p.returncode != 0:
                        return 0
                    t = (p.stdout or "").strip()
                    return int(t) if t.isdigit() else 0
                except Exception:
                    return 0

            base_url = os.environ.get("N8N_BASE_URL", "https://ii-bot-nout.ru").rstrip("/")

            # --- server status bits ---
            r_docker = _call_ssh_action("docker_status", {})
            r_health = _call_ssh_action("healthz", {})
            r_caddy  = _call_ssh_action("caddy_logs", {"since_seconds": 300, "tail": 200, "only_errors": True})

            health_obj = _parse_json_maybe(str(r_health.get("stdout") or r_health.get("text") or "").strip()) or {}
            health_ok = bool(r_health.get("ok")) and (health_obj.get("status") == "ok")
            docker_ok = bool(r_docker.get("ok"))

            caddy_text = str(r_caddy.get("stdout") or r_caddy.get("text") or "")
            caddy_errs = caddy_text.count('\"level\":\"error\"') + caddy_text.count('"level":"error"')

            code_root = _curl_code(f"{base_url}/")
            code_healthz = _curl_code(f"{base_url}/healthz")
            http_ok = (code_root == 200 and code_healthz == 200)

            server_ok = bool(docker_ok and health_ok and http_ok and (caddy_errs == 0))

            # --- sites status bits ---
            docker_out = str(r_docker.get("stdout") or r_docker.get("text") or "")
            site_names = []
            site_up_map = {}
            for line in docker_out.splitlines():
                m = _re.match(r"^([A-Za-z0-9_-]+)-web-1\s+(.*)$", line.strip())
                if not m:
                    continue
                n = m.group(1)
                site_names.append(n)
                site_up_map[n] = (" up " in (" " + m.group(2).lower() + " "))

            sites = []
            up = blocked = down = other = 0
            for n in sorted(set(site_names)):
                code = _curl_code(f"{base_url}/{n}/")
                st_up = bool(site_up_map.get(n, False))
                if st_up and code == 200:
                    state = "up"; up += 1
                elif st_up and code == 404:
                    state = "blocked"; blocked += 1
                elif (not st_up) or code in (0, 502, 503, 504):
                    state = "down"; down += 1
                else:
                    state = "other"; other += 1

                sites.append({"name": n, "http": int(code), "state": state})

            total = len(sites)
            sites_ok = (down == 0 and other == 0)

            # --- n8n status bits ---
            n8n_up = ("n8n-n8n-1" in docker_out) and ("n8n-n8n-1" in docker_out and (" up " in docker_out.lower()))
            n8n_ok = bool(http_ok and n8n_up and (caddy_errs == 0))

            # --- disk quickcheck ---
            r_disk = _call_ssh_action("disk_quickcheck", {})

            # if webhook doesn't know disk_quickcheck, fallback via SSH directly to Hand v2
            try:
                _t = str(r_disk.get("text") or r_disk.get("stdout") or "")
                if (not r_disk.get("ok")) and ("Не понял команду" in _t or not r_disk.get("request_id")):
                    payload = _json.dumps({"task":"ssh: run","params":{"action":"disk_quickcheck","mode":"check","args":{}}}, ensure_ascii=False)
                    p2 = subprocess.run(
                        ["ssh","ii-bot-nout","/usr/local/sbin/iibotv2"],
                        input=payload,
                        text=True,
                        capture_output=True,
                        timeout=30
                    )
                    if p2.returncode == 0 and (p2.stdout or "").strip():
                        # take last line in case ssh prints noise
                        last = (p2.stdout or "").strip().splitlines()[-1]
                        r2 = _json.loads(last)
                        r_disk = normalize_exec_response("ssh: run", r2)
            except Exception:
                pass

            disk_ok = bool(r_disk.get("ok"))

            ok_all = bool(server_ok and sites_ok and n8n_ok and disk_ok)
            status = "OK" if ok_all else "FAIL"

            summary = f"all status {status} (sites total={total} up={up} blocked={blocked} down={down} other={other})"
            print(f"[plan] summary: {summary}")

            out = {
                "ok": ok_all,
                "status": status,
                "summary": summary,
                "server": {
                    "ok": server_ok,
                    "root_http": int(code_root),
                    "healthz_http": int(code_healthz),
                    "health_ok": bool(health_ok),
                    "docker_ok": bool(docker_ok),
                    "caddy_errors_5m": int(caddy_errs),
                    "request_ids": {
                        "docker_status": r_docker.get("request_id"),
                        "healthz": r_health.get("request_id"),
                        "caddy_logs": r_caddy.get("request_id"),
                    },
                },
                "sites": {
                    "ok": sites_ok,
                    "total": int(total),
                    "up": int(up),
                    "blocked": int(blocked),
                    "down": int(down),
                    "other": int(other),
                    "items": sites,
                },
                "n8n": {
                    "ok": n8n_ok,
                    "n8n_up": bool(n8n_up),
                    "root_http": int(code_root),
                    "healthz_http": int(code_healthz),
                    "caddy_errors_5m": int(caddy_errs),
                },
                "disk": {
                    "ok": disk_ok,
                    "request_id": r_disk.get("request_id"),
                    "text": r_disk.get("text") or r_disk.get("stdout") or "",
                },
            }
            print(_json.dumps(out, ensure_ascii=False))
            raise SystemExit(0 if ok_all else 1)




        # monitoring: all fix -> run sites: fix (dryrun/apply) then re-check all status (rule-based, no LLM)
        if _tl.startswith("monitoring:") and ("all fix" in _tl or "all_fix" in _tl):
            import json as _json, subprocess, sys as _sys

            apply = ("apply=1" in _tl) or ("apply:true" in _tl) or ("apply=yes" in _tl)

            def _last_json(stdout: str) -> dict:
                s = (stdout or "").strip()
                if not s:
                    return {}
                last = s.splitlines()[-1].strip()
                try:
                    return _json.loads(last)
                except Exception:
                    return {}

            # 1) sites: fix (dryrun or apply=1) via self-subprocess (reuses existing shortcut logic)
            if apply and os.environ.get("ALLOW_DANGEROUS") != "1":
                out = {
                    "ok": False,
                    "status": "BLOCKED",
                    "summary": "all fix BLOCKED (need ALLOW_DANGEROUS=1 for apply=1)",
                }
                print(_json.dumps(out, ensure_ascii=False))
                raise SystemExit(1)

            sites_cmd = "sites: fix apply=1" if apply else "sites: fix"
            p1 = subprocess.run(
                [_sys.executable, str(Path(__file__)), sites_cmd],
                capture_output=True, text=True, timeout=300
            )
            sites_obj = _last_json(p1.stdout)

            # 2) re-check monitoring: all status
            p2 = subprocess.run(
                [_sys.executable, str(Path(__file__)), "monitoring: all status"],
                capture_output=True, text=True, timeout=300
            )
            st_obj = _last_json(p2.stdout)

            ok_all = bool(st_obj.get("ok"))
            status = "OK" if ok_all else "FAIL"

            s_sites = str(sites_obj.get("summary") or "").strip()
            s_stat  = str(st_obj.get("summary") or "").strip()
            mode    = "APPLY" if apply else "DRYRUN"
            summary = f"all fix {mode} → {s_sites} | then {s_stat}".strip()

            print(f"[plan] summary: {summary}")
            out = {
                "ok": ok_all,
                "status": status,
                "summary": summary,
                "sites_fix": sites_obj,
                "all_status": st_obj,
            }
            print(_json.dumps(out, ensure_ascii=False))
            raise SystemExit(0 if ok_all else 1)

        # monitoring: server status -> docker_status + healthz + caddy_logs (tail 30)

        if _tl.startswith("monitoring:") and ("server status" in _tl or "server_status" in _tl):

            r_docker = _call_ssh_action("docker_status", {})

            r_health = _call_ssh_action("healthz", {})

            r_caddy  = _call_ssh_action("caddy_logs", {"since_seconds": 300, "tail": 200, "only_errors": True})

    

            health_obj = _parse_json_maybe(str(r_health.get("stdout") or r_health.get("text") or "").strip()) or {}

            health_ok = bool(r_health.get("ok")) and (health_obj.get("status") == "ok")

            docker_ok = bool(r_docker.get("ok"))

    

            caddy_text = str(r_caddy.get("stdout") or r_caddy.get("text") or "")

            caddy_errs = caddy_text.count('\"level\":\"error\"') + caddy_text.count('"level":"error"')

    

            ok = bool(docker_ok and health_ok and (caddy_errs == 0))

            status = "OK" if ok else "FAIL"


            def _curl_code(url: str, timeout_s: int = 3) -> int:
                import subprocess
                try:
                    p = subprocess.run(
                        ["curl", "-ksS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout_s), url],
                        capture_output=True, text=True
                    )
                    if p.returncode != 0:
                        return 0
                    t = (p.stdout or "").strip()
                    return int(t) if t.isdigit() else 0
                except Exception:
                    return 0

            base_url = os.environ.get("N8N_BASE_URL", "https://ii-bot-nout.ru").rstrip("/")

            code_root = _curl_code(f"{base_url}/")
            code_healthz = _curl_code(f"{base_url}/healthz")

            http_ok = (code_root == 200 and code_healthz == 200)
            if not http_ok:
                ok = False
                status = "FAIL"
    

            extra = f" (caddy_errors_5m={caddy_errs})" if caddy_errs else ""

            print(f"[plan] summary: server status {status}"+extra)

    

            import json as _json

            out = {

                "ok": ok,

                "status": status,

                "reason": None if ok else ("http probe failed" if not http_ok else ("healthz not ok" if not health_ok else ("docker_status failed" if not docker_ok else f"caddy errors last 5m: {caddy_errs}"))),

                "checks": {
                    "http_probe": {
                        "ok": bool(http_ok),
                        "root_http": int(code_root),
                        "healthz_http": int(code_healthz),
                    },

                    "docker_status": {

                        "ok": bool(r_docker.get("ok")),

                        "request_id": r_docker.get("request_id"),

                        "text": r_docker.get("text") or r_docker.get("stdout") or "",

                    },

                    "healthz": {

                        "ok": bool(health_ok),

                        "request_id": r_health.get("request_id"),

                        "raw": r_health.get("text") or r_health.get("stdout") or "",

                    },

                    "caddy_logs_5m": {

                        "ok": bool(r_caddy.get("ok")),

                        "request_id": r_caddy.get("request_id"),

                        "error_count": int(caddy_errs),

                        "text": caddy_text,

                    },

                },

            }

            print(_json.dumps(out, ensure_ascii=False))

            raise SystemExit(0 if ok else 1)

    

        
        # monitoring: caddy errors since_seconds=300 -> Hand v2 caddy_logs (only_errors)
        if _tl.startswith("monitoring:") and ("caddy errors" in _tl or "caddy_errors" in _tl):
            m = re.search(r"\bsince_seconds\s*=\s*(\d+)", _tl)
            since_s = int(m.group(1)) if m else 300
            if since_s < 1:
                since_s = 300
            if since_s > 86400:
                since_s = 86400

            r_caddy = _call_ssh_action("caddy_logs", {"since_seconds": since_s, "tail": 200, "only_errors": True})

            caddy_text = str(r_caddy.get("stdout") or r_caddy.get("text") or "")
            caddy_errs = caddy_text.count('\"level\":\"error\"') + caddy_text.count('"level":"error"')

            ok = bool(r_caddy.get("ok"))
            status = "OK" if ok else "FAIL"
            extra = f" (errors={caddy_errs})" if caddy_errs else " (no errors)"

            print(f"[plan] summary: caddy errors {status} since_seconds={since_s}"+extra)

            import json as _json
            out = {
                "ok": ok,
                "status": status,
                "since_seconds": int(since_s),
                "error_count": int(caddy_errs),
                "request_id": r_caddy.get("request_id"),
                "text": caddy_text,
            }
            print(_json.dumps(out, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)

# 1) monitoring: zabbix quickcheck  -> Hand v2 zabbix_quickcheck (verbose JSON)

        if _tl.startswith("monitoring:") and ("zabbix quickcheck" in _tl or "zabbix_quickcheck" in _tl):

            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")

            _chat_id_env = os.environ.get("TG_CHAT_ID")

            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None

            _args = {}

            m = re.search(r"\bport\s*=\s*(\d+)", _tl)

            if m:

                _args["port"] = int(m.group(1))

            m = re.search(r"\ballowed_ips\s*=\s*(\[[^\]]*\])", _tl)

            if m:

                try:

                    _args["allowed_ips"] = json.loads(m.group(1).replace("'", '"'))

                except Exception:

                    _args["allowed_ips"] = [x.strip() for x in m.group(1).strip('[]').split(',') if x.strip()]

            _params = {"action": "zabbix_quickcheck", "mode": "check", "args": _args}
            resp = call_agent_exec(_aeu, "ssh: run", _chat_id, params=_params)

            resp = normalize_exec_response("ssh: run", resp)

            import json as _json

            status = 'OK' if resp.get('ok') else 'FAIL'

            print(f"[plan] summary: zabbix quickcheck {status}")

            print(_json.dumps(resp, ensure_ascii=False))

            raise SystemExit(0 if resp.get("ok") else 1)

    

        # 1b) monitoring: zabbix status -> alias to zabbix_quickcheck (short OK/FAIL + reason)

        if _tl.startswith("monitoring:") and ("zabbix status" in _tl or "zabbix_status" in _tl):

            _aeu = os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")

            _chat_id_env = os.environ.get("TG_CHAT_ID")

            _chat_id = int(_chat_id_env) if (_chat_id_env and _chat_id_env.isdigit()) else None

            _args = {}

            m = re.search(r"\bport\s*=\s*(\d+)", _tl)

            if m:

                _args["port"] = int(m.group(1))

            m = re.search(r"\ballowed_ips\s*=\s*(\[[^\]]*\])", _tl)

            if m:

                try:

                    _args["allowed_ips"] = json.loads(m.group(1).replace("'", '"'))

                except Exception:

                    _args["allowed_ips"] = [x.strip() for x in m.group(1).strip('[]').split(',') if x.strip()]

            _params = {"action": "zabbix_quickcheck", "mode": "check", "args": _args}
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

            import json as _json

            if ok:

                print("[plan] summary: zabbix status OK")

                print(_json.dumps({"ok": True, "status": "OK", "reason": None, "source_action": "zabbix_quickcheck"}, ensure_ascii=False))

                raise SystemExit(0)

            else:

                msg = (str(reason).strip() if reason else "unknown")

                print("[plan] summary: zabbix status FAIL")

                print(_json.dumps({"ok": False, "status": "FAIL", "reason": msg, "source_action": "zabbix_quickcheck"}, ensure_ascii=False))

                raise SystemExit(1)

    

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

            raise SystemExit(0 if resp.get("ok") else 1)

    

    except SystemExit:

        raise

    except Exception as _ex:

        print(f"[monitoring] shortcut failed: {_ex}")

    # --- n8n status shortcut (rule-based)
    if user_task.lower().startswith("monitoring: n8n status"):
        import os as _os, json
        import httpx

        base_url = _os.getenv("N8N_BASE_URL", "https://ii-bot-nout.ru").rstrip("/")
        errors_window = 300

        def _http_ok(url: str, timeout: float = 8.0):
            try:
                r = httpx.get(url, timeout=timeout, follow_redirects=True)
                return (200 <= r.status_code < 300), r.status_code
            except Exception:
                return False, 0

        def _ssh_run(action: str, args: dict):
            params = {"action": action, "mode": "check", "args": args}
            return call_agent_exec(agent_exec_url, "ssh: run", chat_id, timeout_s=30, params=params)

        ok_root, code_root = _http_ok(f"{base_url}/")
        ok_health, code_health = _http_ok(f"{base_url}/healthz")

        r_compose = _ssh_run("compose_ps", {"project_dir": "/opt/n8n"})
        r_healthz = _ssh_run("healthz", {})
        r_caddy_err = _ssh_run("caddy_logs", {"since_seconds": errors_window, "tail": 200, "only_errors": True})

        compose_stdout = (r_compose.get("stdout") or "")
        n8n_up = ("n8n" in compose_stdout.lower()) and ("up" in compose_stdout.lower())

        caddy_errs = (r_caddy_err.get("stdout") or "").strip()
        has_caddy_errors = (len(caddy_errs) > 0) and ('-- No entries --' not in caddy_errs)

        ok = bool(ok_root and ok_health and r_compose.get("ok") and r_healthz.get("ok") and n8n_up and (not has_caddy_errors))
        summary = "n8n status OK" if ok else "n8n status FAIL"

        print(f"[plan] summary: {summary} (root={code_root}, healthz={code_health}, n8n_up={n8n_up}, caddy_errors={int(has_caddy_errors)})")

        out = {
            "ok": ok,
            "summary": summary,
            "brain_report": {
                "http": {
                    "base_url": base_url,
                    "root": {"ok": ok_root, "status_code": code_root},
                    "healthz": {"ok": ok_health, "status_code": code_health},
                },
                "compose_ps": r_compose,
                "healthz_action": r_healthz,
                "caddy_errors": {
                    "since_seconds": errors_window,
                    "has_errors": has_caddy_errors,
                    "raw": caddy_errs[:2000],
                    "result": r_caddy_err,
                },
            },
        }

        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /n8n status shortcut

    # --- n8n logs shortcut (rule-based)
    if user_task.lower().startswith("monitoring: n8n logs"):

        # parse last=N (default 200)
        last = 200
        try:
            parts = user_task.split()
            for p2 in parts:
                if p2.startswith("last="):
                    last = int(p2.split("=",1)[1])
        except Exception:
            last = 200

        params = {
            "action": "compose_logs",
            "mode": "check",
            "args": {"project_dir": "/opt/n8n", "tail": last},
        }

        r_logs = call_agent_exec(agent_exec_url, "ssh: run", chat_id, timeout_s=60, params=params)
        ok = bool(r_logs.get("ok"))

        summary = "n8n logs OK" if ok else "n8n logs FAIL"
        print(f"[plan] summary: {summary} (tail={last})")

        out = {"ok": ok, "summary": summary, "brain_report": {"tail": last, "compose_logs": r_logs}}
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /n8n logs shortcut

    # --- n8n restart shortcut (HIGH + confirm)
    if user_task.lower().startswith("monitoring: n8n restart"):

        # parse confirm=TOKEN (required for apply)
        confirm = ""
        try:
            parts = user_task.split()
            for p2 in parts:
                if p2.startswith("confirm="):
                    confirm = p2.split("=", 1)[1].strip()
        except Exception:
            confirm = ""

        mode = "apply" if confirm else "check"

        params = {
            "action": "compose_restart",
            "mode": mode,
            "args": {"project_dir": "/opt/n8n"},
        }
        if confirm:
            params["confirm"] = confirm

        r = call_agent_exec(agent_exec_url, "ssh: run", chat_id, timeout_s=60, params=params)
        ok = bool(r.get("ok"))

        if mode == "check" and (not ok):
            summary = "n8n restart CHECK blocked (need confirm)"
        else:
            summary = "n8n restart OK" if ok else "n8n restart FAIL"

        print(f"[plan] summary: {summary} (mode={mode})")

        out = {"ok": ok, "summary": summary, "brain_report": {"mode": mode, "confirm_set": bool(confirm), "result": r}}
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /n8n restart shortcut


    # --- recovery: n8n restart shortcut (FORCE SSH fallback)
    if user_task.lower().startswith("recovery: n8n restart"):

        # parse confirm=TOKEN (required for apply)
        confirm = ""
        try:
            parts = user_task.split()
            for p2 in parts:
                if p2.startswith("confirm="):
                    confirm = p2.split("=", 1)[1].strip()
        except Exception:
            confirm = ""

        mode = "apply" if confirm else "check"

        params = {
            "action": "compose_restart",
            "mode": mode,
            "args": {"project_dir": "/opt/n8n"},
        }
        if confirm:
            params["confirm"] = confirm

        # force out-of-band path (works even if webhook is down)
        r = _call_handv2_via_ssh(params, timeout_s=180)
        ok = bool(r.get("ok"))

        if mode == "check" and (not ok):
            summary = "recovery n8n restart CHECK blocked (need confirm)"
        else:
            summary = "recovery n8n restart OK" if ok else "recovery n8n restart FAIL"

        print(f"[plan] summary: {summary} (mode={mode})")

        out = {"ok": ok, "summary": summary, "brain_report": {"mode": mode, "confirm_set": bool(confirm), "forced_fallback": "ssh", "result": r}}
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /recovery n8n restart shortcut

    # --- recovery: all fix shortcut (safe-ish fixer: sites unblock + n8n restart via forced SSH fallback)
    if user_task.lower().startswith("recovery: all fix"):

        import subprocess, sys as _sys, json as _json

        def _last_json(stdout: str) -> dict:
            s = (stdout or "").strip()
            if not s:
                return {}
            last = s.splitlines()[-1].strip()
            try:
                return _json.loads(last)
            except Exception:
                return {}

        def _run_self(task_text: str, timeout_s: int = 300) -> dict:
            p2 = subprocess.run(
                [_sys.executable, str(Path(__file__)), task_text],
                capture_output=True, text=True, timeout=timeout_s
            )
            return _last_json(p2.stdout)

        tl = user_task.lower()
        apply = ("apply=1" in tl) or ("apply:true" in tl) or ("apply=yes" in tl)

        # optional confirm=TOKEN for n8n restart apply
        confirm = ""
        try:
            for p2 in user_task.split():
                if p2.startswith("confirm="):
                    confirm = p2.split("=", 1)[1].strip()
        except Exception:
            confirm = ""

        # 1) initial status
        st1 = _run_self("monitoring: all status", timeout_s=120)
        ok1 = bool(st1.get("ok"))

        actions = []
        notes = []

        if ok1 and (not apply):
            summary = "recovery all fix DRYRUN → nothing to fix | then all status OK"
            print(f"[plan] summary: {summary}")
            out = {"ok": True, "summary": summary, "brain_report": {"apply": False, "actions": actions, "status_before": st1}}
            print(json.dumps(out, ensure_ascii=False))
            return

        # parse bits
        sites = st1.get("sites") if isinstance(st1.get("sites"), dict) else {}
        n8n   = st1.get("n8n")   if isinstance(st1.get("n8n"), dict)   else {}

        blocked = int(sites.get("blocked", 0) or 0) if isinstance(sites, dict) else 0
        n8n_ok  = bool(n8n.get("ok")) if isinstance(n8n, dict) else True

        # 2) DRYRUN: print what we would do
        if (not apply):
            if blocked > 0:
                actions.append("would run: sites: fix apply=1 (needs ALLOW_DANGEROUS=1)")
            if not n8n_ok:
                if confirm:
                    actions.append(f"would run: recovery: n8n restart confirm={confirm} (forced SSH fallback; needs ALLOW_DANGEROUS=1)")
                else:
                    actions.append("would run: recovery: n8n restart confirm=TOKEN (forced SSH fallback; needs ALLOW_DANGEROUS=1)")
            summary = "recovery all fix DRYRUN → " + ("; ".join(actions) if actions else "nothing to fix") + f" | then all status {'OK' if ok1 else 'FAIL'}"
            print(f"[plan] summary: {summary}")
            out = {"ok": ok1, "summary": summary, "brain_report": {"apply": False, "actions": actions, "status_before": st1}}
            print(json.dumps(out, ensure_ascii=False))
            return

        # 3) APPLY requires ALLOW_DANGEROUS=1
        if os.environ.get("ALLOW_DANGEROUS") != "1":
            summary = "recovery all fix BLOCKED (need ALLOW_DANGEROUS=1 for apply=1)"
            print(f"[plan] summary: {summary}")
            out = {"ok": False, "summary": summary, "brain_report": {"apply": True, "blocked": True, "actions": actions, "status_before": st1}}
            print(json.dumps(out, ensure_ascii=False))
            return

        # 4) APPLY: sites fix (unblock) if needed
        sites_obj = {}
        if blocked > 0:
            sites_obj = _run_self("sites: fix apply=1", timeout_s=300)
            actions.append("ran: sites: fix apply=1")

        # 5) APPLY: n8n restart (forced ssh fallback) if needed and confirm provided
        n8n_obj = {}
        if (not n8n_ok):
            if not confirm:
                notes.append("n8n not ok: missing confirm=TOKEN → skipped restart")
            else:
                # call forced ssh fallback directly
                params = {"action": "compose_restart", "mode": "apply", "args": {"project_dir": "/opt/n8n"}, "confirm": confirm}
                r = _call_handv2_via_ssh(params, timeout_s=180)
                n8n_obj = {"ok": bool(r.get("ok")), "result": r}
                actions.append(f"ran: recovery: n8n restart confirm={confirm} (forced ssh)")

        # 6) final status
        st2 = _run_self("monitoring: all status", timeout_s=120)
        ok2 = bool(st2.get("ok"))

        summary = "recovery all fix APPLY → " + ("; ".join(actions) if actions else "nothing to do") + f" | then all status {'OK' if ok2 else 'FAIL'}"
        print(f"[plan] summary: {summary}")
        out = {
            "ok": ok2,
            "summary": summary,
            "brain_report": {
                "apply": True,
                "actions": actions,
                "notes": notes,
                "status_before": st1,
                "sites_fix": sites_obj,
                "n8n_restart": n8n_obj,
                "status_after": st2,
            },
        }
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /recovery: all fix shortcut



    # --- postgres status shortcut (rule-based)
    if user_task.lower().startswith("monitoring: postgres status"):

        params = {
            "action": "compose_ps",
            "mode": "check",
            "args": {"project_dir": "/opt/n8n"},
        }

        r_ps = call_agent_exec(agent_exec_url, "ssh: run", chat_id, timeout_s=30, params=params)
        ok = bool(r_ps.get("ok"))

        stdout = (r_ps.get("stdout") or "").lower()
        pg_up = ("postgres" in stdout) and ("up" in stdout)

        ok = bool(ok and pg_up)
        summary = "postgres status OK" if ok else "postgres status FAIL"

        print(f"[plan] summary: {summary} (pg_up={pg_up})")

        out = {"ok": ok, "summary": summary, "brain_report": {"compose_ps": r_ps}}
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /postgres status shortcut

    # --- disk quickcheck shortcut (rule-based)
    if user_task.lower().startswith("monitoring: disk quickcheck"):
        import os as _os
        import subprocess as _subprocess

        params = {"action": "disk_quickcheck", "mode": "check", "args": {}}

        # 1) Try via webhook (n8n gateway)
        _aeu = _os.environ.get("AGENT_EXEC_URL", "https://ii-bot-nout.ru/webhook/agent-exec")
        r = call_agent_exec(_aeu, "ssh: run", chat_id, timeout_s=30, params=params)
        r = normalize_exec_response("ssh: run", r)

        txt = str(r.get("text") or r.get("stdout") or "").strip()
        ok = bool(r.get("ok", False))

        # 2) If gateway says "Не понял команду" → fallback directly to Hand v2 over SSH
        fb = None
        if (not ok) and ("Не понял команду" in txt):
            try:
                host = _os.environ.get("HANDV2_SSH_HOST", "ii-bot-nout")
                payload = {"task": "ssh: run", "params": params}
                proc = _subprocess.run(
                    ["ssh", host, "/usr/local/sbin/iibotv2"],
                    input=(json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
                    capture_output=True,
                    timeout=30,
                )
                out_s = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
                try:
                    fb = json.loads(out_s) if out_s else {"ok": False, "stderr": "empty stdout from iibotv2"}
                except Exception:
                    fb = {"ok": False, "stderr": "non-json stdout from iibotv2", "stdout": out_s}
                fb = normalize_exec_response("ssh: run", fb)
                if fb.get("ok"):
                    r = fb
                    ok = True
            except Exception as _ex:
                fb = {"ok": False, "stderr": f"ssh fallback failed: {_ex}"}

        summary = "disk quickcheck OK" if ok else "disk quickcheck FAIL"
        print(f"[plan] summary: {summary}")

        out = {
            "ok": ok,
            "summary": summary,
            "brain_report": {
                "final": r,
                "ssh_fallback": fb,
            },
        }
        print(json.dumps(out, ensure_ascii=False))
        return
    # --- /disk quickcheck shortcut


    # --- sites group status shortcut (rule-based)

    # alias: sites: fix (auto-fix using first hint from sites status)
    # default = dry-run (no changes). add apply=1 to execute the first suggested fix.
    if user_task.lower().startswith("sites: fix"):
        # Examples:
        #   sites: fix
        #   sites: fix apply=1   (requires ALLOW_DANGEROUS=1 because it will do apply with confirm)
        import re as _re
        from urllib.request import Request as _Req, urlopen as _urlopen
        from urllib.error import HTTPError as _HTTPError

        try:
            raw = user_task.strip()
            parts = raw.split()
            kv = {}
            for tok in parts[2:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            do_apply = str(kv.get("apply", "0")).strip().lower() in ("1", "true", "yes")

            # --- 1) collect sites via docker_status ---
            ds_params = {"action": "docker_status", "mode": "check", "args": {}}
            ds_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=ds_params)
            ds_resp = normalize_exec_response("ssh: run", ds_resp)

            names = []
            if ds_resp.get("ok"):
                for line in str(ds_resp.get("stdout", "")).splitlines():
                    m = _re.match(r"^([A-Za-z0-9_-]+)-web-1\s", line.strip())
                    if m:
                        names.append(m.group(1))
            names = sorted(set(names))

            base_url = os.environ.get("SITE_BASE_URL") or agent_exec_url.split("/webhook/")[0].rstrip("/")
            sites = []
            results = [{"task": "ssh: run", "params": ds_params, "response": ds_resp}]
            issue_found = False

            for name in names:
                url = f"{base_url}/{name}/"
                # HTTP probe (curl is more reliable than urllib for HEAD+TLS)
                code = 0
                err = ""
                try:
                    sp = __import__("subprocess")
                    cp = sp.run(
                        ["curl","-ksS","-o","/dev/null","-w","%{http_code}","--max-time","10", url],
                        capture_output=True, text=True, timeout=10
                    )
                    out = (cp.stdout or "").strip()
                    if out.isdigit():
                        code = int(out)
                    else:
                        code = 0
                    if cp.returncode != 0:
                        err = (cp.stderr or "").strip() or f"curl rc={cp.returncode}"
                except Exception as e:
                    err = str(e)

                # infer route/state from HTTP
                if code in (200, 502):
                    route = "present"
                elif code == 404:
                    route = "blocked_or_missing"
                else:
                    route = "unknown"

                if code == 200:
                    state = "up"
                elif code == 502:
                    state = "down"
                elif code == 404:
                    state = "blocked_or_missing"
                else:
                    state = "other"

                if state != "up":
                    issue_found = True

                sites.append({"name": name, "http": code, "route": route, "state": state})
                results.append({"task": "http: head", "params": {"url": url}, "response": {"ok": (code == 200), "url": url, "http_code": code, "error": err}})

            # --- 2) build hints (first one is used for fix) ---
            hints = []
            for it in sites:
                n = str(it.get("name") or "").strip()
                st = str(it.get("state") or "").strip()
                if not n:
                    continue
                if st == "down":
                    up_token = "UP_" + n.upper().replace("-", "_")
                    hints.append(f"hint: recover → site: up name={n} confirm={up_token}")
                if st == "blocked_or_missing":
                    unb_token = "ROUTE_" + n.upper().replace("-", "_")
                    hints.append(f"hint: publish → site: unblock name={n} confirm={unb_token}")

            status = "OK" if not issue_found else "FAIL"
            summary = f"sites fix {status} (total={len(sites)})"

            # nothing to fix
            if not issue_found or not hints:
                report = {"ok": (not issue_found), "exit_code": 0 if not issue_found else 1, "summary": summary, "base_url": base_url, "sites": sites, "hints": hints, "results": results}
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(0 if not issue_found else 1)

            # pick first hint and extract cmd after "→"
            first_hint = hints[0]
            cmd = first_hint.split("→", 1)[1].strip() if "→" in first_hint else ""
            if "(" in cmd:
                cmd = cmd.split("(", 1)[0].strip()

            if not do_apply:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": f"sites fix DRYRUN (would run: {cmd})",
                    "base_url": base_url,
                    "sites": sites,
                    "hints": hints,
                    "next_cmd": cmd,
                    "results": results,
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            # --- 3) APPLY first fix ---
            fix_resp = {"ok": False, "exit_code": 1, "stdout": "", "stderr": "no fix executed"}
            fix_params = None

            # parse tokens from cmd
            kv2 = {}
            for tok in cmd.split()[2:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv2[k.strip().lower()] = v.strip()
            name2 = (kv2.get("name") or "").strip()
            confirm2 = (kv2.get("confirm") or "").strip()

            if cmd.lower().startswith("site: up") and name2 and confirm2:
                fix_params = {"action": "compose_up", "mode": "apply", "args": {"project_dir": f"/opt/sites/{name2}"}, "confirm": confirm2}
                fix_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=fix_params)
                fix_resp = normalize_exec_response("ssh: run", fix_resp)

            elif cmd.lower().startswith("site: unblock") and name2 and confirm2:
                # auto-detect port via docker_status
                detected = 0
                try:
                    out = (ds_resp.get("stdout") or "").splitlines()
                    target = f"{name2}-web-1"
                    for line in out:
                        if target in line:
                            mm = _re.search(r"(127\.0\.0\.1:)?(\d+)\-\>", line)
                            if mm:
                                detected = int(mm.group(2))
                                break
                except Exception:
                    detected = 0

                if detected <= 0:
                    # fallback: compose_ps
                    try:
                        cps_params = {"action": "compose_ps", "mode": "check", "args": {"project_dir": f"/opt/sites/{name2}"}}
                        cps_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=cps_params)
                        cps_resp = normalize_exec_response("ssh: run", cps_resp)
                        out2 = (cps_resp.get("stdout") or "").splitlines()
                        for line in out2:
                            mm = _re.search(r"(127\.0\.0\.1:)?(\d+)\-\>", line)
                            if mm:
                                detected = int(mm.group(2))
                                break
                    except Exception:
                        detected = 0

                if detected > 0:
                    fix_params = {"action": "caddy_site_route", "mode": "apply", "args": {"name": name2, "state": "present", "port": detected}, "confirm": confirm2}
                    fix_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=fix_params)
                    fix_resp = normalize_exec_response("ssh: run", fix_resp)
                else:
                    fix_resp = {"ok": False, "exit_code": 1, "stdout": "", "stderr": "port auto-detect failed for unblock"}

            results.append({"task": "ssh: run", "params": fix_params or {"cmd": cmd}, "response": fix_resp})

            # --- 4) re-check after fix (HEAD again) ---
            # (simple: reuse existing sites[] but only re-probe the fixed one for correctness)
            # For now: just return fix result + original status; user can re-run sites: status.
            ok2 = bool(fix_resp.get("ok", False))
            report = {
                "ok": ok2,
                "exit_code": int(fix_resp.get("exit_code", 0) or 0),
                "summary": f"sites fix {'OK' if ok2 else 'FAIL'} (ran: {cmd})",
                "base_url": base_url,
                "sites": sites,
                "hints": hints,
                "results": results,
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok2 else 1)

        except SystemExit:
            raise
        except Exception as _ex:
            report = {"ok": False, "exit_code": 1, "summary": f"sites fix FAIL (exception: {_ex})", "results": []}
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

    if user_task.lower().startswith("monitoring: sites status") or user_task.lower().startswith("monitoring: sites_status") or user_task.lower().startswith("sites: status") or user_task.lower().startswith("sites:status"):
        import os as _os, json as _json, re as _re, subprocess as _sub

        base_url = _os.getenv("N8N_BASE_URL", "https://ii-bot-nout.ru").rstrip("/")

        def _curl_code2(url: str, timeout_s: int = 3) -> int:
            try:
                p = _sub.run(
                    ["curl", "-ksS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout_s), url],
                    capture_output=True, text=True
                )
                if p.returncode != 0:
                    return 0
                t = (p.stdout or "").strip()
                return int(t) if t.isdigit() else 0
            except Exception:
                return 0

        # 1) discover sites from docker_status (containers like: <name>-web-1)
        r_ds = _call_ssh_action("docker_status", {})
        ds_text = str(r_ds.get("stdout") or r_ds.get("text") or "")

        sites = []
        for line in ds_text.splitlines():
            m = _re.search(r"^([A-Za-z0-9_-]+)-web-1\b", line.strip())
            if m:
                sites.append(m.group(1))        # 1b) also discover sites from /opt/sites that actually have docker-compose.yml
        try:
            p_find = _sub.run(
                ["ssh", "-o", "BatchMode=yes", "ii-bot-nout", "bash", "-lc", "find /opt/sites -maxdepth 2 -mindepth 2 -name docker-compose.yml -printf '%h\n' | xargs -n1 basename"],
                capture_output=True, text=True
            )
            if p_find.returncode == 0:
                for nm in (p_find.stdout or "").splitlines():
                    nm = (nm or "").strip()
                    if nm and _re.match(r"^[A-Za-z0-9_-]+$", nm):
                        sites.append(nm)
        except Exception:
            pass

        sites = sorted(set(sites))

        results = []
        up_n = 0
        blocked_n = 0
        down_n = 0
        other_n = 0

        ok = True

        for name in sites:
            code = _curl_code2(f"{base_url}/{name}/", timeout_s=3)
            if code == 0:
                # retry once to reduce false negatives (transient curl errors)
                code = _curl_code2(f"{base_url}/{name}/", timeout_s=5)

            # optional: route state from caddy_site_route(check)
            route_state = "unknown"
            try:
                rr = _call_ssh_action("caddy_site_route", {"name": name})
                out = str(rr.get("stdout") or rr.get("text") or "").strip()
                obj = _parse_json_maybe(out) if out else None
                if isinstance(obj, dict):
                    route_state = (obj.get("state") or obj.get("route_state") or obj.get("status") or "unknown")
            except Exception:
                route_state = "unknown"

            if code == 200:
                state = "up"
                up_n += 1
            elif code == 404:
                state = "blocked_or_missing"
                blocked_n += 1
            elif code in (502, 0):
                state = "down"
                down_n += 1
                ok = False
            else:
                state = "other"
                other_n += 1
                ok = False

            results.append({
                "name": name,
                "http": int(code),
                "route": route_state,
                "state": state,
            })

        # normalize route/state from HTTP
        for it in results:
            try:
                h = int(it.get("http") or 0)
            except Exception:
                h = 0

            if h in (200, 502):
                it["route"] = "present"
            elif h == 404:
                it["route"] = "blocked_or_missing"
            else:
                it["route"] = "unknown"

            if h == 200:
                it["state"] = "up"
            elif h == 502:
                it["state"] = "down"
            elif h == 404:
                it["state"] = "blocked_or_missing"
            else:
                it["state"] = it.get("state") or "other"

        # auto-reactions hints
        hints = []
        for it in results:
            n = str(it.get("name") or "").strip()
            st = str(it.get("state") or "").strip()
            if not n:
                continue
            if st == "down":
                up_token = "UP_" + n.upper().replace("-", "_")
                hints.append(f"hint: recover → site: up name={n} confirm={up_token}  (requires ALLOW_DANGEROUS=1)")
            if st == "blocked_or_missing":
                unb_token = "UNBLOCK_" + n.upper().replace("-", "_")
                hints.append(f"hint: publish → site: unblock name={n} confirm={unb_token}  (requires ALLOW_DANGEROUS=1)")

        status = "OK" if ok else "FAIL"
        summary = f"sites status {status} (total={len(sites)} up={up_n} blocked={blocked_n} down={down_n} other={other_n})"

        print(f"[plan] summary: {summary}")
        print(_json.dumps({
            "ok": ok,
            "summary": summary,
            "base_url": base_url,
            "sites": results,
            "hints": hints,
        }, ensure_ascii=False))

        raise SystemExit(0 if ok else 1)
    # --- /sites group status shortcut


    # --- Site shortcuts

    if user_task.lower().startswith("site: create"):
        # examples:
        #   site: create name=demo4 domain=demo4.local port=18083 confirm=CREATE_DEMO4
        # creates: site_init(apply) + compose_up(apply) + caddy_site_route(apply state=present)
        import re as _re

        def _kv(text: str) -> dict:
            out = {}
            for m in _re.finditer(r'(\w+)\s*=\s*("[^"]*"|\S+)', text):
                k = m.group(1).strip()
                v = m.group(2).strip()
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                out[k] = v
            return out

        kv = _kv(user_task)
        name = (kv.get("name", "") or "").strip()
        domain = (kv.get("domain", "") or "").strip()
        base_dir = (kv.get("base_dir", "/opt/sites") or "/opt/sites").strip()
        port_raw = (kv.get("port", "18080") or "18080").strip()
        confirm = (kv.get("confirm", "") or "").strip()

        try:
            port = int(port_raw)
        except Exception:
            port = 18080

        if not name:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": "site create FAIL (name required)",
                "results": [],
            }
            print(f"[plan] summary: {report['summary']}")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

        if not confirm:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": "site create FAIL (confirm required)",
                "results": [],
            }
            print(f"[plan] summary: {report['summary']}")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

        up_token = "UP_" + name.upper().replace("-", "_")
        unblock_token = "UNBLOCK_" + name.upper().replace("-", "_")

        # 1) site_init (apply)
        args_init = {"name": name, "base_dir": base_dir, "port": port}
        if domain:
            args_init["domain"] = domain

        r1 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params={
            "action": "site_init",
            "mode": "apply",
            "args": args_init,
        })
        r1 = normalize_exec_response("ssh: run", r1)

        # 2) compose_up (apply)
        project_dir = f"{base_dir}/{name}"
        r2 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params={
            "action": "compose_up",
            "mode": "apply",
            "args": {"project_dir": project_dir},
            "confirm": up_token,
        })
        r2 = normalize_exec_response("ssh: run", r2)

        # 3) route present (apply)
        r3 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params={
            "action": "caddy_site_route",
            "mode": "apply",
            "args": {"name": name, "port": port, "state": "present"},
            "confirm": unblock_token,
        })
        r3 = normalize_exec_response("ssh: run", r3)

        ok = bool(r1.get("ok")) and bool(r2.get("ok")) and bool(r3.get("ok"))
        summary = f"site create {'OK' if ok else 'FAIL'} ({name})"

        report = {
            "ok": ok,
            "exit_code": 0 if ok else 1,
            "summary": summary,
            "results": [
                {"task": "ssh: run", "params": {"action": "site_init", "mode": "apply", "args": args_init}, "response": r1},
                {"task": "ssh: run", "params": {"action": "compose_up", "mode": "apply", "args": {"project_dir": project_dir}, "confirm": up_token}, "response": r2},
                {"task": "ssh: run", "params": {"action": "caddy_site_route", "mode": "apply", "args": {"name": name, "port": port, "state": "present"}, "confirm": unblock_token}, "response": r3},
            ],
        }

        print(f"[plan] summary: {summary}")
        print("\n[exec] running actions: 3")
        print("\n[exec #1] ssh: run (site_init apply)")
        print("\n[exec #2] ssh: run (compose_up apply)")
        print("\n[exec #3] ssh: run (caddy_site_route apply)")
        print("\n[report] done.")
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if ok else 1)


    if user_task.lower().startswith("site: init"):
        # examples:
        #   site: init name=demo-site domain=demo.local port=18080
        # defaults: base_dir=/opt/sites, port=18080
        import re as _re

        def _kv(text: str) -> dict:
            out = {}
            for m in _re.finditer(r'(\w+)\s*=\s*("[^"]*"|\S+)', text):
                k = m.group(1).strip()
                v = m.group(2).strip()
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                out[k] = v
            return out

        kv = _kv(user_task)
        name = kv.get("name", "").strip()
        domain = kv.get("domain", "").strip()
        base_dir = kv.get("base_dir", "/opt/sites").strip()
        port_raw = kv.get("port", "18080").strip()

        try:
            port = int(port_raw)
        except Exception:
            port = 18080

        if not name:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": "site init FAIL (name required)",
                "results": [{
                    "task": "ssh: run",
                    "params": {"action": "site_init", "mode": "check", "args": {}},
                    "response": {
                        "ok": False,
                        "exit_code": 1,
                        "action": "site_init",
                        "mode": "check",
                        "stdout": "",
                        "stderr": "args.name required (use: site: init name=... [domain=..] [port=..])",
                        "artifacts": [],
                        "meta": {"changed": False, "warnings": []},
                    }
                }],
            }
            print(f"[plan] summary: {report['summary']}")
            print("\n[exec] running actions: 1")
            print("\n[exec #1] ssh: run (site_init)")
            print("\n[report] done.")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

        args = {"name": name, "base_dir": base_dir, "port": port}
        if domain:
            args["domain"] = domain

        resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params={
            "action": "site_init",
            "mode": "apply",
            "args": args,
        })
        resp = normalize_exec_response("ssh: run", resp)

        ok = bool(resp.get("ok"))
        report = {
            "ok": ok,
            "exit_code": int(resp.get("exit_code", 0) or 0),
            "summary": f"site init {'OK' if ok else 'FAIL'} ({name})",
            "results": [{"task": "ssh: run", "params": {"action": "site_init", "mode": "apply", "args": args}, "response": resp}],
        }

        print(f"[plan] summary: {report['summary']}")
        print("\n[exec] running actions: 1")
        print("\n[exec #1] ssh: run (site_init apply)")
        print("\n[report] done.")
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if ok else 1)
    # --- /Site shortcuts

# --- /Monitoring shortcuts ---

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    
    
    if user_task.lower().startswith("site: list"):
        # examples:
        #   site: list
        # Lists sites based on docker containers "<name>-web-1" and probes https://ii-bot-nout.ru/<name>/
        import re as _re
        from urllib.request import Request as _Req, urlopen as _urlopen
        from urllib.error import HTTPError as _HTTPError

        # 1) docker_status (safe) -> find "<name>-web-1"
        resp0 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params={
            "action": "docker_status",
            "mode": "check",
            "args": {},
        })
        resp0 = normalize_exec_response("ssh: run", resp0)

        names = set()
        if resp0.get("ok"):
            for line in str(resp0.get("stdout", "")).splitlines():
                m = _re.match(r"^([A-Za-z0-9_-]+)-web-1\s", line.strip())
                if m:
                    names.add(m.group(1))

        results = [
            {"task": "ssh: run", "params": {"action": "docker_status", "mode": "check", "args": {}}, "response": resp0}
        ]

        base = os.environ.get("SITE_BASE_URL") or agent_exec_url.split("/webhook/")[0].rstrip("/")
        sites = []

        # 2) HEAD probe each route
        for name in sorted(names):
            url = f"{base}/{name}/"
            code = 0
            err = ""
            try:
                req = _Req(url, method="HEAD")
                with _urlopen(req, timeout=10) as r:
                    code = int(getattr(r, "status", 0) or 0)
            except _HTTPError as e:
                code = int(getattr(e, "code", 0) or 0)
                err = str(e)
            except Exception as e:
                err = str(e)

            sites.append({"name": name, "url": url, "http_code": code, "error": err})
            results.append({"task": "http: head", "params": {"url": url}, "response": {"ok": (code == 200), "url": url, "http_code": code, "error": err}})

        summary = f"site list OK (count={len(sites)})"
        report = {"ok": True, "exit_code": 0, "summary": summary, "sites": sites, "results": results}
        print(f"[plan] summary: {summary}")
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0)


    if user_task.lower().startswith("site: status"):
        # Examples:
        #   site: status name=demo-site
        try:
            raw = user_task.strip()
            parts = raw.split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site status FAIL",
                    "results": [{
                        "task": "ssh: run",
                        "params": {"action": "compose_ps", "mode": "check", "args": {}},
                        "response": {
                            "ok": False,
                            "exit_code": 1,
                            "action": "compose_ps",
                            "mode": "check",
                            "stdout": "",
                            "stderr": "args.name required (use: site: status name=...)",
                            "meta": {"changed": False, "warnings": []},
                            "artifacts": [],
                        }
                    }]
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(0)

            project_dir = f"/opt/sites/{name}"
            params = {"action": "compose_ps", "mode": "check", "args": {"project_dir": project_dir}}
            resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=params)
            resp = normalize_exec_response("ssh: run", resp)

            # Compose status (containers)
            compose_ok = bool(resp.get("ok"))
            stdout = (resp.get("stdout") or "")
            up = compose_ok and (" Up " in stdout)

            # Route status (Caddyfile): present|absent|block|unknown
            route_state = "unknown"
            route_resp = {}
            try:
                route_params = {"action": "caddy_site_route", "mode": "check", "args": {"name": name}}
                r_route = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=route_params)
                route_resp = normalize_exec_response("ssh: run", r_route)
                meta = route_resp.get("meta") or {}
                if isinstance(meta, dict):
                    st = str(meta.get("state") or meta.get("route_state") or "").strip().lower()
                    if st in ("present", "absent", "block"):
                        route_state = st

                if route_state == "unknown":
                    txt = (str(route_resp.get("stdout") or "") + "\n" + str(route_resp.get("text") or "")).lower()
                    if "state=absent" in txt or "\nabsent" in txt:
                        route_state = "absent"
                    elif "state=block" in txt or "\nblock" in txt or "blocked" in txt:
                        route_state = "block"
                    elif "state=present" in txt or "\npresent" in txt or "handle_path" in txt:
                        route_state = "present"
            except Exception:
                route_resp = {
                    "ok": False,
                    "exit_code": 1,
                    "action": "caddy_site_route",
                    "mode": "check",
                    "stdout": "",
                    "stderr": "",
                    "text": "route check failed",
                    "meta": {"changed": False, "warnings": []},
                    "artifacts": [],
                }

            # HTTP status by public route
            base_url = (os.environ.get("N8N_BASE_URL") or "https://ii-bot-nout.ru").rstrip("/")
            http_url = f"{base_url}/{name}/"
            http_code = None
            http_err = ""
            try:
                import urllib.request
                import urllib.error
                req = urllib.request.Request(http_url, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as r:
                    http_code = int(getattr(r, "status", 0) or 0)
            except urllib.error.HTTPError as e:
                http_code = int(getattr(e, "code", 0) or 0)
                http_err = str(e)
            except Exception as e:
                http_code = None
                http_err = str(e)

            # Normalize route_state by observed HTTP
            # - 200 => route is present
            # - 404 => could be absent or block; if route check says present -> treat as block
            # - 502 => route is present but backend is down
            if http_code == 200:
                route_state = "present"
            elif http_code == 404 and route_state == "present":
                route_state = "block"
            elif http_code == 502 and route_state == "unknown":
                route_state = "present"

            # Overall OK/FAIL logic:
            # OK:
            # - http=200 AND containers up AND route=present
            # - http=404 AND route in (absent|block)  (blocked or not routed)
            # FAIL:
            # - http=502 (route exists but backend is down)
            # - other / errors
            ok = (http_code == 200 and up and route_state == "present") or (http_code == 404 and route_state in ("absent", "block"))

            summary_http = http_code if http_code is not None else "ERR"
            summary = f"site status {'OK' if ok else 'FAIL'} (up={up} route={route_state} http={summary_http})"
            if http_code == 502:
                summary += f" | hint: site: up name={name} confirm=UP_{name.upper().replace('-', '_')}"
            if http_code == 404 and up and route_state in ("absent", "block"):
                summary += f" | hint: site: unblock name={name} confirm=ROUTE_{name.upper().replace('-', '_')}  (port auto-detect)"

            http_resp = {
                "ok": (http_code in (200, 404)),
                "url": http_url,
                "http_code": http_code,
                "error": http_err,
            }

            report = {
                "ok": ok,
                "exit_code": 0 if ok else 1,
                "summary": summary,
                "results": [
                    {"task": "ssh: run", "params": params, "response": resp},
                    {"task": "ssh: run", "params": {"action": "caddy_site_route", "mode": "check", "args": {"name": name}}, "response": route_resp},
                    {"task": "http: head", "params": {"url": http_url}, "response": http_resp},
                ],
            }
            print(f"[plan] summary: {summary}")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": "site status FAIL",
                "results": [{
                    "task": "ssh: run",
                    "params": {"action": "compose_ps", "mode": "check", "args": {}},
                    "response": {
                        "ok": False,
                        "exit_code": 1,
                        "action": "compose_ps",
                        "mode": "check",
                        "stdout": "",
                        "stderr": f"site status shortcut error: {_ex}",
                        "meta": {"changed": False, "warnings": []},
                        "artifacts": [],
                    }
                }]
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0)


    if user_task.lower().startswith("site: up"):
        # Examples:
        #   site: up name=demo-site
        #   site: up name=demo-site confirm=UP_DEMO_SITE   (requires ALLOW_DANGEROUS=1)
        try:
            parts = user_task.strip().split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k,v = t.split("=",1)
                    kv[k.strip()] = v.strip()
            name = str(kv.get("name","")).strip()
            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site up FAIL (missing name)",
                    "results": [{"task": "ssh: run", "params": {}, "response": {
                        "ok": False,
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "args.name required (use: site: up name=... [confirm=...])",
                        "text": "args.name required (use: site: up name=... [confirm=...])",
                    }}],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            base_dir = str(kv.get("base_dir","/opt/sites")).strip() or "/opt/sites"
            project_dir = f"{base_dir.rstrip("/")}/{name}"
            confirm = str(kv.get("confirm","")).strip()
            _mode = "apply" if confirm else "check"

            params = {
                "action": "compose_up",
                "mode": _mode,
                "args": {"project_dir": project_dir},
            }
            if confirm:
                params["confirm"] = confirm

            resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=params)
            resp = normalize_exec_response("ssh: run", resp)
            ok = bool(resp.get("ok"))
            report = {
                "ok": ok,
                "exit_code": int(resp.get("exit_code", 0) or 0),
                "summary": f"site up {'OK' if ok else 'FAIL'} ({name})",
                "results": [{"task": "ssh: run", "params": params, "response": resp}],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": f"site up FAIL (exception: {_ex})",
                "results": [],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)


    
    # alias: site: fix -> site: deploy
    if user_task.lower().startswith("site: fix"):
        user_task = user_task.replace("site: fix", "site: deploy", 1)

    if user_task.lower().startswith("site: deploy"):
        # Examples:
        #   site: deploy name=demo2
        #   site: deploy name=demo2 confirm=DEPLOY_DEMO2   (apply)
        try:
            parts = user_task.strip().split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            if not name:
                report = {"ok": False, "exit_code": 1, "summary": "site deploy FAIL (missing name)", "results": []}
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            confirm = (kv.get("confirm") or "").strip()
            mode = "apply" if confirm else "check"
            project_dir = f"/opt/sites/{name}"

            results = []

            # 1) pull
            pull_params = {"action": "compose_pull", "mode": mode, "args": {"project_dir": project_dir}}
            if confirm:
                pull_params["confirm"] = confirm
            pull_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=pull_params)
            pull_resp = normalize_exec_response("ssh: run", pull_resp)
            results.append({"task": "ssh: run", "params": pull_params, "response": pull_resp})

            # 2) up
            up_params = {"action": "compose_up", "mode": mode, "args": {"project_dir": project_dir}}
            if confirm:
                up_params["confirm"] = confirm
            up_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=up_params)
            up_resp = normalize_exec_response("ssh: run", up_resp)
            results.append({"task": "ssh: run", "params": up_params, "response": up_resp})

            # 3) status (compose_ps + HTTP HEAD)
            ps_params = {"action": "compose_ps", "mode": "check", "args": {"project_dir": project_dir}}
            ps_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=ps_params)
            ps_resp = normalize_exec_response("ssh: run", ps_resp)

            stdout = (ps_resp.get("stdout") or "")
            up = bool(ps_resp.get("ok")) and (" Up " in stdout)

            base_url = (os.environ.get("N8N_BASE_URL") or "https://ii-bot-nout.ru").rstrip("/")
            http_url = f"{base_url}/{name}/"
            http_code = None
            http_err = ""
            try:
                import urllib.request
                import urllib.error
                req = urllib.request.Request(http_url, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as r:
                    http_code = int(getattr(r, "status", 0) or 0)
            except urllib.error.HTTPError as e:
                http_code = int(getattr(e, "code", 0) or 0)
                http_err = str(e)
            except Exception as e:
                http_code = None
                http_err = str(e)

            ok = (http_code == 404) or (http_code == 200 and up)
            summary_http = http_code if http_code is not None else "ERR"
            summary = f"site deploy {'OK' if ok else 'FAIL'} (name={name} up={up} http={summary_http})"
            if http_code == 502:
                summary += f" | hint: site: up name={name} confirm=UP_{name.upper().replace('-', '_')}"

            results.append({"task": "ssh: run", "params": ps_params, "response": ps_resp})
            results.append({"task": "http: head", "params": {"url": http_url}, "response": {"ok": (http_code in (200,404)), "url": http_url, "http_code": http_code, "error": http_err}})

            report = {"ok": ok, "exit_code": 0 if ok else 1, "summary": summary, "results": results}
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {"ok": False, "exit_code": 1, "summary": f"site deploy FAIL (exception: {_ex})", "results": []}
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)


    if user_task.lower().startswith("site: logs"):
        # Example:
        #   site: logs name=demo-site last=80
        try:
            raw = user_task.strip()
            parts = raw.split()
            kv = {}
            for tok in parts[2:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            last = int(kv.get("last") or "80")

            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site logs FAIL (missing name)",
                    "results": [],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            params = {
                "action": "compose_logs",
                "mode": "check",
                "args": {
                    "project_dir": f"/opt/sites/{name}",
                    "tail": last,
                },
            }

            resp = call_agent_exec(agent_exec_url, "ssh: run", params=params, chat_id=chat_id)
            ok = bool(resp.get("ok", False))

            report = {
                "ok": ok,
                "exit_code": 0 if ok else 1,
                "summary": f"site logs {'OK' if ok else 'FAIL'} ({name})",
                "results": [{"task": "ssh: run", "params": params, "response": resp}],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": f"site logs FAIL (exception: {_ex})",
                "results": [],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)




    if user_task.lower().startswith("site: delete"):
        # Examples:
        #   site: delete name=demo5 confirm=DELETE_DEMO5
        # Does: caddy_site_route(state=absent) + compose_down(apply)
        try:
            parts = user_task.strip().split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            confirm = (kv.get("confirm") or "").strip()

            if not name:
                report = {"ok": False, "exit_code": 1, "summary": "site delete FAIL (missing name)", "results": []}
                print(f"[plan] summary: {report['summary']}")
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            if not confirm:
                report = {"ok": False, "exit_code": 1, "summary": "site delete FAIL (confirm required)", "results": []}
                print(f"[plan] summary: {report['summary']}")
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            # 1) remove route
            p1 = {
                "action": "caddy_site_route",
                "mode": "apply",
                "args": {"name": name, "state": "absent"},
                "confirm": confirm,
            }
            r1 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=p1)
            r1 = normalize_exec_response("ssh: run", r1)

            # 2) down containers
            p2 = {
                "action": "compose_down",
                "mode": "apply",
                "args": {"project_dir": f"/opt/sites/{name}"},
                "confirm": confirm,
            }
            r2 = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=p2)
            r2 = normalize_exec_response("ssh: run", r2)

            ok = bool(r1.get("ok")) and bool(r2.get("ok"))
            summary = f"site delete {'OK' if ok else 'FAIL'} ({name})"

            report = {
                "ok": ok,
                "exit_code": 0 if ok else 1,
                "summary": summary,
                "results": [
                    {"task": "ssh: run", "params": p1, "response": r1},
                    {"task": "ssh: run", "params": p2, "response": r2},
                ],
            }
            print(f"[plan] summary: {summary}")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)

        except SystemExit:
            raise
        except Exception as _ex:
            report = {"ok": False, "exit_code": 1, "summary": f"site delete FAIL (exception: {_ex})", "results": []}
            print(f"[plan] summary: {report['summary']}")
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)


    if user_task.lower().startswith("site: down"):
        # Examples:
        #   site: down name=demo-site
        #   site: down name=demo-site confirm=DOWN_DEMO_SITE   (requires ALLOW_DANGEROUS=1)
        try:
            parts = user_task.strip().split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site down FAIL (missing name)",
                    "results": [],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            confirm = (kv.get("confirm") or "").strip()
            mode = "apply" if confirm else "check"

            params = {
                "action": "compose_down",
                "mode": mode,
                "args": {"project_dir": f"/opt/sites/{name}"},
            }
            if confirm:
                params["confirm"] = confirm

            resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=params)
            resp = normalize_exec_response("ssh: run", resp)
            ok = bool(resp.get("ok", False))

            report = {
                "ok": ok,
                "exit_code": int(resp.get("exit_code", 0) or 0),
                "summary": f"site down {'OK' if ok else 'FAIL'} ({name})",
                "results": [{"task": "ssh: run", "params": params, "response": resp}],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": f"site down FAIL (exception: {_ex})",
                "results": [],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)


    if user_task.lower().startswith("site: restart"):
        # Examples:
        #   site: restart name=demo-site
        #   site: restart name=demo-site confirm=RESTART_DEMO_SITE   (requires ALLOW_DANGEROUS=1)
        try:
            parts = user_task.strip().split()
            kv = {}
            for t in parts[2:]:
                if "=" in t:
                    k, v = t.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site restart FAIL (missing name)",
                    "results": [],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            confirm = (kv.get("confirm") or "").strip()
            mode = "apply" if confirm else "check"

            params = {
                "action": "compose_restart",
                "mode": mode,
                "args": {"project_dir": f"/opt/sites/{name}"},
            }
            if confirm:
                params["confirm"] = confirm

            resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=params)
            resp = normalize_exec_response("ssh: run", resp)
            ok = bool(resp.get("ok", False))

            report = {
                "ok": ok,
                "exit_code": int(resp.get("exit_code", 0) or 0),
                "summary": f"site restart {'OK' if ok else 'FAIL'} ({name})",
                "results": [{"task": "ssh: run", "params": params, "response": resp}],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": f"site restart FAIL (exception: {_ex})",
                "results": [],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)


    # aliases: site: block / site: unblock
    if user_task.lower().startswith("site: block"):
        user_task = user_task.replace("site: block", "site: route", 1) + " state=block"
    if user_task.lower().startswith("site: unblock"):
        user_task = user_task.replace("site: unblock", "site: route", 1) + " state=present"
    if user_task.lower().startswith("site: route"):
        # Examples:
        #   site: route name=demo-site port=18080
        #   site: route name=demo-site port=18080 confirm=ROUTE_DEMO_SITE   (requires ALLOW_DANGEROUS=1)
        #   site: route name=demo-site state=absent confirm=UNROUTE_DEMO_SITE
        try:
            raw = user_task.strip()
            parts = raw.split()
            kv = {}
            for tok in parts[2:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            name = (kv.get("name") or "").strip()
            port_raw = (kv.get("port") or "").strip()
            state = (kv.get("state") or "present").strip().lower()
            confirm = (kv.get("confirm") or "").strip()

            if not name:
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site route FAIL (missing name)",
                    "results": [],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            if state not in ("present", "absent", "block"):
                report = {
                    "ok": False,
                    "exit_code": 1,
                    "summary": "site route FAIL (state must be present|absent|block)",
                    "results": [],
                }
                print(json.dumps(report, ensure_ascii=False))
                raise SystemExit(1)

            port = 0
            if state == "present":
                # port may be omitted for 'site: unblock' → try autodetect
                try:
                    port = int(port_raw)
                except Exception:
                    port = 0

                if port <= 0:
                    detected = 0

                    # 1) Try docker_status (best effort)
                    try:
                        ds_params = {"action": "docker_status", "mode": "check", "args": {}}
                        ds_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=ds_params)
                        ds_resp = normalize_exec_response("ssh: run", ds_resp)
                        out = (ds_resp.get("stdout") or "").splitlines()
                        # Expect container like: <name>-web-1 ... 127.0.0.1:18080->80/tcp
                        target = f"{name}-web-1"
                        for line in out:
                            if target in line:
                                mm = __import__("re").search(r"(127\.0\.0\.1:)?(\d+)\-\>", line)
                                if mm:
                                    detected = int(mm.group(2))
                                    break
                    except Exception:
                        detected = 0

                    # 2) Try compose_ps for /opt/sites/<name>
                    if detected <= 0:
                        try:
                            cps_params = {"action": "compose_ps", "mode": "check", "args": {"project_dir": f"/opt/sites/{name}"}}
                            cps_resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=cps_params)
                            cps_resp = normalize_exec_response("ssh: run", cps_resp)
                            out = (cps_resp.get("stdout") or "").splitlines()
                            for line in out:
                                mm = __import__("re").search(r"(127\.0\.0\.1:)?(\d+)\-\>", line)
                                if mm:
                                    detected = int(mm.group(2))
                                    break
                        except Exception:
                            detected = 0

                    port = detected

                if port <= 0:
                    report = {
                        "ok": False,
                        "exit_code": 1,
                        "summary": "site route FAIL (port required for state=present; auto-detect failed)",
                        "results": [],
                    }
                    print(json.dumps(report, ensure_ascii=False))
                    raise SystemExit(1)
            mode = "apply" if confirm else "check"

            params = {
                "action": "caddy_site_route",
                "mode": mode,
                "args": {
                    "name": name,
                    "state": state,
                },
            }
            if state == "present":
                params["args"]["port"] = port
            if confirm:
                params["confirm"] = confirm

            resp = call_agent_exec(agent_exec_url, "ssh: run", chat_id, params=params)
            resp = normalize_exec_response("ssh: run", resp)

            ok = bool(resp.get("ok", False))
            report = {
                "ok": ok,
                "exit_code": int(resp.get("exit_code", 0) or 0),
                "summary": f"site route {'OK' if ok else 'FAIL'} ({name}, state={state})",
                "results": [{"task": "ssh: run", "params": params, "response": resp}],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(0 if ok else 1)

        except SystemExit:
            raise
        except Exception as _ex:
            report = {
                "ok": False,
                "exit_code": 1,
                "summary": f"site route FAIL (exception: {_ex})",
                "results": [],
            }
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit(1)

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

    plan = plan_with_claude(client, model, user_task, handv2_actions=sorted((handv2_index or {}).keys()))

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
                    params={"action": hv2_action, "mode": mode, "args": args, **({"confirm": (params or {}).get("confirm")} if (params or {}).get("confirm") else {})},
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

        # Gate dangerous tasks
        if task in DANGEROUS_TASKS and not allow_dangerous:
            # For Hand v2 (ssh: run), allow apply when confirm token is present
            if task == "ssh: run":
                _mode = str((params or {}).get("mode") or "check").strip().lower()
                _confirm = str((params or {}).get("confirm") or "").strip()
                if _mode == "apply" and _confirm:
                    pass
                else:
                    print(f"[exec #{i}] SKIP (dangerous). Set ALLOW_DANGEROUS=1 or provide confirm=TOKEN to allow apply.")
                    results.append({"task": task, "skipped": True, "why": "dangerous"})
                    issue_found = True
                    continue
            else:
                print(f"[exec #{i}] SKIP (dangerous). Set ALLOW_DANGEROUS=1 to allow.")
                results.append({"task": task, "skipped": True, "why": "dangerous"})
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
