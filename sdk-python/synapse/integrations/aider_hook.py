"""Aider post-commit hook installer.

Aider commits per-edit. We use that as a natural Synapse audit
checkpoint: after every commit, run `synapse audit` on the session's
JSONL log and print conflicts.

Install:
    python -m synapse.integrations.aider_hook install

Uninstall:
    python -m synapse.integrations.aider_hook uninstall
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

HOOK_MARKER = "# >>> synapse aider audit hook >>>"
HOOK_END_MARKER = "# <<< synapse aider audit hook <<<"

HOOK_BODY = """\
{marker}
# Run synapse audit after each Aider commit.
# Uninstall: python -m synapse.integrations.aider_hook uninstall
SYN_SESSION="${{SYNAPSE_SESSION_ID:-aider-default}}"
SYN_LOG=".synapse/runs/${{SYN_SESSION}}.jsonl"
if [ -f "$SYN_LOG" ]; then
    synapse audit "$SYN_LOG" --no-html 2>/dev/null || true
fi
{end_marker}
"""


def _git_dir() -> Path:
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        if (d / ".git").is_dir():
            return d / ".git"
    raise SystemExit("error: not inside a git repo (no .git dir found)")


def install(args: argparse.Namespace) -> int:
    git = _git_dir()
    hooks_dir = git / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "post-commit"

    body = HOOK_BODY.format(marker=HOOK_MARKER, end_marker=HOOK_END_MARKER)

    if hook.exists():
        existing = hook.read_text(encoding="utf-8")
        if HOOK_MARKER in existing:
            print(f"  synapse hook already installed at {hook}")
            return 0
        new = existing.rstrip() + "\n\n" + body
        hook.write_text(new, encoding="utf-8")
        print(f"  appended synapse hook to existing {hook}")
    else:
        hook.write_text("#!/bin/sh\n\n" + body, encoding="utf-8")
        print(f"  created {hook}")

    # Make executable on POSIX (Windows ignores)
    try:
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass

    print("  to use:  export SYNAPSE_SESSION_ID=team-2026-q2; aider")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    git = _git_dir()
    hook = git / "hooks" / "post-commit"
    if not hook.exists():
        print(f"  no hook at {hook}")
        return 0
    text = hook.read_text(encoding="utf-8")
    if HOOK_MARKER not in text:
        print(f"  synapse hook not present in {hook}")
        return 0
    # Strip our block including markers
    start = text.find(HOOK_MARKER)
    end = text.find(HOOK_END_MARKER) + len(HOOK_END_MARKER)
    new = (text[:start] + text[end:]).strip() + "\n"
    if new.strip() in ("#!/bin/sh", ""):
        hook.unlink()
        print(f"  removed empty {hook}")
    else:
        hook.write_text(new, encoding="utf-8")
        print(f"  removed synapse hook from {hook}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="synapse.integrations.aider_hook")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="add synapse audit to .git/hooks/post-commit").set_defaults(func=install)
    sub.add_parser("uninstall", help="remove the hook").set_defaults(func=uninstall)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
