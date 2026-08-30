#!/usr/bin/env python3
"""PreToolUse guard: keep agent file edits out of the primary checkout.

AGENTS.md requires working each issue in its own worktree. This enforces it:
an edit in the primary checkout lands on whatever branch the shared checkout
has out and survives branch switches, which is how work gets stranded on the
wrong branch when parallel sessions share one checkout.

Primary vs. linked worktree is detected through git rather than a hardcoded
path, so this is machine-independent: in the primary checkout --git-dir and
--git-common-dir resolve to the same directory, while in a linked worktree
--git-dir points at .git/worktrees/<name> and --git-common-dir still points at
the shared .git.

Stdlib only, to match the repo's Python 3.12 / uv stack.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

BLOCK_MESSAGE = """Blocked: {path} is in the primary checkout.

Edits here land on whichever branch the shared checkout has out and survive \
branch switches, so work gets stranded on the wrong branch when sessions share \
one checkout.

Start the issue in its own worktree and edit there instead:
  git worktree add ../<slug> -b issue-<N>-<slug> main

Only .claude/ local config is editable in the primary checkout. See AGENTS.md \
for the full workflow."""


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def git_path(directory: str, which: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--path-format=absolute", which],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        allow()

    path = os.path.abspath(path)

    # Write may target a file that doesn't exist yet — walk up to a real dir.
    directory = os.path.dirname(path)
    while not os.path.isdir(directory) and directory != os.path.dirname(directory):
        directory = os.path.dirname(directory)

    git_dir = git_path(directory, "--git-dir")
    common_dir = git_path(directory, "--git-common-dir")

    # Not a git repo — nothing to enforce.
    if not git_dir or not common_dir:
        allow()

    # Linked worktree — exactly where work is supposed to happen.
    if git_dir != common_dir:
        allow()

    # Local machine config lives in the primary checkout by design:
    # .claude/settings.json, worktree tooling output, etc.
    if f"{os.sep}.claude{os.sep}" in path:
        allow()

    deny(BLOCK_MESSAGE.format(path=path))


if __name__ == "__main__":
    main()
