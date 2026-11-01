"""Stores encrypted submissions in the repository using the job's GITHUB_TOKEN."""
import base64
import hashlib
import logging
import subprocess
from typing import Dict, List, Optional, Tuple

from github import Auth, Github, GithubException, InputGitTreeElement

logger = logging.getLogger(__name__)

GRADE_WORKFLOW = "grade_submission.yml"


def git_blob_sha(content: bytes) -> str:
    """The object id git gives to this content."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def local_tree_blobs(branch: str, directory: str, remote: str = "origin") -> Dict[str, str]:
    """Return {path: blob sha} for a directory on a branch, from the local clone.

    The download job runs hourly over every submission of every assignment, and GITHUB_TOKEN
    is limited to 1000 API requests an hour. Reading from the clone makes the common case,
    nothing changed, cost no API calls at all.
    """
    ref = f"refs/remotes/{remote}/{branch}"
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        capture_output=True, text=True, check=False,
    )
    if exists.returncode != 0:
        return {}
    listing = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-tree", "-r", ref, "--", directory],
        capture_output=True, text=True, check=True,
    )
    blobs = {}
    for line in listing.stdout.splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    return blobs


class GitHubManager:
    def __init__(self, token: str, repo_name: str):
        self.github = Github(auth=Auth.Token(token))
        self.repo = self.github.get_repo(repo_name)
        self.default_branch = self.repo.default_branch
        logger.info("Connected to GitHub repository: %s", repo_name)

    def get_or_create_branch(self, branch_name: str) -> None:
        try:
            self.repo.get_branch(branch_name)
        except GithubException:
            source = self.repo.get_branch(self.default_branch)
            self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)
            logger.info("Created branch %s", branch_name)

    def commit_files(
        self,
        files: List[Tuple[bytes, str]],
        branch_name: str,
        commit_message: str,
        delete_paths: Optional[List[str]] = None,
    ) -> None:
        """Commit (content, repo_path) pairs and deletions as a single commit."""
        head = self.repo.get_branch(branch_name).commit.sha
        elements = []
        for content, repo_path in files:
            blob = self.repo.create_git_blob(base64.b64encode(content).decode("ascii"), "base64")
            elements.append(InputGitTreeElement(repo_path, "100644", "blob", sha=blob.sha))
        for repo_path in delete_paths or []:
            elements.append(InputGitTreeElement(repo_path, "100644", "blob", sha=None))
        tree = self.repo.create_git_tree(elements, self.repo.get_git_tree(head))
        commit = self.repo.create_git_commit(commit_message, tree, [self.repo.get_git_commit(head)])
        self.repo.get_git_ref(f"heads/{branch_name}").edit(sha=commit.sha, force=False)

    def create_or_update_pull_request(self, branch_name: str, title: str, body: str) -> Optional[str]:
        head = f"{self.repo.owner.login}:{branch_name}"
        try:
            existing = self.repo.get_pulls(state="open", head=head, base=self.default_branch)
            if existing.totalCount > 0:
                pull = existing[0]
                pull.edit(body=body)
                return pull.html_url
            pull = self.repo.create_pull(
                title=title, body=body, head=branch_name, base=self.default_branch
            )
            return pull.html_url
        except GithubException as exc:
            logger.warning(
                "Could not create a pull request (is 'Allow GitHub Actions to create pull "
                "requests' enabled? scripts/setup_course.py turns it on): %s", exc,
            )
            return None

    def dispatch_grading(self, branch_name: str) -> bool:
        """Start grading explicitly.

        Pushes made with GITHUB_TOKEN do not trigger other workflows, but workflow_dispatch
        does. So no long-lived personal access token is needed, and the grading workflow
        always runs the trusted code from the default branch.
        """
        workflow = self.repo.get_workflow(GRADE_WORKFLOW)
        started = workflow.create_dispatch(ref=self.default_branch, inputs={"branch": branch_name})
        if not started:
            logger.error("Could not start grading for %s", branch_name)
        return started
