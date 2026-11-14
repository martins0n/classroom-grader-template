from types import SimpleNamespace

import scripts.run_grader as run_grader


def test_only_the_first_notebook_by_name_runs_and_the_rest_are_reported(tmp_path, monkeypatch):
    for name in ["homework_4_v2.ipynb", "homework_4.ipynb", "data.csv"]:
        (tmp_path / name).write_text("{}")
    ran = []
    monkeypatch.setattr(
        run_grader, "run_notebook",
        lambda path: ran.append(path.name) or SimpleNamespace(ok=True, outputs=[]),
    )
    report = run_grader.grade("student", "hw-1", tmp_path, tmp_path / "no-test-cases")
    assert ran == ["homework_4.ipynb"]
    assert report["notebook"] == "homework_4.ipynb"
    assert report["ignored_notebooks"] == ["homework_4_v2.ipynb"]


def test_a_single_notebook_reports_nothing_ignored(tmp_path, monkeypatch):
    (tmp_path / "solution.ipynb").write_text("{}")
    monkeypatch.setattr(run_grader, "run_notebook", lambda path: SimpleNamespace(ok=True, outputs=[]))
    report = run_grader.grade("student", "hw-1", tmp_path, tmp_path / "no-test-cases")
    assert report["notebook"] == "solution.ipynb"
    assert "ignored_notebooks" not in report
