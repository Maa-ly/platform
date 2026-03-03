#!/usr/bin/env python3
"""Automated bug detection and reporting system for security auditing workflows."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import mimetypes
import os
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests
import yaml


GITHUB_API_BASE = "https://api.github.com"
DEFAULT_EXTERNAL_REPO = "PlatformNetwork/bounty-challenge"
DEFAULT_DAILY_VALID_TARGET = 25
DEFAULT_POLL_SECONDS = 120
INVALID_LABELS = {"invalid"}


class ConfigError(RuntimeError):
    """Raised when configuration is invalid."""


class GitHubAPIError(RuntimeError):
    """Raised when GitHub API calls fail."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def today_str() -> str:
    return dt.date.today().isoformat()


def looks_like_placeholder_token(token: str) -> bool:
    lowered = token.strip().lower()
    return lowered in {"", "your_token_here", "changeme", "<token>", "token"}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_git_url(source: str) -> bool:
    lowered = source.lower()
    return lowered.startswith("https://") or lowered.startswith("http://") or lowered.startswith("git@")


def json_dump(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def json_load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class PromptConfig:
    id: str
    prompt: str
    detector_cmd: str
    severity: str = "medium"


@dataclass
class RepoConfig:
    github_name: str
    name: str
    owner: str
    repo: str
    token: str
    labels: List[str] = field(default_factory=list)
    issue_template: Optional[str] = None


@dataclass
class RuntimeConfig:
    state_dir: Path
    dedup_db: Path
    daily_state_file: Path
    summary_file: Path
    clone_root: Path
    poll_interval_seconds: int = DEFAULT_POLL_SECONDS
    valid_target_per_repo: int = DEFAULT_DAILY_VALID_TARGET
    stop_when_targets_met: bool = True


@dataclass
class ProofConfig:
    allowed_image_extensions: List[str]
    allowed_video_extensions: List[str]
    upload_cmd: Optional[str]
    auto_capture_cmd: Optional[str]
    screenshot_example_url: str
    video_example_url: str
    banned_format_url: str


@dataclass
class SubmissionConfig:
    title_template: str = "[Bug][alpha]{title}"
    issue_repo: str = DEFAULT_EXTERNAL_REPO


@dataclass
class AppConfig:
    prompts: List[PromptConfig]
    repositories: List[RepoConfig]
    runtime: RuntimeConfig
    proof: ProofConfig
    submission: SubmissionConfig
    external_dedup_repo: str = DEFAULT_EXTERNAL_REPO
    external_dedup_token_env: Optional[str] = None


@dataclass
class BugCandidate:
    title: str
    description: str
    reproduction_steps: List[str]
    impact: str
    native_gui: str
    proof_artifacts: List[str]
    prompt_id: str
    prompt_text: str
    severity: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProofArtifact:
    source: str
    public_url: str
    media_type: str
    sha256: Optional[str]


class ConfigLoader:
    """Loads and validates YAML config."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            raise ConfigError(f"Config file not found: {self.path}")

        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigError("Config root must be a mapping")

        prompts = self._parse_prompts(raw.get("prompts", []))
        runtime = self._parse_runtime(raw.get("runtime", {}))
        proof = self._parse_proof(raw.get("proof", {}))
        submission = self._parse_submission(raw.get("submission", {}))
        repositories = self._parse_repositories(raw.get("repositories", []), submission.issue_repo)

        external = raw.get("external_dedup", {}) or {}
        external_repo = external.get("repo", DEFAULT_EXTERNAL_REPO)
        external_token_env = external.get("token_env")

        if len(repositories) != 6:
            raise ConfigError("Exactly 6 repositories must be configured")

        return AppConfig(
            prompts=prompts,
            repositories=repositories,
            runtime=runtime,
            proof=proof,
            submission=submission,
            external_dedup_repo=external_repo,
            external_dedup_token_env=external_token_env,
        )

    def _parse_prompts(self, raw_prompts: Any) -> List[PromptConfig]:
        if not isinstance(raw_prompts, list) or not raw_prompts:
            raise ConfigError("prompts must be a non-empty list")

        prompts: List[PromptConfig] = []
        for item in raw_prompts:
            if not isinstance(item, dict):
                raise ConfigError("Each prompt entry must be a mapping")
            prompt_id = str(item.get("id", "")).strip()
            prompt_text = str(item.get("prompt", "")).strip()
            detector_cmd = str(item.get("detector_cmd", "")).strip()
            severity = str(item.get("severity", "medium")).strip().lower() or "medium"
            if not prompt_id or not prompt_text or not detector_cmd:
                raise ConfigError("Prompt entries require id, prompt, and detector_cmd")
            prompts.append(
                PromptConfig(
                    id=prompt_id,
                    prompt=prompt_text,
                    detector_cmd=detector_cmd,
                    severity=severity,
                )
            )
        return prompts

    def _parse_repositories(self, raw_repos: Any, default_issue_repo: str) -> List[RepoConfig]:
        if not isinstance(raw_repos, list) or not raw_repos:
            raise ConfigError("repositories must be a non-empty list")

        issue_parts = default_issue_repo.split("/", 1)
        if len(issue_parts) != 2 or not issue_parts[0].strip() or not issue_parts[1].strip():
            raise ConfigError("submission.issue_repo must be in 'owner/repo' format")
        default_owner = issue_parts[0].strip()
        default_repo = issue_parts[1].strip()

        parsed: List[RepoConfig] = []
        for entry in raw_repos:
            if not isinstance(entry, dict):
                raise ConfigError("Each repository entry must be a mapping")

            github_name = str(entry.get("github_name", "")).strip()
            if not github_name:
                raise ConfigError("Repository entries require github_name (submitter identity)")

            issue_repo = str(entry.get("issue_repo", "")).strip()
            owner = str(entry.get("owner", "")).strip()
            repo_name = str(entry.get("repo", "")).strip()

            if issue_repo:
                parts = issue_repo.split("/", 1)
                if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                    raise ConfigError(
                        "issue_repo must be in 'owner/repo' format "
                        f"(got: {issue_repo!r})"
                    )
                owner = parts[0].strip()
                repo_name = parts[1].strip()
            elif owner and repo_name:
                pass
            elif "/" in github_name:
                # Backward compatibility: old style used github_name as owner/repo.
                parts = github_name.split("/", 1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    owner = parts[0].strip()
                    repo_name = parts[1].strip()
                else:
                    owner = default_owner
                    repo_name = default_repo
            else:
                owner = default_owner
                repo_name = default_repo

            name = str(entry.get("name", "")).strip() or github_name
            token = str(entry.get("token", "")).strip() or str(entry.get("token_env", "")).strip()
            labels = entry.get("labels", []) or []
            if not owner or not repo_name or not token:
                raise ConfigError(
                    "Repository entries require github_name and token "
                    "(optional override: issue_repo)"
                )
            if not isinstance(labels, list):
                raise ConfigError(f"labels must be a list for repository {name}")
            issue_template = entry.get("issue_template")
            if issue_template is not None:
                issue_template = str(issue_template)
            parsed.append(
                RepoConfig(
                    github_name=github_name,
                    name=name,
                    owner=owner,
                    repo=repo_name,
                    token=token,
                    labels=[str(x) for x in labels],
                    issue_template=issue_template,
                )
            )
        return parsed

    def _parse_runtime(self, raw_runtime: Any) -> RuntimeConfig:
        if not isinstance(raw_runtime, dict):
            raise ConfigError("runtime must be a mapping")
        state_dir = Path(str(raw_runtime.get("state_dir", ".audit_state"))).expanduser().resolve()
        poll = int(raw_runtime.get("poll_interval_seconds", DEFAULT_POLL_SECONDS))
        target = int(raw_runtime.get("valid_target_per_repo", DEFAULT_DAILY_VALID_TARGET))
        stop_when_done = bool(raw_runtime.get("stop_when_targets_met", True))

        return RuntimeConfig(
            state_dir=state_dir,
            dedup_db=state_dir / "local_dedup.sqlite3",
            daily_state_file=state_dir / "daily_state.json",
            summary_file=state_dir / "daily_summary.json",
            clone_root=state_dir / "clones",
            poll_interval_seconds=max(10, poll),
            valid_target_per_repo=max(1, target),
            stop_when_targets_met=stop_when_done,
        )

    def _parse_proof(self, raw_proof: Any) -> ProofConfig:
        if not isinstance(raw_proof, dict):
            raise ConfigError("proof must be a mapping")

        image_ext = raw_proof.get("allowed_image_extensions", [".png", ".jpg", ".jpeg"])
        video_ext = raw_proof.get("allowed_video_extensions", [".mp4", ".mov", ".webm"])
        if not isinstance(image_ext, list) or not isinstance(video_ext, list):
            raise ConfigError("proof extension lists must be arrays")

        upload_cmd = raw_proof.get("upload_cmd")
        if upload_cmd is not None:
            upload_cmd = str(upload_cmd).strip() or None
        auto_capture_cmd = raw_proof.get("auto_capture_cmd")
        if auto_capture_cmd is not None:
            auto_capture_cmd = str(auto_capture_cmd).strip() or None

        screenshot_example_url = str(
            raw_proof.get(
                "screenshot_example_url",
                "https://github.com/PlatformNetwork/bounty-challenge/issues/22537",
            )
        )
        video_example_url = str(
            raw_proof.get(
                "video_example_url",
                "https://github.com/PlatformNetwork/bounty-challenge/issues/22534",
            )
        )
        banned_format_url = str(
            raw_proof.get(
                "banned_format_url",
                "https://github.com/PlatformNetwork/bounty-challenge/issues/22375#issuecomment-3983776205",
            )
        )

        return ProofConfig(
            allowed_image_extensions=[str(x).lower() for x in image_ext],
            allowed_video_extensions=[str(x).lower() for x in video_ext],
            upload_cmd=upload_cmd,
            auto_capture_cmd=auto_capture_cmd,
            screenshot_example_url=screenshot_example_url,
            video_example_url=video_example_url,
            banned_format_url=banned_format_url,
        )

    def _parse_submission(self, raw_submission: Any) -> SubmissionConfig:
        if raw_submission is None:
            raw_submission = {}
        if not isinstance(raw_submission, dict):
            raise ConfigError("submission must be a mapping")
        title_template = str(
            raw_submission.get("title_template", "[Bug][alpha]{title}")
        ).strip()
        issue_repo = str(raw_submission.get("issue_repo", DEFAULT_EXTERNAL_REPO)).strip()
        if not title_template:
            raise ConfigError("submission.title_template cannot be empty")
        if "{title}" not in title_template:
            raise ConfigError("submission.title_template must contain {title}")
        if "/" not in issue_repo:
            raise ConfigError("submission.issue_repo must be in 'owner/repo' format")
        return SubmissionConfig(title_template=title_template, issue_repo=issue_repo)


class ConfigReloader:
    """Hot-reloads config when YAML file changes."""

    def __init__(self, config_path: Path):
        self._path = config_path
        self._loader = ConfigLoader(config_path)
        self._last_mtime_ns: Optional[int] = None
        self._cached: Optional[AppConfig] = None

    def get(self) -> Tuple[AppConfig, bool]:
        mtime_ns = self._path.stat().st_mtime_ns
        changed = self._cached is None or self._last_mtime_ns != mtime_ns
        if changed:
            self._cached = self._loader.load()
            self._last_mtime_ns = mtime_ns
        return copy.deepcopy(self._cached), changed


class GitHubClient:
    """Small wrapper around GitHub REST API."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHub token is required")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "audit-bot/1.0",
            }
        )

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = path_or_url if path_or_url.startswith("http") else f"{GITHUB_API_BASE}{path_or_url}"
        response = self._session.request(method, url, params=params, json=json_body, timeout=30)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API error {response.status_code} for {url}: {response.text[:400]}"
            )
        if response.status_code == 204:
            return None
        return response.json()

    def search_issues(self, query: str, per_page: int = 10) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/search/issues",
            params={"q": query, "per_page": per_page},
        )

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = list(labels)
        return self.request("POST", f"/repos/{owner}/{repo}/issues", json_body=payload)

    def get_issue(self, owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
        return self.request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    def list_directory(self, owner: str, repo: str, path: str) -> List[Dict[str, Any]]:
        try:
            payload = self.request("GET", f"/repos/{owner}/{repo}/contents/{path}")
        except GitHubAPIError as exc:
            if "404" in str(exc):
                return []
            raise
        if isinstance(payload, list):
            return payload
        return [payload]

    def download_raw(self, url: str) -> str:
        response = self._session.get(url, timeout=30)
        if response.status_code >= 400:
            raise GitHubAPIError(f"Failed to download template from {url}: {response.status_code}")
        return response.text


class CodebaseManager:
    """Clones or refreshes the target codebase before each audit run."""

    def __init__(self, clone_root: Path):
        self._clone_root = clone_root
        ensure_dir(self._clone_root)

    def prepare(self, source: str) -> Path:
        if is_git_url(source):
            return self._prepare_clone(source)
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        return source_path

    def _prepare_clone(self, source_url: str) -> Path:
        key = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:12]
        clone_path = self._clone_root / key
        if not clone_path.exists():
            self._run(["git", "clone", source_url, str(clone_path)])
            return clone_path

        self._run(["git", "-C", str(clone_path), "fetch", "--all", "--prune"])
        self._run(["git", "-C", str(clone_path), "pull", "--ff-only"])
        return clone_path

    def _run(self, cmd: Sequence[str]) -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({' '.join(cmd)}):\nstdout={proc.stdout}\nstderr={proc.stderr}"
            )


class DetectorRunner:
    """Executes prompt-specific detector commands and parses candidate findings."""

    def run(self, prompts: Sequence[PromptConfig], repo_path: Path) -> List[BugCandidate]:
        findings: List[BugCandidate] = []
        for prompt in prompts:
            items = self._run_prompt(prompt, repo_path)
            findings.extend(items)
        return findings

    def _run_prompt(self, prompt: PromptConfig, repo_path: Path) -> List[BugCandidate]:
        env = os.environ.copy()
        env["AUDIT_PROMPT_TEXT"] = prompt.prompt
        env["AUDIT_PROMPT_ID"] = prompt.id
        env["AUDIT_REPO_PATH"] = str(repo_path)

        cmd = prompt.detector_cmd.format(
            repo_path=str(repo_path),
            prompt_id=prompt.id,
            prompt=prompt.prompt,
        )
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            print(f"[detector] prompt={prompt.id} failed: {proc.stderr.strip()}")
            return []

        stdout = proc.stdout.strip()
        if not stdout:
            return []

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            print(f"[detector] prompt={prompt.id} invalid JSON output: {exc}")
            return []

        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            print(f"[detector] prompt={prompt.id} output must be JSON object/list")
            return []

        candidates: List[BugCandidate] = []
        for item in payload:
            try:
                candidates.append(self._to_candidate(item, prompt))
            except ConfigError as exc:
                print(f"[detector] prompt={prompt.id} invalid candidate: {exc}")
        return candidates

    def _to_candidate(self, item: Any, prompt: PromptConfig) -> BugCandidate:
        if not isinstance(item, dict):
            raise ConfigError("candidate must be a mapping")

        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        impact = str(item.get("impact", "")).strip()
        native_gui = str(item.get("native_gui", "")).strip()
        proof_artifacts = item.get("proof_artifacts", [])
        reproduction_steps = item.get("reproduction_steps", [])

        if isinstance(reproduction_steps, str):
            reproduction_steps = [reproduction_steps]
        if not isinstance(reproduction_steps, list):
            raise ConfigError("reproduction_steps must be a list or string")

        if not isinstance(proof_artifacts, list):
            raise ConfigError("proof_artifacts must be a list")

        if not title or not description or not impact or not native_gui:
            raise ConfigError("candidate requires title, description, impact, and native_gui")

        steps = [str(x).strip() for x in reproduction_steps if str(x).strip()]
        if not steps:
            raise ConfigError("candidate reproduction_steps cannot be empty")

        return BugCandidate(
            title=title,
            description=description,
            reproduction_steps=steps,
            impact=impact,
            native_gui=native_gui,
            proof_artifacts=[str(x).strip() for x in proof_artifacts if str(x).strip()],
            prompt_id=prompt.id,
            prompt_text=prompt.prompt,
            severity=prompt.severity,
            raw=item,
        )


class LocalDedupStore:
    """SQLite-backed dedup store with reservation semantics for parallel agents."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        ensure_dir(self._db_path.parent)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bug_log (
                    fingerprint TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt_id TEXT,
                    source_repo TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    issue_repo TEXT,
                    issue_number INTEGER,
                    issue_url TEXT,
                    note TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bug_log_status ON bug_log(status)
                """
            )

    def try_reserve(self, fingerprint: str, candidate: BugCandidate, source_repo: str) -> bool:
        now = utc_now()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO bug_log (
                        fingerprint, status, title, prompt_id, source_repo,
                        created_at, updated_at
                    ) VALUES (?, 'reserved', ?, ?, ?, ?, ?)
                    """,
                    (
                        fingerprint,
                        candidate.title,
                        candidate.prompt_id,
                        source_repo,
                        now,
                        now,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT status, COALESCE(note, '')
                    FROM bug_log
                    WHERE fingerprint = ?
                    """,
                    (fingerprint,),
                ).fetchone()
                if not row:
                    return False

                status, note = str(row[0]), str(row[1])
                retryable = (
                    status == "skipped"
                    and (
                        note.startswith("proof_validation_failed:")
                        or note.startswith("issue_submit_failed:")
                        or note.startswith("external_dedup_error:")
                    )
                )
                if not retryable:
                    return False

                conn.execute(
                    """
                    UPDATE bug_log
                    SET status = 'reserved', note = 'retrying', updated_at = ?
                    WHERE fingerprint = ?
                    """,
                    (now, fingerprint),
                )
                return True

    def mark_skipped(self, fingerprint: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE bug_log
                SET status = 'skipped', note = ?, updated_at = ?
                WHERE fingerprint = ?
                """,
                (reason, utc_now(), fingerprint),
            )

    def mark_submitted(
        self,
        fingerprint: str,
        issue_repo: str,
        issue_number: int,
        issue_url: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE bug_log
                SET status = 'submitted', issue_repo = ?, issue_number = ?, issue_url = ?, updated_at = ?
                WHERE fingerprint = ?
                """,
                (issue_repo, issue_number, issue_url, utc_now(), fingerprint),
            )


class ExternalDedupChecker:
    """Checks the external bounty-challenge issue tracker for duplicates."""

    def __init__(self, github_client: GitHubClient, repository: str) -> None:
        self._client = github_client
        self._repository = repository

    def is_duplicate(self, candidate: BugCandidate, fingerprint: str) -> Tuple[bool, Optional[str]]:
        title_query = f'repo:{self._repository} is:issue "{candidate.title}"'
        if self._has_match(title_query):
            issue_url = self._first_issue_url(title_query)
            return True, issue_url

        fp_prefix = fingerprint[:16]
        fp_query = f'repo:{self._repository} is:issue "{fp_prefix}"'
        if self._has_match(fp_query):
            issue_url = self._first_issue_url(fp_query)
            return True, issue_url

        return False, None

    def _has_match(self, query: str) -> bool:
        results = self._client.search_issues(query, per_page=1)
        return int(results.get("total_count", 0)) > 0

    def _first_issue_url(self, query: str) -> Optional[str]:
        results = self._client.search_issues(query, per_page=1)
        items = results.get("items", [])
        if items:
            return items[0].get("html_url")
        return None


class ProofManager:
    """Validates and prepares screenshot/video proof artifacts."""

    def __init__(self, proof_config: ProofConfig, state_dir: Path):
        self._proof_config = proof_config
        self._proof_manifest_path = state_dir / "proof_manifest.jsonl"
        ensure_dir(self._proof_manifest_path.parent)

    def prepare(
        self,
        candidate: BugCandidate,
        fingerprint: str,
        source_repo: Path,
    ) -> List[ProofArtifact]:
        if not candidate.native_gui:
            raise ValueError("native_gui is required for proof validation")

        if not candidate.proof_artifacts:
            generated = self._auto_capture(candidate, fingerprint, source_repo)
            if generated:
                candidate.proof_artifacts = generated
            else:
                raise ValueError(
                    "No proof_artifacts provided. Attach native GUI screenshot/video "
                    "before submission."
                )

        artifacts: List[ProofArtifact] = []
        for artifact_ref in candidate.proof_artifacts:
            artifact = self._prepare_single_artifact(artifact_ref)
            artifacts.append(artifact)

        self._append_manifest(candidate, fingerprint, artifacts)
        return artifacts

    def _auto_capture(
        self,
        candidate: BugCandidate,
        fingerprint: str,
        source_repo: Path,
    ) -> List[str]:
        if not self._proof_config.auto_capture_cmd:
            return []

        finding_id = str(candidate.raw.get("finding_id", "")).strip() or fingerprint[:16]
        evidence_file = str(candidate.raw.get("evidence_file", "")).strip()
        evidence_line = str(candidate.raw.get("evidence_line", "")).strip()
        cmd = self._proof_config.auto_capture_cmd.format(
            repo_path=shlex.quote(str(source_repo)),
            finding_id=shlex.quote(finding_id),
            evidence_file=shlex.quote(evidence_file),
            evidence_line=evidence_line or "1",
            title=shlex.quote(candidate.title),
        )
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            print(
                f"[proof] auto-capture failed for '{candidate.title}': "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
            return []

        outputs: List[str] = []
        for line in proc.stdout.splitlines():
            value = line.strip()
            if not value:
                continue
            if value.startswith("http://") or value.startswith("https://"):
                outputs.append(value)
                continue
            local = Path(value).expanduser().resolve()
            if local.exists() and local.is_file():
                outputs.append(str(local))

        if outputs:
            print(
                f"[proof] auto-captured {len(outputs)} artifact(s) for '{candidate.title}'"
            )
        return outputs

    def _prepare_single_artifact(self, artifact_ref: str) -> ProofArtifact:
        parsed = urlparse(artifact_ref)
        if parsed.scheme in {"http", "https"}:
            ext = Path(parsed.path).suffix.lower()
            media_type = self._extension_to_media_type(ext)
            return ProofArtifact(
                source=artifact_ref,
                public_url=artifact_ref,
                media_type=media_type,
                sha256=None,
            )

        local_path = Path(artifact_ref).expanduser().resolve()
        if not local_path.exists() or not local_path.is_file():
            raise ValueError(f"Proof artifact file does not exist: {artifact_ref}")

        ext = local_path.suffix.lower()
        media_type = self._extension_to_media_type(ext)
        guessed_type = mimetypes.guess_type(str(local_path))[0] or ""
        if media_type == "image" and not guessed_type.startswith("image/"):
            raise ValueError(f"File is not a valid image: {artifact_ref}")
        if media_type == "video" and not guessed_type.startswith("video/"):
            raise ValueError(f"File is not a valid video: {artifact_ref}")

        if not self._proof_config.upload_cmd:
            raise ValueError(
                "Local artifact provided but proof.upload_cmd is not configured. "
                "Use URL artifacts or configure upload_cmd."
            )

        public_url = self._upload_artifact(local_path)
        return ProofArtifact(
            source=str(local_path),
            public_url=public_url,
            media_type=media_type,
            sha256=sha256_file(local_path),
        )

    def _upload_artifact(self, artifact_path: Path) -> str:
        cmd = self._proof_config.upload_cmd.format(file_path=shlex.quote(str(artifact_path)))
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError(f"Artifact upload failed: {proc.stderr.strip()}")
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("http://") or line.startswith("https://"):
                return line
        raise ValueError("upload_cmd did not return a URL on stdout")

    def _extension_to_media_type(self, extension: str) -> str:
        if extension in self._proof_config.allowed_image_extensions:
            return "image"
        if extension in self._proof_config.allowed_video_extensions:
            return "video"
        raise ValueError(f"Unsupported proof artifact extension: {extension}")

    def _append_manifest(
        self,
        candidate: BugCandidate,
        fingerprint: str,
        artifacts: Sequence[ProofArtifact],
    ) -> None:
        payload = {
            "timestamp": utc_now(),
            "fingerprint": fingerprint,
            "title": candidate.title,
            "native_gui": candidate.native_gui,
            "artifacts": [
                {
                    "source": x.source,
                    "public_url": x.public_url,
                    "media_type": x.media_type,
                    "sha256": x.sha256,
                }
                for x in artifacts
            ],
        }
        with self._proof_manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")


@dataclass
class TemplateSpec:
    source: str
    sections: List[str]


class IssueTemplateManager:
    """Loads per-repository issue template requirements from GitHub."""

    def __init__(self) -> None:
        self._cache: Dict[str, TemplateSpec] = {}

    def resolve(self, repo_cfg: RepoConfig, client: GitHubClient) -> TemplateSpec:
        if repo_cfg.name in self._cache:
            return self._cache[repo_cfg.name]

        if repo_cfg.issue_template:
            spec = TemplateSpec(source="config", sections=self._parse_sections(repo_cfg.issue_template))
            self._cache[repo_cfg.name] = spec
            return spec

        entries = client.list_directory(repo_cfg.owner, repo_cfg.repo, ".github/ISSUE_TEMPLATE")
        markdown_templates = [
            x for x in entries if x.get("type") == "file" and str(x.get("name", "")).endswith(".md")
        ]
        yaml_templates = [
            x
            for x in entries
            if x.get("type") == "file"
            and (
                str(x.get("name", "")).endswith(".yml")
                or str(x.get("name", "")).endswith(".yaml")
            )
        ]

        if markdown_templates:
            raw = client.download_raw(markdown_templates[0]["download_url"])
            sections = self._parse_sections(raw)
            spec = TemplateSpec(source=markdown_templates[0]["name"], sections=sections)
            self._cache[repo_cfg.name] = spec
            return spec

        if yaml_templates:
            raw = client.download_raw(yaml_templates[0]["download_url"])
            sections = self._parse_issue_form_sections(raw)
            spec = TemplateSpec(source=yaml_templates[0]["name"], sections=sections)
            self._cache[repo_cfg.name] = spec
            return spec

        spec = TemplateSpec(source="default", sections=[])
        self._cache[repo_cfg.name] = spec
        return spec

    def _parse_sections(self, text: str) -> List[str]:
        sections: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                header = stripped[4:].strip()
                if header:
                    sections.append(header)
        return sections

    def _parse_issue_form_sections(self, text: str) -> List[str]:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            return []
        if not isinstance(parsed, dict):
            return []

        sections: List[str] = []
        body = parsed.get("body", [])
        if not isinstance(body, list):
            return sections

        for item in body:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes", {})
            if isinstance(attrs, dict):
                label = attrs.get("label")
                if isinstance(label, str) and label.strip():
                    sections.append(label.strip())
        return sections


class DailyState:
    """Tracks daily issue submissions and valid/invalid counts per repo."""

    def __init__(self, state_file: Path, summary_file: Path, repo_names: Sequence[str]):
        self._state_file = state_file
        self._summary_file = summary_file
        self._repo_names = list(repo_names)
        ensure_dir(self._state_file.parent)

        self.date = today_str()
        self.next_repo_index = 0
        self.repos: Dict[str, Dict[str, Any]] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        if not self._state_file.exists():
            self._reset(today_str())
            self.save()
            return

        try:
            payload = json_load(self._state_file)
        except json.JSONDecodeError:
            self._reset(today_str())
            self.save()
            return

        current_day = today_str()
        stored_day = str(payload.get("date", current_day))
        if stored_day != current_day:
            self._archive_day(payload)
            self._reset(current_day)
            self.save()
            return

        self.date = stored_day
        self.next_repo_index = int(payload.get("next_repo_index", 0))
        self.repos = payload.get("repos", {}) if isinstance(payload.get("repos", {}), dict) else {}
        for name in self._repo_names:
            self.repos.setdefault(name, {"submitted": []})

    def _archive_day(self, payload: Dict[str, Any]) -> None:
        archive_dir = self._summary_file.parent / "history"
        ensure_dir(archive_dir)
        archive_path = archive_dir / f"{payload.get('date', 'unknown')}.json"
        json_dump(archive_path, payload)

    def _reset(self, date_str: str) -> None:
        self.date = date_str
        self.next_repo_index = 0
        self.repos = {name: {"submitted": []} for name in self._repo_names}

    def rollover_if_needed(self) -> None:
        current_day = today_str()
        if self.date != current_day:
            self._archive_day(
                {
                    "date": self.date,
                    "next_repo_index": self.next_repo_index,
                    "repos": self.repos,
                }
            )
            self._reset(current_day)
            self.save()

    def save(self) -> None:
        payload = {
            "date": self.date,
            "next_repo_index": self.next_repo_index,
            "repos": self.repos,
            "updated_at": utc_now(),
        }
        json_dump(self._state_file, payload)

    def choose_repo(self, target_valid_count: int) -> Optional[str]:
        if not self._repo_names:
            return None

        total = len(self._repo_names)
        for offset in range(total):
            idx = (self.next_repo_index + offset) % total
            name = self._repo_names[idx]
            if self.valid_count(name) < target_valid_count:
                self.next_repo_index = (idx + 1) % total
                return name
        return None

    def record_submission(self, repo_name: str, issue_number: int, issue_url: str, fingerprint: str) -> None:
        entry = {
            "number": int(issue_number),
            "url": issue_url,
            "fingerprint": fingerprint,
            "invalid": False,
            "labels": [],
            "updated_at": utc_now(),
        }
        self.repos.setdefault(repo_name, {"submitted": []})
        self.repos[repo_name]["submitted"].append(entry)

    def sync_invalid_labels(
        self,
        repo_cfgs: Sequence[RepoConfig],
        clients: Dict[str, GitHubClient],
        invalid_labels: Iterable[str],
    ) -> None:
        invalid_set = {x.lower() for x in invalid_labels}
        for repo_cfg in repo_cfgs:
            submitted = self.repos.get(repo_cfg.name, {}).get("submitted", [])
            if not submitted:
                continue

            client = clients[repo_cfg.name]
            for issue in submitted:
                number = int(issue["number"])
                payload = client.get_issue(repo_cfg.owner, repo_cfg.repo, number)
                labels = [str(label.get("name", "")).lower() for label in payload.get("labels", [])]
                issue["labels"] = labels
                issue["invalid"] = any(label in invalid_set for label in labels)
                issue["updated_at"] = utc_now()

    def total_count(self, repo_name: str) -> int:
        return len(self.repos.get(repo_name, {}).get("submitted", []))

    def invalid_count(self, repo_name: str) -> int:
        submitted = self.repos.get(repo_name, {}).get("submitted", [])
        return sum(1 for item in submitted if item.get("invalid"))

    def valid_count(self, repo_name: str) -> int:
        return self.total_count(repo_name) - self.invalid_count(repo_name)

    def all_targets_met(self, target_valid_count: int) -> bool:
        return all(self.valid_count(name) >= target_valid_count for name in self._repo_names)

    def build_summary(self, target_valid_count: int) -> Dict[str, Any]:
        repo_summary: Dict[str, Any] = {}
        for name in self._repo_names:
            total = self.total_count(name)
            invalid = self.invalid_count(name)
            valid = total - invalid
            repo_summary[name] = {
                "total_submitted": total,
                "invalid": invalid,
                "valid": valid,
                "target": target_valid_count,
                "remaining_to_target": max(0, target_valid_count - valid),
            }

        return {
            "date": self.date,
            "updated_at": utc_now(),
            "repositories": repo_summary,
        }

    def save_summary(self, target_valid_count: int) -> None:
        json_dump(self._summary_file, self.build_summary(target_valid_count))


def compute_fingerprint(candidate: BugCandidate) -> str:
    explicit = normalize_text(str(candidate.raw.get("fingerprint", "")))
    if explicit:
        return hashlib.sha256(explicit.encode("utf-8")).hexdigest()

    core = "|".join(
        [
            normalize_text(candidate.title),
            normalize_text(candidate.description),
            normalize_text("\n".join(candidate.reproduction_steps)),
            normalize_text(candidate.impact),
            normalize_text(candidate.native_gui),
            normalize_text(candidate.prompt_id),
        ]
    )
    return hashlib.sha256(core.encode("utf-8")).hexdigest()


def format_issue_title(raw_title: str, title_template: str) -> str:
    title = raw_title.strip()
    if not title:
        return title_template.replace("{title}", "Untitled bug")

    prefix = title_template.split("{title}", 1)[0]
    if prefix and title.lower().startswith(prefix.lower()):
        return title
    return title_template.replace("{title}", title)


def render_proof_section(artifacts: Sequence[ProofArtifact], native_gui: str) -> str:
    lines = [
        f"Native GUI: {native_gui}",
        "Artifacts are raw captures of the observed bug behavior with no visual edits.",
        "",
    ]
    for artifact in artifacts:
        if artifact.media_type == "image":
            lines.append(f"Screenshot URL: {artifact.public_url}")
            lines.append(f"![Screenshot proof]({artifact.public_url})")
            lines.append("")
        else:
            lines.append(f"Video URL: {artifact.public_url}")
            lines.append(f"[View video proof]({artifact.public_url})")
            lines.append(f'<video src="{artifact.public_url}" controls></video>')
            lines.append("")
    return "\n".join(lines)


def render_issue_body(
    candidate: BugCandidate,
    fingerprint: str,
    artifacts: Sequence[ProofArtifact],
    template: TemplateSpec,
    external_repo: str,
    proof_cfg: ProofConfig,
) -> str:
    proof_section = render_proof_section(artifacts, candidate.native_gui)

    steps_text = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(candidate.reproduction_steps))
    actual_behavior = str(candidate.raw.get("actual_behavior", "")).strip() or candidate.description
    expected_behavior = (
        str(candidate.raw.get("expected_behavior", "")).strip()
        or "Feature should route data and actions to the intended target and display accurate metadata."
    )
    project_name = str(candidate.raw.get("project", "")).strip() or "cortex-ide"
    error_message = (
        str(candidate.raw.get("error_message", "")).strip()
        or "No explicit runtime error message is shown in the UI."
    )
    debug_logs = (
        str(candidate.raw.get("debug_logs", "")).strip()
        or "No debug logs were captured for this reproduction."
    )
    system_information = (
        str(candidate.raw.get("system_information", "")).strip()
        or f"Native GUI: {candidate.native_gui}"
    )
    additional_context = str(candidate.raw.get("additional_context", "")).strip() or (
        f"Impact: {candidate.impact}\n\n"
        f"Local fingerprint: `{fingerprint}`\n"
        f"External duplicate check repository: `{external_repo}`"
    )

    section_map = {
        "project": project_name,
        "summary": candidate.description,
        "bug summary": candidate.description,
        "description": candidate.description,
        "error message": error_message,
        "debug logs": debug_logs,
        "system information": system_information,
        "system info": system_information,
        "impact": candidate.impact,
        "severity": candidate.severity,
        "reproduction steps": steps_text,
        "steps to reproduce": steps_text,
        "expected behavior": expected_behavior,
        "actual behavior": actual_behavior,
        "additional context": additional_context,
        "proof": proof_section,
        "proof of bug": proof_section,
        "screenshots": proof_section,
        "deduplication": additional_context,
        "detector prompt": candidate.prompt_text,
        "prompt": candidate.prompt_text,
    }

    if not template.sections:
        return "\n".join(
            [
                "### Project",
                project_name,
                "",
                "### Description",
                candidate.description,
                "",
                "### Error Message",
                error_message,
                "",
                "### Debug Logs",
                debug_logs,
                "",
                "### System Information",
                system_information,
                "",
                "### Screenshots",
                proof_section,
                "",
                "### Steps to Reproduce",
                steps_text,
                "",
                "### Expected Behavior",
                expected_behavior,
                "",
                "### Actual Behavior",
                actual_behavior,
                "",
                "### Additional Context",
                additional_context,
            ]
        )

    output_lines: List[str] = []
    for section in template.sections:
        lowered = section.strip().lower()
        if "proof format reference" in lowered:
            continue
        content = section_map.get(lowered)
        if content is None:
            if "project" in lowered:
                content = project_name
            elif "description" in lowered or "summary" in lowered:
                content = candidate.description
            elif "error" in lowered:
                content = error_message
            elif "debug" in lowered or "log" in lowered:
                content = debug_logs
            elif "system" in lowered:
                content = system_information
            elif "expected" in lowered:
                content = expected_behavior
            elif "actual" in lowered:
                content = actual_behavior
            elif "additional" in lowered or "context" in lowered:
                content = additional_context
            elif "impact" in lowered:
                content = candidate.impact
            elif "step" in lowered or "repro" in lowered:
                content = steps_text
            elif "proof" in lowered or "video" in lowered or "screenshot" in lowered:
                content = proof_section
            elif "prompt" in lowered:
                content = candidate.prompt_text
            elif "dedup" in lowered:
                content = additional_context
            else:
                content = "N/A"
        output_lines.append(f"### {section}")
        output_lines.append(content)
        output_lines.append("")
    return "\n".join(output_lines)


class AuditOrchestrator:
    """Main workflow orchestration."""

    def __init__(self, config_path: Path, source: str, once: bool = False) -> None:
        self._config_reloader = ConfigReloader(config_path)
        self._source = source
        self._once = once

        self._config: Optional[AppConfig] = None
        self._codebase_manager: Optional[CodebaseManager] = None
        self._detector_runner = DetectorRunner()
        self._dedup_store: Optional[LocalDedupStore] = None
        self._proof_manager: Optional[ProofManager] = None
        self._daily_state: Optional[DailyState] = None
        self._template_manager = IssueTemplateManager()

        self._repo_cfgs: List[RepoConfig] = []
        self._clients: Dict[str, GitHubClient] = {}
        self._external_checker: Optional[ExternalDedupChecker] = None

    def run(self) -> None:
        while True:
            config, changed = self._config_reloader.get()
            if changed or self._config is None:
                self._apply_config(config)
                print("[config] Reloaded configuration")

            self._daily_state.rollover_if_needed()
            self._daily_state.sync_invalid_labels(self._repo_cfgs, self._clients, INVALID_LABELS)
            self._daily_state.save()
            self._daily_state.save_summary(self._config.runtime.valid_target_per_repo)

            if self._daily_state.all_targets_met(self._config.runtime.valid_target_per_repo):
                print("[status] Daily valid issue targets reached for all repositories")
                if self._once or self._config.runtime.stop_when_targets_met:
                    break
                time.sleep(self._config.runtime.poll_interval_seconds)
                continue

            source_path = self._codebase_manager.prepare(self._source)
            candidates = self._detector_runner.run(self._config.prompts, source_path)
            print(f"[audit] detector produced {len(candidates)} candidate(s)")

            submissions = self._process_candidates(candidates, source_path)
            print(f"[audit] submitted {submissions} issue(s) this cycle")

            self._daily_state.sync_invalid_labels(self._repo_cfgs, self._clients, INVALID_LABELS)
            self._daily_state.save()
            self._daily_state.save_summary(self._config.runtime.valid_target_per_repo)

            if self._once:
                break

            if submissions == 0:
                time.sleep(self._config.runtime.poll_interval_seconds)

    def _apply_config(self, config: AppConfig) -> None:
        self._config = config
        ensure_dir(config.runtime.state_dir)
        ensure_dir(config.runtime.clone_root)

        self._codebase_manager = CodebaseManager(config.runtime.clone_root)
        self._dedup_store = LocalDedupStore(config.runtime.dedup_db)
        self._proof_manager = ProofManager(config.proof, config.runtime.state_dir)

        self._repo_cfgs = config.repositories
        self._clients = {}
        first_resolved_token = ""
        for repo_cfg in self._repo_cfgs:
            token = os.environ.get(repo_cfg.token, "").strip() or repo_cfg.token.strip()
            if not token:
                raise ConfigError(
                    f"Missing token for {repo_cfg.name}. Set environment variable "
                    f"{repo_cfg.token} or provide a literal token."
                )
            self._clients[repo_cfg.name] = GitHubClient(token)
            if not first_resolved_token:
                first_resolved_token = token

        # Provide a default proof upload token for github_repo backend.
        if first_resolved_token and not os.environ.get("PROOF_GH_TOKEN", "").strip():
            os.environ["PROOF_GH_TOKEN"] = first_resolved_token

        external_token = ""
        if config.external_dedup_token_env:
            external_token = os.environ.get(config.external_dedup_token_env, "").strip()
            if looks_like_placeholder_token(external_token):
                external_token = ""
        if not external_token and self._repo_cfgs:
            first_repo_token_ref = self._repo_cfgs[0].token
            external_token = (
                os.environ.get(first_repo_token_ref, "").strip()
                or first_repo_token_ref.strip()
            )
        if not external_token:
            raise ConfigError("Unable to initialize external dedup client: no token available")

        self._external_checker = ExternalDedupChecker(
            GitHubClient(external_token),
            config.external_dedup_repo,
        )

        self._daily_state = DailyState(
            config.runtime.daily_state_file,
            config.runtime.summary_file,
            [repo.name for repo in self._repo_cfgs],
        )

    def _process_candidates(self, candidates: Sequence[BugCandidate], source_path: Path) -> int:
        assert self._config is not None
        assert self._daily_state is not None
        assert self._dedup_store is not None
        assert self._proof_manager is not None
        assert self._external_checker is not None

        submitted = 0
        for candidate in candidates:
            if self._daily_state.all_targets_met(self._config.runtime.valid_target_per_repo):
                break

            fingerprint = compute_fingerprint(candidate)
            reserved = self._dedup_store.try_reserve(
                fingerprint,
                candidate,
                source_repo=str(source_path),
            )
            if not reserved:
                print(f"[audit] skipped '{candidate.title}' due to local dedup")
                continue

            try:
                artifacts = self._proof_manager.prepare(candidate, fingerprint, source_path)
            except Exception as exc:
                print(f"[audit] skipped '{candidate.title}' due to proof validation: {exc}")
                self._dedup_store.mark_skipped(fingerprint, f"proof_validation_failed:{exc}")
                continue

            try:
                duplicate, duplicate_url = self._external_checker.is_duplicate(candidate, fingerprint)
            except Exception as exc:
                print(f"[audit] skipped '{candidate.title}' due to external dedup error: {exc}")
                self._dedup_store.mark_skipped(fingerprint, f"external_dedup_error:{exc}")
                continue

            if duplicate:
                print(
                    f"[audit] skipped '{candidate.title}' due to external duplicate: "
                    f"{duplicate_url or 'match_found'}"
                )
                self._dedup_store.mark_skipped(
                    fingerprint,
                    f"external_duplicate:{duplicate_url or 'match_found'}",
                )
                continue

            repo_name = self._daily_state.choose_repo(self._config.runtime.valid_target_per_repo)
            if not repo_name:
                self._dedup_store.mark_skipped(fingerprint, "daily_target_reached")
                break

            repo_cfg = next(x for x in self._repo_cfgs if x.name == repo_name)
            client = self._clients[repo_name]
            template = self._template_manager.resolve(repo_cfg, client)

            issue_title = format_issue_title(
                candidate.title,
                self._config.submission.title_template,
            )
            issue_body = render_issue_body(
                candidate=candidate,
                fingerprint=fingerprint,
                artifacts=artifacts,
                template=template,
                external_repo=self._config.external_dedup_repo,
                proof_cfg=self._config.proof,
            )

            try:
                issue = client.create_issue(
                    repo_cfg.owner,
                    repo_cfg.repo,
                    issue_title,
                    issue_body,
                    labels=repo_cfg.labels,
                )
            except Exception as exc:
                self._dedup_store.mark_skipped(fingerprint, f"issue_submit_failed:{exc}")
                continue

            issue_number = int(issue["number"])
            issue_url = str(issue["html_url"])
            self._daily_state.record_submission(repo_name, issue_number, issue_url, fingerprint)
            self._dedup_store.mark_submitted(
                fingerprint,
                issue_repo=f"{repo_cfg.owner}/{repo_cfg.repo}",
                issue_number=issue_number,
                issue_url=issue_url,
            )
            submitted += 1

        return submitted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated bug detection and reporting pipeline",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Local codebase path or git clone URL",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    orchestrator = AuditOrchestrator(
        config_path=Path(args.config).expanduser().resolve(),
        source=args.source,
        once=bool(args.once),
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
