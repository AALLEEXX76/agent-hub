#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from json import JSONDecoder


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
BRAIN = Path(__file__).resolve().parent / "agent_brain.py"


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
    )
    return {
        "ok": p.returncode == 0,
        "exit_code": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }


def extract_brain_report(brain_stdout: str) -> Optional[Dict[str, Any]]:
    """
    Достаём финальный JSON, который agent_brain.py печатает после:
      [report] done.
      { ...json... }
    """
    marker = "\n[report] done.\n"
    i = brain_stdout.rfind(marker)
    if i == -1:
        return None

    tail = brain_stdout[i + len(marker):].strip()
    if not tail:
        return None

    try:
        dec = JSONDecoder()
        obj, idx = dec.raw_decode(tail)
        # Если после JSON есть мусор — считаем это ошибкой формата
        rest = tail[idx:].strip()
        if rest:
            return None
        if isinstance(obj, dict):
            return obj
        return None
    except Exception:
        return None


def short_summary(brain_stdout: str, brain_stderr: str = "", ok: bool = True, exit_code: int = 0) -> str:
    """
    Достаём 1-2 строки итога.
    Приоритет:
      1) строка после "[plan] summary:" из stdout
      2) если ошибка — хвост stderr (например, "ANTHROPIC_API_KEY not found")
      3) запасной вариант
    """
    for line in (brain_stdout or "").splitlines():
        if line.startswith("[plan] summary:"):
            s = line.split(":", 1)[1].strip()
            return (s[:240] if s else "done")

    if not ok:
        tail = (brain_stderr or "").strip().splitlines()[-1:]  # последняя строка
        msg = tail[0] if tail else (brain_stderr or "").strip()
        msg = msg.strip()
        if msg:
            return (msg[:240])
        return f"error (exit_code={exit_code})"

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
