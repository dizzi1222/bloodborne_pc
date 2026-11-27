#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Resolves the target upstream bbport Windows release and checks whether an
Atlas host release for that upstream version + Atlas commit tip already exists
in the fork repository."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def run_git(*args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return res.stdout.strip()


def github_get(url: str, token: str | None = None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HuntersAtlas-CI/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def write_output(key: str, value: str) -> None:
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    print(f"OUTPUT {key}={value}")


def main() -> int:
    ci_dir = Path(os.environ["ATLAS_CI_DIR"]).resolve()
    ci_dir.mkdir(parents=True, exist_ok=True)

    fork_repo = os.environ.get("GITHUB_REPOSITORY", "dizzi1222/bloodborne_pc")
    upstream_repo = os.environ.get("UPSTREAM_REPOSITORY", "Supermedo/bloodborne_pc")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    input_tag = (os.environ.get("INPUT_UPSTREAM_TAG") or "").strip()
    atlas_branch = (os.environ.get("INPUT_ATLAS_BRANCH") or "atlas-native-mod").strip()
    input_base = (os.environ.get("INPUT_ATLAS_BASE") or "115a029").strip()
    force = (os.environ.get("INPUT_FORCE") or "false").strip().lower() == "true"
    prerelease = (os.environ.get("INPUT_PRERELEASE") or "true").strip().lower() == "true"

    remotes = run_git("remote").splitlines()
    upstream_url = f"https://github.com/{upstream_repo}.git"
    if "upstream" not in remotes:
        run_git("remote", "add", "upstream", upstream_url)
    else:
        run_git("remote", "set-url", "upstream", upstream_url)

    run_git("fetch", "--tags", "--force", "upstream", "windows")
    run_git("fetch", "--force", "origin", f"refs/heads/{atlas_branch}:refs/remotes/origin/{atlas_branch}")

    releases = github_get(f"https://api.github.com/repos/{upstream_repo}/releases?per_page=30", token)
    assert isinstance(releases, list)

    chosen_release = None
    if input_tag:
        for rel in releases:
            if rel.get("tag_name") == input_tag:
                chosen_release = rel
                break
        if not chosen_release:
            chosen_release = github_get(
                f"https://api.github.com/repos/{upstream_repo}/releases/tags/{input_tag}",
                token,
            )
    else:
        candidates = []
        for rel in releases:
            if rel.get("draft") or rel.get("prerelease"):
                continue
            tag = str(rel.get("tag_name") or "")
            m = re.fullmatch(r"windows-v(\d+(?:\.\d+)*)", tag)
            if not m:
                continue
            candidates.append((version_tuple(m.group(1)), rel))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            raise RuntimeError(f"No published windows-v* release found in {upstream_repo}")
        chosen_release = candidates[0][1]

    upstream_tag = str(chosen_release["tag_name"])
    m = re.fullmatch(r"windows-v(\d+(?:\.\d+)*)", upstream_tag)
    if not m:
        raise RuntimeError(f"Upstream tag {upstream_tag!r} does not match windows-v<version>")
    base_version = m.group(1)

    zip_url = ""
    zip_sha256 = ""
    for asset in chosen_release.get("assets") or []:
        aname = str(asset.get("name") or "")
        if aname.lower() == "bloodborne-windows.zip":
            zip_url = str(asset.get("browser_download_url") or "")
            digest = str(asset.get("digest") or "")
            if digest.lower().startswith("sha256:"):
                zip_sha256 = digest.split(":", 1)[1].strip().lower()
            break

    run_git("fetch", "upstream", f"refs/tags/{upstream_tag}:refs/tags/{upstream_tag}")
    upstream_commit = run_git("rev-parse", f"refs/tags/{upstream_tag}^{{commit}}")
    atlas_tip = run_git("rev-parse", f"refs/remotes/origin/{atlas_branch}^{{commit}}")

    atlas_base = ""
    if input_base:
        try:
            resolved_base = run_git("rev-parse", f"{input_base}^{{commit}}")
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", resolved_base, atlas_tip],
                check=True,
            )
            atlas_base = resolved_base
        except subprocess.CalledProcessError:
            atlas_base = ""
    if not atlas_base:
        atlas_base = run_git("merge-base", "upstream/windows", f"refs/remotes/origin/{atlas_branch}")

    commits_raw = run_git("rev-list", "--reverse", f"{atlas_base}..{atlas_tip}")
    atlas_commits = [c.strip() for c in commits_raw.splitlines() if c.strip()]
    if not atlas_commits:
        raise RuntimeError(f"No Atlas commits found in range {atlas_base}..{atlas_tip}")

    # Check existing releases in fork
    fork_releases = github_get(f"https://api.github.com/repos/{fork_repo}/releases?per_page=100", token)
    assert isinstance(fork_releases, list)

    tag_pattern = re.compile(rf"^atlas-host-v{re.escape(base_version)}-atlas\.(\d+)$")
    max_rev = 0
    already_built_tag = ""
    for rel in fork_releases:
        rtag = str(rel.get("tag_name") or "")
        tm = tag_pattern.fullmatch(rtag)
        if not tm:
            continue
        rev = int(tm.group(1))
        if rev > max_rev:
            max_rev = rev
        body = str(rel.get("body") or "")
        assets = rel.get("assets") or []
        has_zip = any(str(a.get("name") or "").endswith(".zip") for a in assets)
        if has_zip and f"<!-- atlas-tip: {atlas_tip} -->" in body:
            already_built_tag = rtag

    # Also check legacy release tags (e.g. hunters-atlas-v0.1.2) for existing host-<base_version>-atlas.<R>.zip
    legacy_pattern = re.compile(
        rf"^(?:bbport-atlas-host|Hunters-Atlas-[0-9.]+-bbport-host)-{re.escape(base_version)}-atlas\.(\d+)\.zip$"
    )
    for rel in fork_releases:
        for asset in rel.get("assets") or []:
            aname = str(asset.get("name") or "")
            lm = legacy_pattern.fullmatch(aname)
            if lm:
                rev = int(lm.group(1))
                if rev > max_rev:
                    max_rev = rev

    if already_built_tag and not force:
        print(f"Release {already_built_tag} already exists for {upstream_tag} and Atlas tip {atlas_tip}.")
        write_output("should_build", "false")
        write_output("release_tag", already_built_tag)
        write_output("base_version", base_version)
        return 0

    next_rev = max_rev + 1
    host_version = f"{base_version}-atlas.{next_rev}"
    release_tag = f"atlas-host-v{host_version}"
    zip_name = f"bbport-atlas-host-{host_version}.zip"

    target_data = {
        "schema": 1,
        "fork_repo": fork_repo,
        "upstream_repo": upstream_repo,
        "upstream_tag": upstream_tag,
        "upstream_commit": upstream_commit,
        "upstream_zip_url": zip_url,
        "upstream_zip_sha256": zip_sha256,
        "base_version": base_version,
        "atlas_branch": atlas_branch,
        "atlas_base": atlas_base,
        "atlas_tip": atlas_tip,
        "atlas_commits": atlas_commits,
        "atlas_revision": next_rev,
        "host_version": host_version,
        "release_tag": release_tag,
        "zip_name": zip_name,
        "prerelease": prerelease,
    }
    (ci_dir / "target.json").write_text(json.dumps(target_data, indent=2) + "\n", encoding="utf-8")

    write_output("should_build", "true")
    write_output("upstream_tag", upstream_tag)
    write_output("base_version", base_version)
    write_output("atlas_revision", str(next_rev))
    write_output("host_version", host_version)
    write_output("release_tag", release_tag)
    write_output("zip_name", zip_name)
    write_output("prerelease", "true" if prerelease else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
