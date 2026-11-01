"""Everything student code would try in order to reach the key. Standard library only.

Runs inside the sandbox as a notebook cell, and also directly on the runner host as a control.
The control has to find the canaries: otherwise a clean sandbox result would prove nothing.
"""
import ctypes
import json
import os
import socket
import stat
import subprocess
import sys
import time

# Split so that the notebook holding this source does not itself match.
CANARY_PREFIX = "SELFTEST" + "-CANARY-"
HOST_ENV_PREFIXES = ("GITHUB_", "ACTIONS_", "RUNNER_", "SELFTEST_", "ENCRYPTION", "GOOGLE_", "GH_")
SKIP_DIRS = {"node_modules", ".cache", ".cargo", ".rustup", ".dotnet", ".nvm", ".npm", "venv", "site-packages"}


def env_hits():
    return sorted(k for k, v in os.environ.items() if CANARY_PREFIX in v)


def host_env_names():
    return sorted(k for k in os.environ if k.startswith(HOST_ENV_PREFIXES))


def proc_scan():
    hits, runner_visible, count = [], False, 0
    for pid in filter(str.isdigit, os.listdir("/proc")):
        count += 1
        for name in ("environ", "cmdline"):
            try:
                with open(f"/proc/{pid}/{name}", "rb") as stream:
                    data = stream.read()
            except OSError:
                continue
            if CANARY_PREFIX.encode() in data:
                hits.append(f"{pid}/{name}")
            if b"Runner.Worker" in data or b"Runner.Listener" in data:
                runner_visible = True
    return {"hits": hits, "runner_visible": runner_visible, "process_count": count}


def file_hits():
    roots = [os.environ.get(k) for k in ("GITHUB_WORKSPACE", "RUNNER_TEMP", "HOME")]
    roots += ["/work", "/tmp", "/home", "/github", "/root", "/run", "/var/run", "/opt", "/mnt", "/__w"]
    hits, seen, deadline = [], 0, time.time() + 60
    needle = CANARY_PREFIX.encode()
    for root in filter(None, dict.fromkeys(roots)):
        for directory, subdirs, files in os.walk(root, followlinks=False):
            if time.time() > deadline or seen > 50000:
                return sorted(set(hits))
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
            for name in files:
                seen += 1
                path = os.path.join(directory, name)
                try:
                    # Regular files only: opening a FIFO, of which /run has several, blocks forever.
                    info = os.lstat(path)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
                        continue
                    with open(path, "rb") as stream:
                        if needle in stream.read():
                            hits.append(path)
                except OSError:
                    pass
    return sorted(set(hits))


def can_write(directory):
    path = os.path.join(directory, ".probe-write-test")
    try:
        with open(path, "w") as stream:
            stream.write("x")
        os.unlink(path)
        return True
    except OSError:
        return False


def status_field(name):
    with open("/proc/self/status") as stream:
        for line in stream:
            if line.startswith(name + ":"):
                return line.split(":", 1)[1].strip()
    return None


def tcp_reachable(host, port=80, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def gateway_address():
    with open("/proc/net/route") as stream:
        for line in stream.readlines()[1:]:
            fields = line.split()
            if fields[1] == "00000000":
                return socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
    return None


def sudo_works():
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def mount_works():
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.mount(b"none", b"/tmp", b"tmpfs", 0, None) == 0


def resolves(host):
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def runtime_pip_install():
    """Return an empty string on success, otherwise what went wrong."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "cowsay"],
            capture_output=True, text=True, timeout=120,
        )
        if done.returncode != 0:
            return done.stderr[-800:] or f"pip exited with {done.returncode}"
        check = subprocess.run([sys.executable, "-c", "import cowsay"], capture_output=True, text=True)
        return "" if check.returncode == 0 else check.stderr[-800:]
    except (OSError, subprocess.SubprocessError) as exc:
        return repr(exc)


def run_probes(in_sandbox=True):
    result = {
        "env_hits": env_hits(),
        "host_env_names": host_env_names(),
        "proc": proc_scan(),
        "file_hits": file_hits(),
        "uid": os.getuid(),
        "cap_eff": status_field("CapEff"),
        "no_new_privs": status_field("NoNewPrivs"),
        "docker_socket": any(os.path.exists(p) for p in ("/var/run/docker.sock", "/run/docker.sock")),
        "sudo": sudo_works(),
        "host_home_exists": os.path.exists("/home/runner"),
    }
    if in_sandbox:
        result.update(
            writes={d: can_write(d) for d in ("/work", "/tmp", "/venv", "/opt/sandbox", "/usr/local", "/")},
            mount=mount_works(),
            metadata_reachable={h: tcp_reachable(h) for h in ("169.254.169.254", "168.63.129.16")},
            host_ports_open=[p for p in (22, 80, 443, 2375, 2376) if tcp_reachable(gateway_address(), p)],
            dns=resolves("pypi.org"),
            runtime_pip_error=runtime_pip_install(),
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run_probes(in_sandbox=False)))
