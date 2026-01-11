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
    Robustly extract the JSON report printed by agent_brain.py.

    Brain stdout may contain extra log lines after the JSON (e.g. post-apply healthcheck),
    so we scan lines from bottom to top and parse the first JSON-looking line.
    """
    import json

    if not brain_stdout:
        return None

    for ln in reversed(brain_stdout.splitlines()):
        t = (ln or "").strip()
        if not t:
            continue
        if t.startswith("{") and t.endswith("}"):
            try:
                obj = json.loads(t)
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

    report = {
        "task": task_text,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "ok": brain["ok"],
        "exit_code": brain["exit_code"],
        "brain": brain,
        "brain_report": brain_report,
    }

    report_path = write_report(report)

    out = {
        "ok": brain["ok"],
        "summary": summary,
        "report": str(report_path),
        "exit_code": brain["exit_code"],
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        # 1-2 строки, чтобы удобно слать в Telegram
        print(summary)
        print(f"report: {report_path}")

    return 0 if brain["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
