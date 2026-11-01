"""Real attacks in a real container. These run in the 'Selftest: sandbox' workflow."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import ROOT, write_notebook
from scripts.run_grader import grade
from src.sandbox import SandboxConfig, run_notebook

EXAMPLES = [
    ("homework-1-example", "sample_solution.ipynb"),
    ("homework-2-example", "solution.ipynb"),
    ("homework-3-performance", "solution.ipynb"),
]


def probe_notebook(path: Path) -> Path:
    source = (ROOT / "tests" / "probe.py").read_text().split('if __name__ == "__main__":')[0]
    return write_notebook(path, source + "\nprint(json.dumps(run_probes()))")


@pytest.fixture(scope="module")
def probe_result(sandbox_ready, tmp_path_factory):
    result = run_notebook(probe_notebook(tmp_path_factory.mktemp("probe") / "attack.ipynb"))
    assert result.ok, result.error_type
    assert len(result.outputs) == 1
    return result.outputs[0]


def test_sandbox_sees_no_canary_anywhere(probe_result):
    assert probe_result["env_hits"] == []
    assert probe_result["proc"]["hits"] == []
    assert probe_result["file_hits"] == []


def test_sandbox_inherits_nothing_from_the_host_environment(probe_result):
    assert probe_result["host_env_names"] == []


def test_runner_process_and_host_are_out_of_reach(probe_result):
    assert probe_result["proc"]["runner_visible"] is False
    assert probe_result["host_home_exists"] is False
    assert probe_result["docker_socket"] is False
    assert probe_result["sudo"] is False


def test_sandbox_has_no_privileges(probe_result):
    assert probe_result["uid"] == 65534
    assert int(probe_result["cap_eff"], 16) == 0
    assert probe_result["no_new_privs"] == "1"
    assert probe_result["mount"] is False


def test_only_scratch_space_is_writable(probe_result):
    assert probe_result["writes"] == {
        "/work": True, "/tmp": True, "/venv": False, "/opt/sandbox": False, "/usr/local": False, "/": False,
    }


def test_cloud_metadata_is_blocked(probe_result):
    assert not any(probe_result["metadata_reachable"].values())


def test_services_on_the_host_are_blocked(probe_result):
    assert probe_result["host_ports_open"] == []


def test_notebooks_can_resolve_names(probe_result):
    """Real assignments download their data."""
    assert probe_result["dns"] is True


def test_notebooks_can_still_pip_install_at_runtime(probe_result):
    assert probe_result["runtime_pip_error"] == ""


def test_control_same_probe_on_the_host_finds_the_canaries(sandbox_ready):
    """Guards against a vacuous pass: the probe must work where the secrets really are."""
    if not os.environ.get("SELFTEST_CANARY"):
        pytest.skip("canaries are planted by the workflow")
    done = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "probe.py")],
        capture_output=True, text=True, check=True, timeout=200,
    )
    control = json.loads(done.stdout)
    assert "SELFTEST_CANARY" in control["env_hits"]
    assert sum(hit.endswith(".selftest-canary") for hit in control["file_hits"]) >= 3
    assert control["proc"]["runner_visible"] is True
    assert control["sudo"] is True


@pytest.mark.parametrize("assignment,notebook", EXAMPLES)
def test_example_solutions_get_full_marks(sandbox_ready, assignment, notebook):
    source = ROOT / "test_cases" / assignment
    report = grade("student", assignment, _only(source, notebook), ROOT / "test_cases")
    assert report.get("score") == 100, report


def _only(source: Path, notebook: str) -> Path:
    import shutil
    import tempfile

    target = Path(tempfile.mkdtemp())
    shutil.copy(source / notebook, target / notebook)
    return target


def test_crashing_notebook_leaks_no_source_to_logs_or_report(sandbox_ready, tmp_path):
    marker = "PRIVATE-SOLUTION-MARKER"
    submission = tmp_path / "submission"
    submission.mkdir()
    write_notebook(submission / "work.ipynb", "x = 1", f"raise ValueError('{marker}')  # {marker}")
    report_path = tmp_path / "report.json"
    done = subprocess.run(
        [sys.executable, "scripts/run_grader.py", "--student-id", "student", "--assignment-id",
         "homework-1-example", "--submission-dir", str(submission), "--output", str(report_path)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr
    assert marker not in done.stdout + done.stderr
    report = json.loads(report_path.read_text())
    assert marker not in json.dumps(report)
    assert report["error_type"] == "ValueError"
    assert report["cell_index"] == 1
    assert report["score"] == 0.0


def test_runaway_notebook_is_killed(sandbox_ready, tmp_path):
    config = SandboxConfig(deps_dir=os.environ["SANDBOX_DEPS_DIR"], hard_timeout=20)
    notebook = write_notebook(tmp_path / "slow.ipynb", "import time; time.sleep(600)")
    started = time.time()
    result = run_notebook(notebook, config)
    assert result.ok is False and result.error_type == "HardTimeout"
    assert time.time() - started < 60


def test_flooding_the_result_channel_is_bounded(sandbox_ready, tmp_path):
    notebook = write_notebook(
        tmp_path / "flood.ipynb",
        "import os\n"
        "fd = os.open('/proc/1/fd/1', os.O_WRONLY)\n"
        "chunk = b'A' * 1048576\n"
        "for _ in range(64):\n"
        "    os.write(fd, chunk)\n",
    )
    started = time.time()
    result = run_notebook(notebook)
    assert result.ok is False
    assert result.error_type in ("OutputTooLarge", "NoResult")
    assert time.time() - started < 120


def test_student_cannot_forge_a_host_read_through_symlinks(sandbox_ready, tmp_path):
    """The host reads nothing from the sandbox, so planted links lead nowhere."""
    notebook = write_notebook(
        tmp_path / "links.ipynb",
        "import os, json\n"
        "os.symlink('/etc/passwd', 'result.json')\n"
        "os.symlink('/', 'out')\n"
        "print(json.dumps({'ok': True}))",
    )
    result = run_notebook(notebook)
    assert result.ok and result.outputs == [{"ok": True}]
