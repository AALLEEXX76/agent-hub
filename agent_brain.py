#!/usr/bin/env python3
import os
import json
from datetime import datetime, timezone
from pathlib import Path

import re
import sys
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from anthropic import Anthropic


ALLOWED_TASKS = {
    "ssh: docker_status",
    "ssh: healthz",
    "ssh: backup_now",
    "ssh: caddy_logs",
    "ssh: restart_n8n",
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
        normalized.append({"task": task, "reason": str(reason)})
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
def call_agent_exec(agent_exec_url: str, task: str, chat_id: Optional[int], timeout_s: int = 30) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"task": task}
    if chat_id is not None:
        payload["chatId"] = chat_id

    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(agent_exec_url, json=payload)
        r.raise_for_status()
        return r.json()


def plan_with_claude(client: Anthropic, model: str, user_task: str) -> Dict[str, Any]:
    system = (
        "Ты — планировщик действий для DevOps-агента. "
        "Твоя задача: превратить запрос пользователя в минимальный безопасный план действий.\n\n"
        "СТРОГОЕ ТРЕБОВАНИЕ: верни ТОЛЬКО валидный JSON-объект, без markdown и без пояснений вокруг.\n\n"
        "Разрешённые действия (task):\n"
        "- ssh: docker_status\n"
        "- ssh: healthz\n"
        "- ssh: backup_now\n"
        "- ssh: caddy_logs\n"
        "- ssh: restart_n8n\n\n"
        "Формат ответа JSON:\n"
        "{\n"
        '  "summary": "коротко что делаем",\n'
        '  "actions": [ {"task":"ssh: healthz","reason":"почему"} ],\n'
        '  "finish": {"status":"done|need_more_info","message":"короткий итог","questions":[...]}\n'
        "}\n\n"
        "Правила:\n"
        "- Делай МИНИМУМ действий, которые реально нужны.\n"
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

def main() -> int:
    load_env()

    user_task = " ".join(sys.argv[1:]).strip()
    if not user_task:
        eprint('Usage: ./agent_brain.py "твоя задача текстом"')
        return 2

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

    if finish.get("status") == "need_more_info":
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
        task = a["task"]
        reason = a.get("reason", "")
        print(f"\n[exec #{i}] {task}")
        if reason:
            print(f"[exec #{i}] reason: {reason}")

        if task in DANGEROUS_TASKS and not allow_dangerous:
            print(f"[exec #{i}] SKIP (dangerous). Set ALLOW_DANGEROUS=1 to allow.")
            results.append({"task": task, "skipped": True, "why": "dangerous"})
            issue_found = True
            continue

        try:
            out_raw = call_agent_exec(agent_exec_url, task, chat_id)
            out_norm = normalize_exec_response(task, out_raw)
            out = sanitize_response(task, out_norm)
            results.append({"task": task, "response": out})
            print(f"[exec #{i}] ok={out.get('ok')} action={out.get('action')}")
            stdout = (out.get("stdout") or "")
            stderr = (out.get("stderr") or "")
            if stdout:
                print(f"[exec #{i}] stdout:", stdout[:600])
            if stderr:
                print(f"[exec #{i}] stderr:", stderr[:600])

            if not out.get("ok", False):
                issue_found = True

        except Exception as ex:
            issue_found = True
            results.append({"task": task, "error": str(ex)})
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
