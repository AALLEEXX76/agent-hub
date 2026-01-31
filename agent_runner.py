#!/usr/bin/env python3
import argparse
import os
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from json import JSONDecoder


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
BRAIN = Path(__file__).resolve().parent / "agent_brain.py"

ENV_FILE = Path(__file__).resolve().parent / ".agent_env"

def _parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        txt = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out

    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        # strip surrounding quotes
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        out[k] = v
    return out

_CHILD_ENV: Optional[Dict[str, str]] = None

def _get_child_env() -> Dict[str, str]:
    global _CHILD_ENV
    if _CHILD_ENV is None:
        env = os.environ.copy()
        # don't override already-set env vars; allow CLI overrides
        for k, v in _parse_env_file(ENV_FILE).items():
            env.setdefault(k, v)
        _CHILD_ENV = env
    return _CHILD_ENV


def run_brain(task_text: str) -> Dict[str, Any]:
    """
    Запускает agent_brain.py как подпроцесс, возвращает:
    - ok: bool (код выхода == 0)
    - stdout/stderr: строки
    - exit_code: int
    """
    p = subprocess.run(
        [sys.executable, str(BRAIN), task_text],
        capture_output=True,
        text=True,
        env=_get_child_env(),
    )
    return {
        "ok": p.returncode == 0,
        "exit_code": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }


def extract_brain_report(brain_stdout: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract the final JSON report printed by agent_brain.py.

    Brain stdout may contain:
      - lots of logs before JSON
      - pretty (multiline) JSON at the end
      - extra logs after JSON (e.g. post-apply healthcheck)

    Strategy:
      - find JSON object that starts at beginning of a line ("^{")
      - try to json-decode from the last such position backwards
      - accept the first successfully decoded dict
    """
    import json
    import re

    if not brain_stdout:
        return None

    # candidates: positions where a JSON object starts at line beginning
    positions = [m.start() for m in re.finditer(r"(?m)^\{", brain_stdout)]
    if not positions:
        return None

    dec = json.JSONDecoder()
    for pos in reversed(positions):
        tail = brain_stdout[pos:].lstrip()
        try:
            obj, _end = dec.raw_decode(tail)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    return None



def short_summary(brain_stdout: str, brain_stderr: str = "", ok: bool = True, exit_code: int = 0) -> str:
    """
    Достаём 1-2 строки итога.
    Приоритет:
      1) если ошибка (ok=false) — первая информативная строка stderr
      2) иначе строка после "[plan] summary:" из stdout
      3) запасной вариант
    """
    if not ok:
        lines = [ln.strip() for ln in (brain_stderr or "").splitlines() if ln.strip()]
        if lines:
            return lines[0][:240]
        # если stderr пустой — вытащим причину из stdout (например, "SKIP (dangerous)")
        for ln in (brain_stdout or "").splitlines():
            t = ln.strip()
            if "SKIP (dangerous)" in t:
                return t[:240]
            if t.startswith("[exec") and "ERROR" in t:
                return t[:240]
        # если stderr пустой — попробуем взять [plan] summary даже при FAIL (shortcut-ветки)
        for line in (brain_stdout or "").splitlines():
            if line.startswith("[plan] summary:"):
                msg = line.split(":", 1)[1].strip()
                return (msg[:240] if msg else f"error (exit_code={exit_code})")

        return f"error (exit_code={exit_code})"

    for line in (brain_stdout or "").splitlines():
        if line.startswith("[plan] summary:"):
            msg = line.split(":", 1)[1].strip()
            return (msg[:240] if msg else "done")

    return "done"




def write_report(payload: Dict[str, Any]) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fp = ARTIFACTS_DIR / f"{ts}_report.json"

    # self-reference path inside report (удобно для парсинга и логов)
    payload["report"] = str(fp)

    fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fp


def _detect_apply(task_text: str, brain_report: Optional[Dict[str, Any]]) -> bool:
    """
    True if this task likely performed APPLY (mutating) operation.
    Heuristics:
      - explicit "mode=apply" in raw task text
      - shortcut tasks that include "confirm=" (usually implies apply)
      - inspect brain_report.results[*].params.mode == "apply"
    """
    t = (task_text or "").lower()
    if "mode=apply" in t:
        return True
    if "confirm=" in t:
        return True

    # try to detect from brain_report
    if isinstance(brain_report, dict):
        results = brain_report.get("results")
        if isinstance(results, list):
            for r in results:
                params = (r or {}).get("params") or {}
                mode = (params.get("mode") or "").lower()
                if mode == "apply":
                    return True
    return False


def _run_remote_healthcheck() -> Dict[str, Any]:
    """
    Runs tools/remote_healthcheck.sh (no snapshot unless MAKE_IIBOT_SNAPSHOT=1 is set).
    Captures stdout/stderr and exit code into the report.
    """
    script = Path(__file__).resolve().parent / "tools" / "remote_healthcheck.sh"
    env = _get_child_env()
    p = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
    )
    return {
        "ok": p.returncode == 0,
        "exit_code": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }

# --- qid->rid support (auto) ---
def _find_request_id_anywhere(obj: Any) -> Optional[str]:
    """
    Recursively scan a dict/list for something that looks like request_id.
    Prefer q_* or rq_*.
    """
    best: Optional[str] = None

    def consider(v: str):
        nonlocal best
        if not isinstance(v, str):
            return
        if v.startswith(("q_", "rq_")):
            # prefer q_/rq_ over anything else
            if best is None:
                best = v
            else:
                # keep the "more specific" one (rq_ > q_)
                if best.startswith("q_") and v.startswith("rq_"):
                    best = v

    def walk(x: Any):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and k == "request_id" and isinstance(v, str):
                    consider(v)
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)
        elif isinstance(x, str):
            consider(x)

    walk(obj)
    return best


def _qid_to_rid(qid: str) -> Dict[str, Any]:
    """
    q_<...> -> rq_<...> by reading /tmp/iibot_<qid>.log on server (via tools/qid_to_rid.sh).
    """
    script = Path(__file__).resolve().parent / "tools" / "qid_to_rid.sh"
    try:
        p = subprocess.run(
            ["bash", str(script), qid],
            capture_output=True,
            text=True,
            env=_get_child_env(),
        )
        rid = (p.stdout or "").strip()
        ok = (p.returncode == 0) and rid.startswith("rq_")
        return {
            "ok": ok,
            "exit_code": p.returncode,
            "qid": qid,
            "rid": rid,
            "stdout": p.stdout,
            "stderr": p.stderr,
        }
    except Exception as e:
        return {"ok": False, "exit_code": 1, "qid": qid, "rid": "", "stdout": "", "stderr": str(e)}


def _audit_match_rid(rid: str) -> Dict[str, Any]:
    """
    Grep audit.jsonl on server for rid (best-effort).
    """
    if not rid:
        return {"ok": False, "exit_code": 2, "rid": rid, "stdout": "", "stderr": "empty rid"}

    cmd = [
        "ssh", "ii-bot-nout",
        f"set -euo pipefail; tail -n 2000 /var/log/iibot/audit.jsonl | grep -nF '{rid}' | tail -n 5 || true"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, env=_get_child_env())
    out = (p.stdout or "").strip()
    return {
        "ok": bool(out),
        "exit_code": p.returncode,
        "rid": rid,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="agent_runner v1.1 (CLI wrapper over agent_brain.py)")
    ap.add_argument("task", nargs="*", help="Task text (in quotes)")
    ap.add_argument("--file", help="Read task text from file")
    ap.add_argument("--json", action="store_true", help="Print JSON result to stdout")
    args = ap.parse_args()

    if args.file:
        task_text = Path(args.file).read_text(encoding="utf-8").strip()
    else:
        task_text = " ".join(args.task).strip()

    if not task_text:
        print('Usage: ./agent_runner.py "твоя задача"  OR  ./agent_runner.py --file task.txt', file=sys.stderr)
        return 2

    brain = run_brain(task_text)
    brain_report = extract_brain_report(brain.get("stdout", ""))
    summary = short_summary(brain.get("stdout",""), brain.get("stderr",""), ok=brain.get("ok", True), exit_code=int(brain.get("exit_code", 0) or 0))

    # prefer summary from structured brain_report when present
    if isinstance(brain_report, dict):
        _s = brain_report.get('summary')
        if isinstance(_s, str) and _s.strip():
            summary = _s.strip()
        else:
            _inner = brain_report.get('brain_report')
            _s2 = _inner.get('summary') if isinstance(_inner, dict) else None
            if isinstance(_s2, str) and _s2.strip():
                summary = _s2.strip()

    # prefer ok/exit_code from structured brain_report when present

    ok_final = bool(brain.get('ok', False))

    exit_code_final = int(brain.get('exit_code', 0) or 0)

    if isinstance(brain_report, dict):

        _ok = brain_report.get('ok')

        if isinstance(_ok, bool):

            ok_final = _ok

            if (not ok_final) and exit_code_final == 0:

                exit_code_final = 1
    report = {
        "task": task_text,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "ok": ok_final,
        "exit_code": exit_code_final,
        "brain": brain,
        "brain_report": brain_report,
    }
    # post-apply: resolve qid->rid (for queued self-ops) and match audit
    did_apply = brain.get("ok") and _detect_apply(task_text, brain_report)

    if did_apply:
        rid0 = _find_request_id_anywhere(brain_report) if isinstance(brain_report, dict) else None
        if rid0:
            report["apply_request_id"] = rid0

            # queued self-op: webhook returns q_..., real rid is inside /tmp log
            if rid0.startswith("q_"):
                qres = _qid_to_rid(rid0)
                report["qid_to_rid"] = qres
                real_rid = qres.get("rid") if qres.get("ok") else ""
                if real_rid:
                    report["apply_real_request_id"] = real_rid
                    report["apply_audit_match"] = _audit_match_rid(real_rid)
            elif rid0.startswith("rq_"):
                report["apply_real_request_id"] = rid0
                report["apply_audit_match"] = _audit_match_rid(rid0)

    # post-apply healthcheck (optional): server / webhook:list_actions / audit for that list_actions
    if did_apply and os.environ.get("DISABLE_POST_APPLY_HEALTHCHECK") != "1":
        # if this was a queued self-op (qid -> rid), give services a moment to come back
        if str(report.get("apply_request_id","")).startswith(("q_","rq_sshfb_")):
            import time
            time.sleep(15)
    report["post_apply_healthcheck"] = _run_remote_healthcheck()

    report_path = write_report(report)

    out = {
        "ok": ok_final,
        "summary": summary,
        "report": str(report_path),
        "exit_code": exit_code_final,
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        # 1-2 строки, чтобы удобно слать в Telegram
        print(summary)
        print(f"report: {report_path}")

    return int(exit_code_final)


if __name__ == "__main__":
    raise SystemExit(main())
