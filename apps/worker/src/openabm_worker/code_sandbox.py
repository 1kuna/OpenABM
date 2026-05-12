from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run_code_judge_dev_sandbox(
    code: str,
    trace_input: dict[str, Any],
    *,
    timeout_seconds: int = 5,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="openabm-code-judge-") as tmp:
        tmp_path = Path(tmp)
        script = tmp_path / "judge.py"
        input_path = tmp_path / "input.json"
        output_path = tmp_path / "result.json"
        script.write_text(code, encoding="utf-8")
        input_path.write_text(json.dumps(trace_input), encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": "",
            "OPENABM_CODE_JUDGE_INPUT": str(input_path),
            "OPENABM_CODE_JUDGE_OUTPUT": str(output_path),
        }
        try:
            completed = subprocess.run(
                ["python3", str(script)],
                cwd=tmp,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "timeout",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "result": None,
                "isolation_level": "dev_only",
            }

        if completed.returncode != 0:
            return {
                "status": "sandbox_error",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "result": None,
                "isolation_level": "dev_only",
            }
        if not output_path.exists():
            return {
                "status": "invalid_result",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "result": None,
                "isolation_level": "dev_only",
            }
        try:
            result = json.loads(output_path.read_text())
        except json.JSONDecodeError:
            return {
                "status": "invalid_result",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "result": None,
                "isolation_level": "dev_only",
            }
        return {
            "status": "succeeded",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "result": result,
            "isolation_level": "dev_only",
        }

