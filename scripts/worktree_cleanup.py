#!/usr/bin/env python3
"""Report and clean up git worktrees whose work has landed on the default branch.

The linked GitHub issue is the source of truth: a worktree is a removal
candidate only when its issue is CLOSED. The merged-PR and clean-tree checks
are corroborating evidence that removing it loses nothing.

Usage:
    python scripts/worktree_cleanup.py report
    python scripts/worktree_cleanup.py clean <issue|branch> [...] | all

`report` removes nothing; `clean` removes only confirmed-removable worktrees.

Stdlib only, to match the repo's Python 3.12 / uv stack.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def git(args: list[str], cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def git_or_none(args: list[str], cwd: Path = REPO_ROOT) -> str | None:
    """Run git, returning None on failure. Stderr is captured, never leaked —
    a failed probe (e.g. a branch a parallel session just removed) must not
    spew `fatal:` into the report or the scheduled-job log."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def gh_json(args: list[str]):
    try:
        result = subprocess.run(
            ["gh", *args], cwd=REPO_ROOT, capture_output=True, text=True
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


@lru_cache(maxsize=1)
def default_branch() -> str:
    """The remote's default branch, detected from origin/HEAD with a `main`
    fallback (origin/HEAD is not always set locally)."""
    ref = git_or_none(["symbolic-ref", "refs/remotes/origin/HEAD"])
    if ref:
        return ref.rsplit("/", 1)[-1]
    return "main"


def parse_worktrees(porcelain: str) -> list[dict]:
    # `git worktree list --porcelain` always lists the primary checkout first;
    # flagging it by position keeps it out of the candidate set even when this
    # script runs from inside a linked worktree.
    worktrees: list[dict] = []
    current: dict | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            current = {
                "path": line[len("worktree ") :],
                "branch": None,
                "locked": False,
                "primary": len(worktrees) == 0,
            }
            worktrees.append(current)
        elif line.startswith("branch ") and current is not None:
            current["branch"] = line[len("branch ") :].replace("refs/heads/", "", 1)
        elif line.startswith("locked") and current is not None:
            current["locked"] = True
    return worktrees


def issue_number_from_branch(branch: str | None) -> str | None:
    if not branch:
        return None
    match = re.search(r"issue-(\d+)", branch)
    return match.group(1) if match else None


def get_issue_info(issue_number: str):
    return gh_json(["issue", "view", issue_number, "--json", "state,title,url"])


def merged_pr_for_branch(branch: str):
    # Squash merges are allowed on this repo, so a merged branch's commits are
    # never ancestors of the default branch — ask GitHub directly.
    prs = gh_json(
        [
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "merged",
            "--json",
            "number,title,mergedAt",
            "--limit",
            "1",
        ]
    )
    return prs[0] if prs else None


def is_ancestor_of_default(branch: str) -> bool:
    return (
        git_or_none(
            ["merge-base", "--is-ancestor", branch, f"origin/{default_branch()}"]
        )
        is not None
    )


def inspect_worktrees() -> list[dict]:
    git_or_none(["fetch", "origin", default_branch(), "--prune", "--quiet"])

    entries: list[dict] = []
    for wt in parse_worktrees(git(["worktree", "list", "--porcelain"])):
        if wt["primary"] or not wt["branch"]:
            continue

        branch = wt["branch"]
        issue_number = issue_number_from_branch(branch)
        issue = get_issue_info(issue_number) if issue_number else None
        merged_pr = merged_pr_for_branch(branch)
        ancestor = False if merged_pr else is_ancestor_of_default(branch)
        dirty = bool(git_or_none(["status", "--porcelain"], Path(wt["path"])))
        ahead = int(
            git_or_none(["rev-list", "--count", f"origin/{default_branch()}..{branch}"])
            or "0"
        )

        # Each blocker is a reason NOT to remove, phrased for the held-back list.
        blockers: list[str] = []
        if not issue_number:
            blockers.append(
                "branch name has no issue number — can't confirm the work is done"
            )
        elif not issue:
            blockers.append(f"issue #{issue_number} could not be read from GitHub")
        elif issue.get("state") != "CLOSED":
            blockers.append(f"issue #{issue_number} is still {issue.get('state')}")
        if dirty:
            blockers.append("uncommitted changes in the worktree")
        if not merged_pr and not ancestor:
            blockers.append(f"no merged PR, and branch is not in {default_branch()}")

        entries.append(
            {
                "worktree_path": wt["path"],
                "branch": branch,
                "locked": wt["locked"],
                "issue_number": issue_number,
                "issue_state": issue.get("state") if issue else None,
                "issue_title": issue.get("title") if issue else None,
                "merged_pr_number": merged_pr.get("number") if merged_pr else None,
                "merged_pr_merged_at": merged_pr.get("mergedAt") if merged_pr else None,
                "in_default_by_ancestry": ancestor,
                "dirty": dirty,
                "ahead": ahead,
                "blockers": blockers,
                "removable": not blockers,
            }
        )
    return entries


def evidence_for(entry: dict) -> list[str]:
    evidence: list[str] = []
    if entry["issue_number"]:
        line = f"issue #{entry['issue_number']} is {entry['issue_state']}"
        if entry["issue_title"]:
            line += f" — {entry['issue_title']}"
        evidence.append(line)
    if entry["merged_pr_number"]:
        when = (entry["merged_pr_merged_at"] or "unknown date")[:10]
        evidence.append(f"PR #{entry['merged_pr_number']} merged {when}")
    elif entry["in_default_by_ancestry"]:
        evidence.append(f"branch is already contained in {default_branch()}")
    evidence.append(
        "HAS uncommitted changes" if entry["dirty"] else "working tree is clean"
    )
    if entry["ahead"] > 0:
        evidence.append(
            f"{entry['ahead']} commit(s) not in {default_branch()} — "
            "expected after a squash merge"
        )
    return evidence


def remove_worktree_and_branch(entry: dict) -> None:
    if entry["locked"]:
        git_or_none(["worktree", "unlock", entry["worktree_path"]])
    git(["worktree", "remove", entry["worktree_path"]])
    # -D, not -d: a squash-merged branch is not an ancestor of the default
    # branch, so git's own safety check would refuse even though the PR merged.
    git(["branch", "-D", entry["branch"]])
    if git_or_none(["ls-remote", "--heads", "origin", entry["branch"]]):
        git_or_none(["push", "origin", "--delete", entry["branch"]])


def cmd_report(_args: argparse.Namespace) -> int:
    entries = inspect_worktrees()
    removable = [e for e in entries if e["removable"]]
    held_back = [e for e in entries if not e["removable"]]

    lines: list[str] = []
    if not removable:
        lines.append(
            "Nothing to clean up: no worktree has a closed issue and a clean tree."
        )
    else:
        lines.append(f"{len(removable)} worktree(s) confirmed safe to remove:")
        for entry in removable:
            lines.append("")
            lines.append(f"  {entry['branch']}")
            for line in evidence_for(entry):
                lines.append(f"    ✓ {line}")
        lines.append("")
        lines.append("Nothing was removed. To act on it, run:")
        targets = " ".join(e["issue_number"] or e["branch"] for e in removable)
        lines.append(f"  python scripts/worktree_cleanup.py clean {targets}")

    if held_back:
        lines.append("")
        lines.append(f"{len(held_back)} worktree(s) kept:")
        for entry in held_back:
            lines.append(f"  - {entry['branch']} — {'; '.join(entry['blockers'])}")

    print("\n".join(lines))
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    entries = inspect_worktrees()
    removable = [e for e in entries if e["removable"]]

    want_all = args.targets == ["all"]
    if want_all:
        targets = removable
    else:
        wanted = set(args.targets)
        targets = [
            e for e in removable if e["issue_number"] in wanted or e["branch"] in wanted
        ]

    if not targets:
        wanted = set(args.targets)
        held = [
            e
            for e in entries
            if not e["removable"]
            and (e["issue_number"] in wanted or e["branch"] in wanted)
        ]
        if held:
            print("Requested worktree(s) are not safe to remove:", file=sys.stderr)
            for entry in held:
                print(
                    f"  - {entry['branch']} — {'; '.join(entry['blockers'])}",
                    file=sys.stderr,
                )
        else:
            print(
                "No matching removable worktrees found for: " + ", ".join(args.targets),
                file=sys.stderr,
            )
        return 1

    for entry in targets:
        print(f"Cleaning up {entry['branch']} ({entry['worktree_path']})")
        for line in evidence_for(entry):
            print(f"  ✓ {line}")
        remove_worktree_and_branch(entry)
        print("  worktree + branch removed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report", help="list removable worktrees with evidence")
    clean = sub.add_parser("clean", help="remove confirmed-removable worktrees")
    clean.add_argument(
        "targets",
        nargs="+",
        metavar="issue|branch",
        help='issue numbers or branch names, or the literal "all"',
    )

    args = parser.parse_args()
    if args.command == "report":
        return cmd_report(args)
    return cmd_clean(args)


if __name__ == "__main__":
    raise SystemExit(main())
