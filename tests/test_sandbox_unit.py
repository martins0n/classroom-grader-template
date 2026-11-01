import json

import pytest

from src.sandbox import SandboxConfig, build_docker_args, parse_result


def args():
    config = SandboxConfig(deps_dir="/deps", image="img:1")
    return build_docker_args(config, "/tmp/work", "a.ipynb", "name")


def test_container_is_locked_down():
    command = args()
    for flag in ("--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--rm", "--init"):
        assert flag in command
    assert command[command.index("--user") + 1] == "65534:65534"


def test_nothing_dangerous_is_passed_in():
    text = " ".join(args())
    for forbidden in ("--privileged", "docker.sock", "--env-file", "--pid=host", "--network=host",
                      "--ipc=host", "--cap-add", "GITHUB", "ENCRYPTION", "TOKEN", "/home/runner"):
        assert forbidden not in text


def test_every_env_var_is_an_explicit_value():
    command = args()
    values = [command[i + 1] for i, item in enumerate(command) if item == "--env"]
    assert values and all("=" in value for value in values)


def test_dependencies_and_runner_are_read_only():
    mounts = [item for item in args() if item.startswith("type=bind")]
    assert sum("readonly" in mount for mount in mounts) == 2
    assert [m for m in mounts if "readonly" not in m] == ["type=bind,src=/tmp/work,dst=/work"]


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b"null", b"{}", b'{"status":"ok"}', b'{"status":"ok","outputs":1}',
    b'{"status":"weird"}', b"[" * 100000, b'{"status":"ok","outputs":[]}{"status":"ok","outputs":[1]}',
])
def test_malformed_results_are_a_failure_not_a_crash(raw):
    assert parse_result(raw).ok is False


def test_error_fields_are_validated():
    result = parse_result(json.dumps({"status": "error", "error_type": "x\n::error::pwned", "cell_index": "1; rm"}).encode())
    assert result.error_type == "UnknownError" and result.cell_index is None
    assert parse_result(b'{"status":"error","error_type":"ValueError","cell_index":2}').cell_index == 2
    assert parse_result(b'{"status":"error","error_type":"E","cell_index":true}').cell_index is None


def test_good_result():
    result = parse_result(b'{"status":"ok","outputs":[{"a":1}]}')
    assert result.ok and result.outputs == [{"a": 1}]
