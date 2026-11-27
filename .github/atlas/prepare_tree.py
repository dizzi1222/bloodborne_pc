#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Checks out the target upstream release tag, ensures LF line endings on all
patch files, and cherry-picks the Hunter's Atlas native-mod commits onto it.
Opens or updates a GitHub issue in the fork if a cherry-pick conflict occurs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace")


def report_conflict_issue(target: dict, status_out: str, diff_out: str) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = target.get("fork_repo") or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    upstream_tag = target["upstream_tag"]
    title = f"[Atlas CI] Cherry-pick conflict on {upstream_tag}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "HuntersAtlas-CI/1.0",
        "Content-Type": "application/json",
    }
    run_url = ""
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ['GITHUB_SERVER_URL']}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    body = (
        f"Automated cherry-pick of `{target['atlas_branch']}` (`{target['atlas_tip'][:10]}`) "
        f"onto `{upstream_tag}` (`{target['upstream_commit'][:10]}`) failed.\n\n"
        f"- **Upstream release**: `{upstream_tag}`\n"
        f"- **Atlas branch**: `{target['atlas_branch']}` (`{target['atlas_tip']}`)\n"
        f"- **Workflow run**: {run_url or 'N/A'}\n\n"
        f"### `git status --short`\n```\n{status_out.strip()}\n```\n\n"
        f"### Unmerged diff preview\n```diff\n{diff_out.strip()[:4000]}\n```\n\n"
        f"Until `{target['atlas_branch']}` is rebased onto `{upstream_tag}`, the Hunter's Atlas updater "
        f"will safely keep users on the previous supported release."
    )

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            issues = json.load(resp)
        existing_num = None
        for issue in issues:
            if issue.get("title") == title:
                existing_num = issue.get("number")
                break
        if existing_num:
            patch_req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/issues/{existing_num}",
                data=json.dumps({"body": body}).encode("utf-8"),
                headers=headers,
                method="PATCH",
            )
            urllib.request.urlopen(patch_req, timeout=30).close()
            print(f"Updated conflict issue #{existing_num}")
        else:
            post_req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/issues",
                data=json.dumps({"title": title, "body": body}).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(post_req, timeout=30).close()
            print(f"Opened conflict issue: {title}")
    except Exception as exc:
        print(f"Warning: could not create/update conflict issue: {exc}", file=sys.stderr)


def main() -> int:
    ci_dir = Path(os.environ["ATLAS_CI_DIR"]).resolve()
    target_path = ci_dir / "target.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))

    upstream_tag = target["upstream_tag"]
    commits = target["atlas_commits"]

    run(["git", "config", "core.autocrlf", "false"])
    run(["git", "config", "core.eol", "lf"])
    run(["git", "config", "core.longpaths", "true"])

    run(["git", "checkout", "-f", "-B", "atlas-build", f"refs/tags/{upstream_tag}"])
    run(["git", "reset", "--hard", f"refs/tags/{upstream_tag}"])
    run(["git", "clean", "-fdx"])

    cp = run(
        [
            "git",
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "cherry-pick",
            *commits,
        ],
        check=False,
    )
    if cp.returncode != 0:
        status_out = run(["git", "status", "--short"], check=False).stdout
        diff_out = run(["git", "diff"], check=False).stdout
        run(["git", "cherry-pick", "--abort"], check=False)
        print(f"Cherry-pick failed on {upstream_tag}:\n{cp.stdout}\n{cp.stderr}", file=sys.stderr)
        report_conflict_issue(target, status_out, diff_out)
        return 1

    # Normalize any .patch files to LF so git apply inside build.sh never fails
    for patch_file in Path("gpu/patches").rglob("*.patch"):
        raw = patch_file.read_bytes()
        if b"\r\n" in raw:
            patch_file.write_bytes(raw.replace(b"\r\n", b"\n"))

    # Verify ABI header and native_mods.py are present
    sdk_header = Path("sdk/bbport_native_mod.h")
    if not sdk_header.is_file() or "BBPORT_NATIVE_MOD_API_V1" not in sdk_header.read_text(encoding="utf-8"):
        raise RuntimeError("sdk/bbport_native_mod.h is missing BBPORT_NATIVE_MOD_API_V1 after cherry-pick")
    if not Path("scripts/native_mods.py").is_file():
        raise RuntimeError("scripts/native_mods.py is missing after cherry-pick")

    built_commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    target["built_commit"] = built_commit
    target_path.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared patched tree at {built_commit} on top of {upstream_tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
