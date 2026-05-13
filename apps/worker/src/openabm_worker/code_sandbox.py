from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

ALLOWED_IMPORT_ROOTS = {
    "collections",
    "datetime",
    "functools",
    "itertools",
    "json",
    "math",
    "os",
    "re",
    "statistics",
    "time",
    "typing",
}
FORBIDDEN_IMPORT_ROOTS = {
    "builtins",
    "ctypes",
    "http",
    "httpx",
    "multiprocessing",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "urllib",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "breakpoint",
}
FORBIDDEN_OS_CALLS = {
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "fork",
    "kill",
    "open",
    "popen",
    "remove",
    "removedirs",
    "rename",
    "replace",
    "rmdir",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "system",
    "unlink",
}
SCORE_STATUSES = {"succeeded", "failed", "timeout", "invalid_output", "skipped"}

RUNNER_SOURCE = r'''
from __future__ import annotations

import builtins
import os
import runpy

INPUT_PATH = os.path.abspath(os.environ["OPENABM_CODE_JUDGE_INPUT"])
OUTPUT_PATH = os.path.abspath(os.environ["OPENABM_CODE_JUDGE_OUTPUT"])
ARTIFACT_DIR = os.path.abspath(os.environ["OPENABM_CODE_JUDGE_ARTIFACT_DIR"])
ORIGINAL_OPEN = builtins.open


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _guarded_open(file, mode="r", *args, **kwargs):
    path = os.path.abspath(os.fspath(file))
    write_mode = any(flag in str(mode) for flag in ("w", "a", "+", "x"))
    if write_mode:
        if path != OUTPUT_PATH and not _inside(path, ARTIFACT_DIR):
            raise PermissionError("code judges may write only their output or artifact directory")
    elif path != INPUT_PATH and not _inside(path, ARTIFACT_DIR):
        raise PermissionError("code judges may read only their input or artifact directory")
    return ORIGINAL_OPEN(path, mode, *args, **kwargs)


builtins.open = _guarded_open
runpy.run_path(os.environ["OPENABM_CODE_JUDGE_SCRIPT"], run_name="__main__")
'''


def run_code_judge_dev_sandbox(
    code: str,
    trace_input: dict[str, Any],
    *,
    timeout_seconds: int = 5,
    cpu_seconds: int = 2,
    memory_mb: int = 256,
    allowed_import_roots: set[str] | None = None,
) -> dict[str, Any]:
    policy_error = _sandbox_policy_error(
        code,
        allowed_import_roots=allowed_import_roots or ALLOWED_IMPORT_ROOTS,
    )
    policy = _sandbox_policy(
        allowed_import_roots=allowed_import_roots or ALLOWED_IMPORT_ROOTS,
        timeout_seconds=timeout_seconds,
        cpu_seconds=cpu_seconds,
        memory_mb=memory_mb,
    )
    if policy_error:
        return _sandbox_result(
            "failed",
            failure_reason="permission_denied",
            stderr=policy_error,
            policy=policy,
        )
    with tempfile.TemporaryDirectory(prefix="openabm-code-judge-") as tmp:
        tmp_path = Path(tmp)
        script = tmp_path / "judge.py"
        runner = tmp_path / "runner.py"
        artifact_dir = tmp_path / "artifacts"
        input_path = tmp_path / "input.json"
        output_path = tmp_path / "result.json"
        artifact_dir.mkdir()
        script.write_text(code, encoding="utf-8")
        runner.write_text(RUNNER_SOURCE, encoding="utf-8")
        input_path.write_text(json.dumps(trace_input), encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": "",
            "OPENABM_CODE_JUDGE_INPUT": str(input_path),
            "OPENABM_CODE_JUDGE_OUTPUT": str(output_path),
            "OPENABM_CODE_JUDGE_ARTIFACT_DIR": str(artifact_dir),
            "OPENABM_CODE_JUDGE_SCRIPT": str(script),
        }
        try:
            completed = subprocess.run(
                [sys.executable, str(runner)],
                cwd=tmp,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                preexec_fn=_resource_limiter(cpu_seconds, memory_mb),
            )
        except subprocess.TimeoutExpired as exc:
            return _sandbox_result(
                "timeout",
                failure_reason="resource_exceeded",
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                policy=policy,
            )

        if completed.returncode != 0:
            return _sandbox_result(
                "failed",
                failure_reason="sandbox_error",
                stdout=completed.stdout,
                stderr=completed.stderr,
                policy=policy,
            )
        if not output_path.exists():
            return _sandbox_result(
                "invalid_output",
                failure_reason="invalid_result",
                stdout=completed.stdout,
                stderr=completed.stderr,
                policy=policy,
            )
        try:
            result = json.loads(output_path.read_text())
        except json.JSONDecodeError:
            return _sandbox_result(
                "invalid_output",
                failure_reason="invalid_result",
                stdout=completed.stdout,
                stderr=completed.stderr,
                policy=policy,
            )
        return _sandbox_result(
            "succeeded",
            stdout=completed.stdout,
            stderr=completed.stderr,
            result=result,
            policy=policy,
        )


def _sandbox_policy_error(code: str, *, allowed_import_roots: set[str]) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"invalid Python syntax: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                error = _import_policy_error(alias.name, allowed_import_roots)
                if error:
                    return error
        elif isinstance(node, ast.ImportFrom):
            error = _import_policy_error(node.module or "", allowed_import_roots)
            if error:
                return error
        elif isinstance(node, ast.Call):
            error = _call_policy_error(node)
            if error:
                return error
    return None


def _import_policy_error(module: str, allowed_import_roots: set[str]) -> str | None:
    root = module.split(".", 1)[0]
    if root in FORBIDDEN_IMPORT_ROOTS:
        return f"import {module!r} is blocked in the default code judge sandbox"
    if root not in allowed_import_roots:
        return f"import {module!r} is not in the allowed dependency set"
    return None


def _call_policy_error(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
        return f"call {node.func.id!r} is blocked in the default code judge sandbox"
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr in FORBIDDEN_OS_CALLS
    ):
        return f"os.{node.func.attr} is blocked in the default code judge sandbox"
    return None


def _resource_limiter(cpu_seconds: int, memory_mb: int) -> Any:
    if resource is None:
        return None

    def apply_limits() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except (OSError, ValueError):
            pass
        if hasattr(resource, "RLIMIT_AS"):
            memory_bytes = memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            except (OSError, ValueError):
                pass

    return apply_limits


def _sandbox_policy(
    *,
    allowed_import_roots: set[str],
    timeout_seconds: int,
    cpu_seconds: int,
    memory_mb: int,
) -> dict[str, Any]:
    return {
        "dependency_mode": "standard_library_allowlist",
        "allowed_import_roots": sorted(allowed_import_roots),
        "network_disabled": True,
        "filesystem": {
            "input": "read_only",
            "output": "single_result_file",
            "artifacts": "temporary_directory",
            "project": "not_mounted",
        },
        "limits": {
            "wall_clock_timeout_seconds": timeout_seconds,
            "cpu_seconds": cpu_seconds,
            "memory_mb": memory_mb,
        },
        "secrets_mounted": False,
        "artifact_cleanup": "temporary_directory_removed",
    }


def _sandbox_result(
    status: str,
    *,
    failure_reason: str | None = None,
    stdout: str = "",
    stderr: str = "",
    result: dict[str, Any] | None = None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if status not in SCORE_STATUSES:
        raise ValueError(f"Unsupported code judge status: {status}")
    return {
        "status": status,
        "failure_reason": failure_reason,
        "stdout": stdout,
        "stderr": stderr,
        "result": result,
        "isolation_level": "dev_only",
        "sandbox_policy": policy,
    }
