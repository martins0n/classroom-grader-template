"""Security invariants of the workflows. A failure here usually means a hole has been reopened."""
import re
from pathlib import Path

import pytest
import yaml

from conftest import ROOT

WORKFLOW_DIR = ROOT / ".github" / "workflows"
FILES = sorted(WORKFLOW_DIR.glob("*.yml"))
ACTION = ROOT / ".github" / "actions" / "prepare-sandbox" / "action.yml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def triggers(workflow: dict) -> dict:
    # YAML 1.1 reads the bare key "on" as boolean True.
    return workflow.get(True) or workflow.get("on")


def all_steps(workflow: dict):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


def test_found_the_workflows():
    assert len(FILES) == 8


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
class TestEveryWorkflow:
    def test_no_trigger_runs_untrusted_code_with_privileges(self, path):
        on = triggers(load(path))
        assert "pull_request_target" not in on and "workflow_run" not in on
        assert "pull_request" not in on

    def test_token_has_no_default_permissions(self, path):
        workflow = load(path)
        assert workflow["permissions"] == {}
        assert all("permissions" in job for job in workflow["jobs"].values())

    def test_checkout_never_leaves_credentials_behind(self, path):
        for step in all_steps(load(path)):
            if step.get("uses", "").startswith("actions/checkout"):
                assert step["with"]["persist-credentials"] is False

    def test_actions_are_pinned_to_a_commit(self, path):
        for step in all_steps(load(path)):
            uses = step.get("uses", "")
            if uses and not uses.startswith("./"):
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses

    def test_nothing_saves_a_cache_implicitly_after_student_code(self, path):
        for step in all_steps(load(path)):
            uses = step.get("uses", "")
            assert not re.match(r"actions/cache@", uses)
            if uses.startswith("actions/setup-python"):
                assert "cache" not in step.get("with", {})

    def test_secrets_are_only_given_to_single_steps_through_env(self, path):
        for job in load(path)["jobs"].values():
            assert "secrets." not in str(job.get("env", {}))
            for step in job.get("steps", []):
                outside_env = {k: v for k, v in step.items() if k != "env"}
                assert "secrets." not in str(outside_env), step.get("name")
                assert "github.token" not in str(outside_env), step.get("name")

    def test_no_expression_is_pasted_into_a_shell_script(self, path):
        for step in all_steps(load(path)):
            assert "${{" not in step.get("run", ""), step.get("name")

    def test_schedules_stay_off_until_setup_ran(self, path):
        workflow = load(path)
        if "schedule" in triggers(workflow):
            for job in workflow["jobs"].values():
                assert "vars.GRADER_ENABLED == 'true'" in job["if"]


class TestGradingWorkflow:
    workflow = load(WORKFLOW_DIR / "grade_submission.yml")
    grade = workflow["jobs"]["grade"]
    names = [step.get("name") for step in grade["steps"]]

    def index(self, name):
        return self.names.index(name)

    def test_only_a_person_or_workflow_with_write_access_can_start_it(self):
        assert set(triggers(self.workflow)) == {"workflow_dispatch"}

    def test_job_running_student_code_can_only_read(self):
        assert self.grade["permissions"] == {"contents": "read"}

    def test_key_is_given_to_the_decrypt_step_and_nothing_else(self):
        holders = [s["name"] for s in self.grade["steps"] if "secrets." in str(s)]
        assert holders == ["Decrypt submission"]
        decrypt = self.grade["steps"][self.index("Decrypt submission")]
        assert set(re.findall(r"secrets\.(\w+)", str(decrypt))) == {"ENCRYPTION_KEY"}

    def test_key_is_not_in_the_step_that_runs_student_code(self):
        step = self.grade["steps"][self.index("Run notebook in the sandbox and score it")]
        assert "secrets." not in str(step) and "ENCRYPTION" not in str(step)

    def test_sandbox_is_ready_before_the_key_appears(self):
        assert (
            self.index("Prepare sandbox")
            < self.index("Decrypt submission")
            < self.index("Run notebook in the sandbox and score it")
            < self.index("Upload grading report")
        )

    def test_writing_comments_happens_on_another_machine_without_the_key(self):
        comment = self.workflow["jobs"]["comment"]
        assert comment["needs"] == "grade"
        assert comment["permissions"] == {"contents": "read", "pull-requests": "write"}
        assert "secrets." not in str(comment)


def test_composite_action_saves_the_cache_only_on_a_miss_and_before_returning():
    steps = load(ACTION)["runs"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    assert sum(u.startswith("actions/cache/restore") for u in uses) == 1
    assert sum(u.startswith("actions/cache/save") for u in uses) == 1
    for step in steps:
        uses_value = step.get("uses", "")
        if uses_value:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses_value)
        assert "${{" not in step.get("run", "")


def test_old_token_and_key_names_are_gone():
    text = "\n".join(path.read_text() for path in FILES)
    for name in ("PAT_TOKEN", "DEFAULT_ENCRYPTION_KEY", "ENCRYPTION_KEYS", "USE_DEFAULT_ENCRYPTION_KEY", "GOOGLE_CREDENTIALS"):
        assert name not in text
