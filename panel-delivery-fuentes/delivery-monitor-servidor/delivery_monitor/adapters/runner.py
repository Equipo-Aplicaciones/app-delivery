"""Ejecuta CLIs existentes en subproceso para no mezclar api_client.py homónimos."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from ..sanitize import looks_like_auth_failure, sanitize

_DROP_ENV = ("PANEL_USER", "PANEL_PASSWORD", "PANEL_PASSWORD_FILE", "SESSION_SECRET", "AUTH_SECRET")


def _child_env() -> dict[str, str]:
    """Los CLI hijos no heredan secretos del panel."""
    env = {}
    for key, value in os.environ.items():
        if key in _DROP_ENV or key.startswith("PANEL_") or key.startswith("SESSION_"):
            continue
        env[key] = value
    return env



class CliError(RuntimeError):
    def __init__(self, message: str, returncode: int | None = None, auth: bool = False):
        super().__init__(message)
        self.returncode = returncode
        self.auth = auth


@dataclass
class CliOutput:
    data: object
    stderr: str
    returncode: int


def run_json_cli(script: str, args: list[str], cwd: str, timeout: int) -> CliOutput:
    cmd = [sys.executable, script, *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise CliError(f"timeout de {timeout}s al ejecutar {script}", auth=False) from exc
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = stdout + "\n" + stderr
    if proc.returncode != 0:
        raise CliError(
            sanitize(stderr or stdout) or f"exit {proc.returncode}",
            returncode=proc.returncode,
            auth=looks_like_auth_failure(combined),
        )
    text = stdout.strip()
    if not text:
        raise CliError(
            sanitize(stderr) or "salida vacía",
            returncode=proc.returncode,
            auth=looks_like_auth_failure(combined),
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        auth = looks_like_auth_failure(combined) or "no-json" in combined.lower()
        raise CliError(
            f"salida no es JSON: {sanitize(text)}",
            returncode=proc.returncode,
            auth=auth,
        ) from exc
    return CliOutput(data=data, stderr=stderr, returncode=proc.returncode)
