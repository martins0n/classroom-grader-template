# Classroom Grader Template

Automatic grading of Jupyter notebook assignments submitted through Google Classroom, running
entirely on GitHub Actions. Create one repository from this template for each course.

```
Google Classroom ──hourly──▶ Download job ──encrypted──▶ student branch + pull request
                                  │
                                  └─ workflow_dispatch ─▶ Grade job
                                                            1. decrypt on the host
                                                            2. run notebook in a locked-down container
                                                            3. score the outputs on the host
                                                          Comment job (separate machine)
                                                            4. post the score on the pull request
```

Student notebooks are stored encrypted, even though the repository is public, and run in a sandbox
that cannot reach the encryption key. [SECURITY.md](SECURITY.md) explains what is protected, how,
and what stays public on purpose.

**Keep course repositories public.** GitHub Actions is free for public repositories, while private
ones use up a limited monthly allowance of minutes. Nothing the sandbox protects depends on the
repository being private.

## Set up a new course

You need Python 3.11+, the [GitHub CLI](https://cli.github.com) 2.31 or newer (`gh auth login`) and a Google
account that teaches the course.

### 1. Create the repository

Click **Use this template** and leave **Include all branches** unticked. Then clone your copy. The
**Selftest: sandbox** workflow runs by itself on the first commit and should turn green. It needs no
secrets.

### 2. Create a Google OAuth client

Only needed once. The same client works for all your courses.

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the
   **Google Classroom API** and the **Google Drive API**.
2. Configure the OAuth consent screen with user type **External**, keep the publishing status at
   **Testing** and add the account that teaches the course under **Audience → Test users**. Only
   listed accounts can log in.
3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app** and save the JSON as
   `credentials.json` in your clone. It is ignored by git.

The token can read all of the account's Google Drive, because that is the only way to read student
attachments. A dedicated Google account for grading limits what a leaked token would expose.

Google documents a 7-day limit on refresh tokens in Testing, yet one course ran for months without
logging in again, so plan for either. If the hourly download fails with `invalid_grant`, run the
setup script again. Publishing the app has not been tried with this template. It needs the Branding
page completed first, and Google may require verification because Drive access is a restricted scope.

### 3. Run the setup script

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/setup_course.py
```

This logs in to Google, lets you pick the courses, generates a new encryption key, stores the
secrets in GitHub and applies the repository settings. It leaves no secrets on your machine other
than `credentials.json`. The encryption key exists only as a GitHub secret.

Log in with the account you added as a test user. Google warns that it has not verified the app:
choose **Continue**, then tick **Select all** on the permissions page.

### 4. Check the pipeline

In the **Actions** tab, run **Selftest: pipeline**. A few minutes later a pull request from
`student-selftest_at_example_com/...` should have a comment with a full score. Close it afterwards.
Marks and grade CSVs ignore this student.

### 5. Add your assignments

See [test_cases/README.md](test_cases/README.md), delete the example assignments you don't need, and
push to `main`. Submissions are picked up within the hour.

## Workflows

| Workflow | Runs | What it does |
| --- | --- | --- |
| Download Student Submissions | hourly, manual | Encrypts new submissions, commits them, opens a PR, starts grading. |
| Grade Homework Submission | started by the download, manual | Grades one student branch and comments the score. |
| Regrade All | manual | Regrades all open submissions, for instance after changing test cases. |
| Generate Marks CSV | weekly, manual | One row per student, one column per assignment, as an artifact. |
| Aggregate Grades | daily, manual | One CSV per assignment, as an artifact. |
| Prebuild Sandbox Dependencies | on change, manual | Installs assignment packages ahead of time. |
| Selftest: sandbox | on change, manual | Attacks the sandbox on a real runner. Needs no secrets. |
| Selftest: pipeline | manual | Sends a sample notebook through the whole pipeline. |

Scheduled workflows stay off until `scripts/setup_course.py` sets the `GRADER_ENABLED` variable. To
pause a course, set that variable to anything else.

To grade one student by hand, run **Grade Homework Submission** with their branch name.

## Sending grades to Classroom

Download a `grades_<assignment>.csv` from an **Aggregate Grades** run, set the assignment's ids and
run this from your clone:

```bash
export ASSIGNMENT_HOMEWORK_1_COURSE_ID=<course id>
export ASSIGNMENT_HOMEWORK_1_COURSEWORK_ID=<coursework id>
python scripts/bulk_submit_grades.py grades_homework-1.csv --dry-run
```

Grades are saved as drafts for you to review and return in Classroom. Classroom only lets an app
grade coursework created by that same app's Google Cloud project, so this can be refused for
assignments created in the Classroom web interface.

## Settings

Optional repository variables (**Settings → Secrets and variables → Actions → Variables**):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SANDBOX_NETWORK` | `bridge` | Set to `none` to cut notebooks off from the network. They then cannot download datasets. |
| `SANDBOX_MEMORY` | `12g` | Memory limit of the sandbox. |
| `SANDBOX_CELL_TIMEOUT` | `3000` | Seconds per notebook cell. |
| `SANDBOX_TIMEOUT` | `6000` | Seconds for the whole notebook. |

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Download fails with `No usable Google token` or `invalid_grant` | The token expired or was revoked. Run `python scripts/setup_course.py` again. |
| Google blocks the login with `Error 403: access_denied` | The account is not a test user of the OAuth app. Add it under **Audience → Test users**. |
| Download fails with `ENCRYPTION_KEY is not set` | Run `python scripts/setup_course.py --skip-google`. |
| `Could not create a pull request` in the download log | "Allow GitHub Actions to create pull requests" is off. Run `python scripts/setup_course.py --skip-google`. |
| Comment says `ModuleNotFoundError` | Add the package to `test_cases/<assignment>/requirements.txt` and run **Regrade All**. |
| Comment says `HardTimeout`, `CellTimeout`, `DeadKernelError` or `NoResult` | The notebook ran too long or ran out of memory, and the comment asks for a manual check. The score of 0 is not a judgement of the work. Check it by hand, or raise the settings above and rerun it. |
| Comment says no expected outputs are configured | The directory name in `test_cases/` differs from the branch's assignment name. |
| Two assignments share one branch | Their titles differ only in non-Latin characters. See [test_cases/README.md](test_cases/README.md). |
