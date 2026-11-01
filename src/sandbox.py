"""Runs student notebooks in a locked-down container on the GitHub runner.

Student code must never run on the runner host. The host can read the job's secrets
from the memory of the runner process (passwordless sudo is available there), so clearing
environment variables or deleting key files is not enough. Inside the container there is
no host process, host file system, token or Docker socket to reach.

The only channel back is the container's stdout, read with a size limit and parsed as
untrusted JSON. The host never reads a path the container could have written, because a
symlink planted there would resolve on the host.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "sandbox" / "runner.py"
IMAGE_FILE = REPO_ROOT / "sandbox" / "image.txt"
SANDBOX_UID = "65534:65534"  # "nobody": not root and not the runner user either
MAX_RESULT_BYTES = 16 * 1024 * 1024
DOCKER_FAILURE_CODES = {125, 126, 127}
WAIT_AFTER_EXIT_SECONDS = 30
KILL_TIMEOUT_SECONDS = 30
_ERROR_TYPE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,99}")


class SandboxError(RuntimeError):
    """Infrastructure failure: says nothing about the student's work."""


@dataclass
class SandboxConfig:
    deps_dir: str
    image: str = ""
    network: str = "bridge"
    memory: str = "12g"
    pids_limit: int = 4096
    cell_timeout: int = 3000
    hard_timeout: int = 6000

    def __post_init__(self):
        if not self.image:
            self.image = IMAGE_FILE.read_text().strip()

    @classmethod
    def from_env(cls) -> "SandboxConfig":
        deps_dir = os.environ.get("SANDBOX_DEPS_DIR", "")
        if not deps_dir:
            raise SandboxError("SANDBOX_DEPS_DIR is not set; run prepare-sandbox first")
        return cls(
            deps_dir=deps_dir,
            network=os.environ.get("SANDBOX_NETWORK") or "bridge",
            memory=os.environ.get("SANDBOX_MEMORY") or "12g",
            cell_timeout=int(os.environ.get("SANDBOX_CELL_TIMEOUT") or 3000),
            hard_timeout=int(os.environ.get("SANDBOX_TIMEOUT") or 6000),
        )


@dataclass
class ExecutionResult:
    ok: bool
    outputs: List[Any] = field(default_factory=list)
    error_type: Optional[str] = None
    cell_index: Optional[int] = None


def _dns_args(network: str) -> List[str]:
    # By default containers on a runner resolve names through 168.63.129.16. That is also the
    # Azure host endpoint prepare-sandbox blocks, so they need a resolver of their own.
    return [] if network == "none" else ["--dns=1.1.1.1", "--dns=8.8.8.8"]


def build_docker_args(
    config: SandboxConfig, work_dir: str, notebook_name: str, container_name: str
) -> List[str]:
    return [
        "docker", "run", "--rm", "--init",
        "--name", container_name,
        "--user", SANDBOX_UID,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=4g,mode=1777",
        "--shm-size=1g",
        f"--pids-limit={config.pids_limit}",
        f"--memory={config.memory}",
        f"--memory-swap={config.memory}",
        f"--network={config.network}",
        *_dns_args(config.network),
        "--log-driver=none",
        "--workdir", "/work",
        "--mount", f"type=bind,src={work_dir},dst=/work",
        "--mount", f"type=bind,src={config.deps_dir},dst=/venv,readonly",
        "--mount", f"type=bind,src={RUNNER_PATH},dst=/opt/sandbox/runner.py,readonly",
        # Explicit allow-list: nothing from the host environment gets in.
        "--env", "HOME=/work/.home",
        "--env", "PATH=/venv/bin:/usr/local/bin:/usr/bin:/bin",
        "--env", "MPLBACKEND=Agg",
        "--env", "PYTHONUNBUFFERED=1",
        "--env", f"SANDBOX_CELL_TIMEOUT={config.cell_timeout}",
        config.image,
        "/venv/bin/python", "/opt/sandbox/runner.py", f"/work/{notebook_name}",
    ]


def parse_result(raw: bytes) -> ExecutionResult:
    """Validate the runner's answer. It comes from a process the student controls."""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return ExecutionResult(ok=False, error_type="NoResult")
    if not isinstance(data, dict):
        return ExecutionResult(ok=False, error_type="NoResult")
    if data.get("status") == "ok" and isinstance(data.get("outputs"), list):
        return ExecutionResult(ok=True, outputs=data["outputs"])
    if data.get("status") == "error":
        error_type = data.get("error_type")
        if not (isinstance(error_type, str) and _ERROR_TYPE_RE.fullmatch(error_type)):
            error_type = "UnknownError"
        cell_index = data.get("cell_index")
        if not (type(cell_index) is int and 0 <= cell_index < 1_000_000):
            cell_index = None
        return ExecutionResult(ok=False, error_type=error_type, cell_index=cell_index)
    return ExecutionResult(ok=False, error_type="NoResult")


def _prepare_work_dir(notebook_path: Path, work_dir: Path) -> None:
    """Copy only this submission's files into a directory the sandbox user can write."""
    work_dir.mkdir()
    for item in notebook_path.parent.iterdir():
        if item.is_file() and not item.is_symlink():
            target = work_dir / item.name
            shutil.copyfile(item, target)
            target.chmod(0o666)
    home = work_dir / ".home"
    home.mkdir()
    home.chmod(0o777)
    work_dir.chmod(0o777)


def run_notebook(notebook_path: Path, config: Optional[SandboxConfig] = None) -> ExecutionResult:
    config = config or SandboxConfig.from_env()
    temp_root = tempfile.mkdtemp(prefix="sandbox-", dir=os.environ.get("RUNNER_TEMP"))
    container_name = f"grader-{uuid.uuid4().hex}"
    verdict = {"error_type": None}

    try:
        work_dir = Path(temp_root) / "work"
        _prepare_work_dir(notebook_path, work_dir)
        args = build_docker_args(config, str(work_dir), notebook_path.name, container_name)
        with tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr
            )

            def stop_container(error_type: str) -> None:
                verdict["error_type"] = error_type
                try:
                    subprocess.run(
                        ["docker", "kill", container_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                        timeout=KILL_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    pass
                # Ending the client closes the pipe, and that ends the read loop below.
                process.kill()

            timer = threading.Timer(config.hard_timeout, stop_container, ["HardTimeout"])
            timer.start()
            received = bytearray()
            too_large = False
            try:
                # Keep reading until the client is gone, even past the limit. "docker kill"
                # hangs while the container's output is backed up, so one notebook printing
                # too much would otherwise hold the job until its timeout.
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    if too_large:
                        continue
                    if len(received) + len(chunk) > MAX_RESULT_BYTES:
                        too_large = True
                        received.clear()
                        threading.Thread(
                            target=stop_container, args=["OutputTooLarge"], daemon=True
                        ).start()
                        continue
                    received.extend(chunk)
                process.stdout.close()
                try:
                    returncode = process.wait(timeout=WAIT_AFTER_EXIT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    returncode = process.wait()
            finally:
                timer.cancel()
            if verdict["error_type"]:
                return ExecutionResult(ok=False, error_type=verdict["error_type"])
            if returncode in DOCKER_FAILURE_CODES and not received:
                # Docker itself failed and the container never ran, so its message
                # cannot contain student output and is safe to show.
                stderr.seek(0)
                message = stderr.read(2000).decode("utf-8", "replace")
                raise SandboxError(f"docker run failed ({returncode}): {message}")
            return parse_result(bytes(received))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
