# Security model

The repository is public so that GitHub Actions stays free. Encrypted notebooks therefore sit in
public branches where anyone can download them, and the encryption key is the only thing protecting
them. The main goal of this design is that **no student and no outsider can obtain the key**.

## What is public on purpose

Test cases and expected answers, student emails (in branch names and comments), scores (comments,
artifacts), and the marks and grades CSVs, which may include student names.

## What is protected

- The contents of student notebooks.
- The encryption key and the Google token.
- The integrity of grades: only the pipeline can produce a mark.

## Attacks and what stops them

Each row is covered by tests in `tests/`. The attacks marked **live** run on a real GitHub runner in
the **Selftest: sandbox** workflow.

| Attack | Defence | Test |
| --- | --- | --- |
| The notebook reads a key file left on disk | The key is never written to any file. | `test_encryption` |
| The notebook reads the job's memory or environment. The runner host has passwordless `sudo`, so clearing variables is not enough | The notebook runs in a container with its own process list and file system: a non-root user, no capabilities, `no-new-privileges`, read-only root, no Docker socket. | **live** `test_sandbox_integration` |
| The notebook steals the `GITHUB_TOKEN` from `.git/config` | The container has no checkout. Checkouts use `persist-credentials: false`. The job's token can only read. Comments are posted by a separate job on another machine. | **live**, `test_workflows` |
| Cache poisoning: the notebook modifies Python packages, they get cached, and the next run decrypts with them | The host's Python is never cached. Sandbox dependencies are saved before student code exists on the machine and are mounted read-only. | **live**, `test_workflows` |
| Tricking the host through files the notebook wrote, such as symlinks | The host reads nothing from the container's file system. The only channel is stdout: size-limited and parsed as untrusted JSON. | **live**, `test_sandbox_unit` |
| Reading a solution from public logs through a traceback | Container output is never printed. Only the exception type and cell number leave the sandbox. | **live** |
| Attachment titled `../../src/encryption.py` overwrites code in the privileged download job | Titles are reduced to a single file name. | `test_submission_flow`, `test_naming` |
| A replaced token file runs code when loaded | The token is JSON, never pickle. | `test_submission_flow` |
| Testing a guess against public ciphertext | The nonce is an HMAC under a secret key. The old nonce was an unkeyed hash of the plaintext. | `test_encryption` |
| Commenting `Score: 100/100` on a pull request | Marks count only from the bot, from a marker on the comment's first line that names the same student and assignment. | `test_marks_and_comment` |
| Notebook output forging that marker in the bot's own comment | Student text is flattened into an inline code span, and a marker counts only at the very start. | `test_marks_and_comment` |
| A pull request from a fork posing as a submission | Marks ignore forks. | `test_marks_and_comment` |
| A fork adds a workflow that uploads a fake `grading-report-*` artifact | Aggregation reads only `workflow_dispatch` runs of the grading workflow, which require write access. Fork runs need approval and get no secrets. | `test_workflows` |
| Shell injection through branch names or inputs | Expressions never appear in `run:` scripts, and branch names are validated against a strict pattern. | `test_workflows`, `test_naming` |
| Workflow-command injection through notebook output | Nothing from the notebook is printed to the log. | **live** |
| A compromised action tag | Every action is pinned to a commit. | `test_workflows` |
| A leaked long-lived GitHub token | There is none. Everything uses the short-lived `GITHUB_TOKEN`. | `test_workflows` |

The self-test also runs its probe directly on the host as a control: it has to find the planted
canaries there. Otherwise a clean result from the sandbox would prove nothing.

## What this does not protect against

- **Escaping the container.** The key is in the job's memory on the host while the notebook runs, so
  a working container or kernel exploit would reach it. The hardening above makes that hard, not
  impossible. If that risk matters to you, rotate the key after each course.
- **Wrong answers presented as right.** The grader only sees outputs. A notebook can print the
  expected numbers without computing them, and the expected numbers are public.
- **Plagiarism.** Nothing here detects copying between students.
- **Anyone with write access to the repository**, or a compromised Google or GitHub account of the
  teacher. They can read every secret through a workflow of their own.

## Rotating the key

```bash
python scripts/setup_course.py --skip-google --rotate-key
```

The next download re-encrypts every current submission and regrades it. Old ciphertext stays in the
git history, so if the old key really leaked, submissions encrypted with it remain exposed.

Each course must have its own key. `setup_course.py` generates a new one, so never copy one across.

## Rules when changing this code

- Never run student code on the runner host.
- Never write a secret to a file, and never print anything that came out of a notebook.
- Keep grading on `workflow_dispatch`. Do not add `pull_request` or `pull_request_target` triggers.
- Do not read files from the sandbox on the host.
- `tests/test_workflows.py` encodes these rules. Weakening it should be a deliberate decision.
