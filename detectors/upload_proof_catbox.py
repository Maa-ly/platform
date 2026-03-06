#!/usr/bin/env python3
"""Upload proof artifact and print a public URL.

Default backend: GitHub repo contents API (public raw URL).

Usage (called by bug_audit_system.py):
  python3 ./detectors/upload_proof_catbox.py /abs/path/to/file.png

Optional env vars:
- PROOF_UPLOAD_BACKEND: "github_repo" (default), "github_attachment", or "catbox"
- PROOF_UPLOAD_TIMEOUT: request timeout seconds (default: 120)
- For github_repo backend:
  - PROOF_GH_TOKEN: GitHub token with contents:write
  - PROOF_GH_OWNER: owner/org (optional if PROOF_GH_REPO is owner/repo)
  - PROOF_GH_REPO: repo name or owner/repo (optional when source repo is on GitHub)
  - PROOF_GH_BRANCH: branch name (default: main)
  - PROOF_GH_PATH_PREFIX: path prefix in repo (default: proofs)
  - PROOF_SOURCE_REPO_PATH: source checkout path used to infer owner/repo from git origin
- For github_attachment backend (real github.com/user-attachments links):
  - PROOF_GH_COOKIE or PROOF_GH_COOKIE_FILE: GitHub web session cookie string
  - PROOF_GH_REPO_ID: numeric repository ID (optional if PROOF_GH_REPO can be resolved)
  - PROOF_GH_TOKEN: optional, used to resolve repo ID when PROOF_GH_REPO_ID is absent
- Optional backup:
  - PROOF_GIST_BACKUP=1 to emit a gist backup URL
  - PROOF_GIST_TOKEN (defaults to PROOF_GH_TOKEN)
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests


_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)

_DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "origin": "https://github.com",
    "referer": "https://github.com/",
}

_ATTACHMENT_MIME_BY_EXT = {
    "svg": "image/svg+xml",
    "gif": "image/gif",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "mov": "video/quicktime",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "txt": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "log": "text/plain",
}


def _parse_github_owner_repo(remote_url: str) -> Optional[Tuple[str, str]]:
    text = remote_url.strip()
    if not text:
        return None
    match = _GITHUB_REMOTE_RE.match(text)
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo:
        return None
    return owner, repo


def _find_git_root(start: Path) -> Optional[Path]:
    current = start
    if current.is_file():
        current = current.parent
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _infer_repo_from_path(start: Path) -> Optional[Tuple[str, str]]:
    git_root = _find_git_root(start)
    if git_root is None:
        return None
    proc = subprocess.run(
        ["git", "-C", str(git_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return _parse_github_owner_repo(proc.stdout.strip())


def _resolve_repo_env(path: Path) -> Tuple[str, str]:
    repo_raw = os.environ.get("PROOF_GH_REPO", "").strip()
    owner_raw = os.environ.get("PROOF_GH_OWNER", "").strip()
    if repo_raw:
        if "/" in repo_raw:
            owner, repo = repo_raw.split("/", 1)
            owner = owner.strip()
            repo = repo.strip()
        else:
            owner = owner_raw
            repo = repo_raw
        if owner and repo:
            return owner, repo
        raise RuntimeError("Set PROOF_GH_REPO as owner/repo or provide PROOF_GH_OWNER + PROOF_GH_REPO")

    source_repo_path = os.environ.get("PROOF_SOURCE_REPO_PATH", "").strip()
    infer_candidates = [path]
    if source_repo_path:
        infer_candidates.insert(0, Path(source_repo_path).expanduser().resolve())

    for candidate in infer_candidates:
        inferred = _infer_repo_from_path(candidate)
        if inferred:
            return inferred

    raise RuntimeError(
        "PROOF_GH_REPO is required (or set PROOF_SOURCE_REPO_PATH to a GitHub checkout so owner/repo can be inferred)"
    )


def _resolve_repo_id(path: Path, timeout: int) -> int:
    raw = os.environ.get("PROOF_GH_REPO_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError as exc:
            raise RuntimeError("PROOF_GH_REPO_ID must be an integer") from exc

    owner, repo = _resolve_repo_env(path)
    token = os.environ.get("PROOF_GH_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "algo-platform-proof-uploader/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=headers,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Repo lookup failed {response.status_code} for {owner}/{repo}: {response.text[:220]}"
        )
    payload = response.json()
    repo_id = payload.get("id")
    if not isinstance(repo_id, int):
        raise RuntimeError("Unable to resolve repository id from GitHub API")
    return repo_id


def _resolve_session_cookie() -> str:
    cookie = os.environ.get("PROOF_GH_COOKIE", "").strip()
    if cookie:
        return cookie
    cookie_file = os.environ.get("PROOF_GH_COOKIE_FILE", "").strip()
    if cookie_file:
        text = Path(cookie_file).expanduser().read_text(encoding="utf-8").strip()
        if text:
            return text
    raise RuntimeError("PROOF_GH_COOKIE (or PROOF_GH_COOKIE_FILE) is required for github_attachment backend")


def _resolve_attachment_mime(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in _ATTACHMENT_MIME_BY_EXT:
        return _ATTACHMENT_MIME_BY_EXT[ext]
    guessed = mimetypes.guess_type(str(path))[0]
    if guessed:
        return guessed
    return "application/octet-stream"


def upload_catbox(path: Path, timeout: int) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with path.open("rb") as handle:
                response = requests.post(
                    "https://catbox.moe/user/api.php",
                    data={"reqtype": "fileupload"},
                    files={"fileToUpload": handle},
                    timeout=timeout,
                )
            response.raise_for_status()
            url = response.text.strip()
            if url.startswith("http://") or url.startswith("https://"):
                return url
            raise RuntimeError(f"Uploader did not return a URL: {url[:200]}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
            continue

    raise RuntimeError(str(last_error) if last_error else "Unknown catbox upload failure")


def upload_github_repo(path: Path, timeout: int) -> str:
    token = os.environ.get("PROOF_GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PROOF_GH_TOKEN is required for github_repo backend")

    owner, repo = _resolve_repo_env(path)

    branch = os.environ.get("PROOF_GH_BRANCH", "main").strip() or "main"
    prefix = os.environ.get("PROOF_GH_PATH_PREFIX", "proofs").strip().strip("/")
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    target_name = f"{uuid.uuid4().hex}-{path.name}"
    target_path = f"{prefix}/{today}/{target_name}" if prefix else f"{today}/{target_name}"

    content = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "message": f"Upload proof artifact: {path.name}",
        "content": content,
        "branch": branch,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "algo-platform-proof-uploader/1.0",
    }

    response = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{target_path}",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub upload failed {response.status_code}: {response.text[:300]}")

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{target_path}"
    raw_check = requests.get(raw_url, timeout=timeout)
    if raw_check.status_code >= 400:
        raise RuntimeError(
            "GitHub repo proof URL is not publicly accessible. "
            "Use a public proof repo or switch to PROOF_UPLOAD_BACKEND=github_attachment."
        )
    return raw_url


def upload_github_attachment(path: Path, timeout: int) -> str:
    cookie = _resolve_session_cookie()
    repo_id = _resolve_repo_id(path, timeout)
    content_type = _resolve_attachment_mime(path)
    file_size = path.stat().st_size

    policy_headers = {
        **_DEFAULT_BROWSER_HEADERS,
        "cookie": cookie,
        "GitHub-Verified-Fetch": "true",
        "X-Requested-With": "XMLHttpRequest",
    }
    policy_form = {
        "repository_id": (None, str(repo_id)),
        "name": (None, path.name),
        "size": (None, str(file_size)),
        "content_type": (None, content_type),
    }
    policy_resp = requests.post(
        "https://github.com/upload/policies/assets",
        files=policy_form,
        headers=policy_headers,
        timeout=timeout,
    )
    if policy_resp.status_code >= 400:
        raise RuntimeError(
            f"Attachment policy request failed {policy_resp.status_code}: {policy_resp.text[:300]}"
        )
    policy = policy_resp.json()
    if not isinstance(policy, dict):
        raise RuntimeError("Attachment policy response was not JSON")

    upload_url = str(policy.get("upload_url", "")).strip()
    upload_form = policy.get("form", {})
    if not upload_url or not isinstance(upload_form, dict):
        raise RuntimeError("Attachment policy response missing upload_url/form")

    upload_headers: Dict[str, str] = dict(_DEFAULT_BROWSER_HEADERS)
    upload_headers["cookie"] = cookie
    extra_headers = policy.get("header", {})
    if isinstance(extra_headers, dict):
        for key, value in extra_headers.items():
            if value is None:
                continue
            upload_headers[str(key)] = str(value)
    if policy.get("same_origin") and str(policy.get("upload_authenticity_token", "")).strip():
        upload_headers["authenticity_token"] = str(policy.get("upload_authenticity_token"))

    upload_resp = requests.post(
        upload_url,
        data=upload_form,
        files={"file": (path.name, path.read_bytes(), content_type)},
        headers=upload_headers,
        timeout=timeout,
    )
    if upload_resp.status_code >= 400:
        raise RuntimeError(
            f"Attachment binary upload failed {upload_resp.status_code}: {upload_resp.text[:260]}"
        )

    asset_upload_url = str(policy.get("asset_upload_url", "")).strip()
    asset_auth = str(policy.get("asset_upload_authenticity_token", "")).strip()
    if not asset_upload_url or not asset_auth:
        raise RuntimeError("Attachment policy response missing finalize parameters")
    finalize_url = urljoin("https://github.com/", asset_upload_url)
    finalize_headers = {
        **_DEFAULT_BROWSER_HEADERS,
        "cookie": cookie,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    finalize_resp = requests.put(
        finalize_url,
        files={"authenticity_token": (None, asset_auth)},
        headers=finalize_headers,
        timeout=timeout,
    )
    if finalize_resp.status_code >= 400:
        raise RuntimeError(
            f"Attachment finalize failed {finalize_resp.status_code}: {finalize_resp.text[:260]}"
        )

    asset: Dict[str, Any] = {}
    try:
        payload = finalize_resp.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("asset"), dict):
                asset = payload["asset"]
            else:
                asset = payload
    except Exception:  # noqa: BLE001
        asset = {}
    if not asset:
        raw_asset = policy.get("asset", {})
        if isinstance(raw_asset, dict):
            asset = raw_asset

    href = str(asset.get("href", "")).strip()
    if not href.startswith("https://"):
        raise RuntimeError("Attachment upload did not return an href URL")
    return href


def upload_gist_backup(path: Path, primary_url: str, timeout: int) -> str:
    token = os.environ.get("PROOF_GIST_TOKEN", "").strip() or os.environ.get("PROOF_GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PROOF_GIST_BACKUP=1 requires PROOF_GIST_TOKEN or PROOF_GH_TOKEN")

    is_public = os.environ.get("PROOF_GIST_PUBLIC", "").strip() in {"1", "true", "yes"}
    description = os.environ.get("PROOF_GIST_DESC", "Cortex bug proof backup").strip()
    max_embed = int(os.environ.get("PROOF_GIST_EMBED_MAX_BYTES", "1500000"))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()

    summary_md = (
        "# Evidence Backup\n\n"
        f"- file: `{path.name}`\n"
        f"- size: `{path.stat().st_size}` bytes\n"
        f"- sha256: `{sha}`\n"
        f"- primary url: {primary_url}\n"
    )
    files: Dict[str, Dict[str, str]] = {
        "evidence.md": {"content": summary_md},
    }
    if path.stat().st_size <= max_embed:
        files[f"{path.name}.base64.txt"] = {"content": base64.b64encode(path.read_bytes()).decode("ascii")}

    response = requests.post(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "algo-platform-proof-uploader/1.0",
        },
        json={
            "description": description,
            "public": bool(is_public),
            "files": files,
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gist backup failed {response.status_code}: {response.text[:240]}")

    payload = response.json()
    gist_url = str(payload.get("html_url", "")).strip()
    if not gist_url.startswith("https://gist.github.com/"):
        raise RuntimeError("Gist backup did not return a gist URL")
    return gist_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload proof file and print URL")
    parser.add_argument("file_path", help="Path to local proof file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = Path(args.file_path).expanduser().resolve()
    if not artifact.exists() or not artifact.is_file():
        sys.stderr.write(f"File not found: {artifact}\n")
        return 2

    backend = os.environ.get("PROOF_UPLOAD_BACKEND", "github_repo").strip().lower() or "github_repo"
    timeout = int(os.environ.get("PROOF_UPLOAD_TIMEOUT", "120"))

    try:
        if backend == "catbox":
            url = upload_catbox(artifact, timeout)
            backup_url = None
        elif backend == "github_repo":
            url = upload_github_repo(artifact, timeout)
            backup_url = upload_gist_backup(artifact, url, timeout) if os.environ.get("PROOF_GIST_BACKUP", "").strip() in {"1", "true", "yes"} else None
        elif backend == "github_attachment":
            url = upload_github_attachment(artifact, timeout)
            backup_url = upload_gist_backup(artifact, url, timeout) if os.environ.get("PROOF_GIST_BACKUP", "").strip() in {"1", "true", "yes"} else None
        else:
            raise RuntimeError(f"Unsupported PROOF_UPLOAD_BACKEND: {backend}")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Upload failed: {exc}\n")
        return 1

    if backup_url:
        print(json.dumps({"public_url": url, "backup_url": backup_url}))
    else:
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
