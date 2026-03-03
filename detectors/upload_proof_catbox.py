#!/usr/bin/env python3
"""Upload proof artifact and print a public URL.

Default backend: catbox.moe anonymous file upload API.

Usage (called by bug_audit_system.py):
  python3 ./detectors/upload_proof_catbox.py /abs/path/to/file.png

Optional env vars:
- PROOF_UPLOAD_BACKEND: "catbox" (default) or "github_repo"
- PROOF_UPLOAD_TIMEOUT: request timeout seconds (default: 120)
- For github_repo backend:
  - PROOF_GH_TOKEN: GitHub token with contents:write
  - PROOF_GH_OWNER: owner/org (optional if PROOF_GH_REPO is owner/repo)
  - PROOF_GH_REPO: repo name or owner/repo
  - PROOF_GH_BRANCH: branch name (default: main)
  - PROOF_GH_PATH_PREFIX: path prefix in repo (default: proofs)
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import os
import sys
import uuid
from pathlib import Path

import requests


def upload_catbox(path: Path, timeout: int) -> str:
    with path.open("rb") as handle:
        response = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": handle},
            timeout=timeout,
        )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise RuntimeError(f"Uploader did not return a URL: {url[:200]}")
    return url


def upload_github_repo(path: Path, timeout: int) -> str:
    token = os.environ.get("PROOF_GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PROOF_GH_TOKEN is required for github_repo backend")

    repo_raw = os.environ.get("PROOF_GH_REPO", "").strip()
    owner_raw = os.environ.get("PROOF_GH_OWNER", "").strip()
    if not repo_raw:
        raise RuntimeError("PROOF_GH_REPO is required for github_repo backend")

    if "/" in repo_raw:
        owner, repo = repo_raw.split("/", 1)
        owner = owner.strip()
        repo = repo.strip()
    else:
        owner = owner_raw
        repo = repo_raw

    if not owner or not repo:
        raise RuntimeError("Set PROOF_GH_REPO as owner/repo or provide PROOF_GH_OWNER + PROOF_GH_REPO")

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

    data = response.json()
    content_obj = data.get("content", {}) if isinstance(data, dict) else {}
    download_url = str(content_obj.get("download_url", "")).strip()
    if download_url.startswith("https://"):
        return download_url
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{target_path}"


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

    backend = os.environ.get("PROOF_UPLOAD_BACKEND", "catbox").strip().lower() or "catbox"
    timeout = int(os.environ.get("PROOF_UPLOAD_TIMEOUT", "120"))

    try:
        if backend == "catbox":
            url = upload_catbox(artifact, timeout)
        elif backend == "github_repo":
            url = upload_github_repo(artifact, timeout)
        else:
            raise RuntimeError(f"Unsupported PROOF_UPLOAD_BACKEND: {backend}")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Upload failed: {exc}\n")
        return 1

    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
