#!/usr/bin/env python3
"""Bring the newest upstream DARKSLIDE GR release into this branch.

    python3 desktop/scripts/update_from_upstream.py [--remote origin] [--push REMOTE]

Fetches the remote's tags, takes the newest vX.Y.Z, and merges it into the current
branch unless it is already there. Then it checks what the desktop app depends on:
the launcher's interface (PORT, --no-browser, POST /api/quit), the resources the
program reads (check_resources.py) and that the shell still builds. The version needs
no edit: mygo.config.ts reads darkslide/__init__.py. With --push, the branch goes to
REMOTE, where CI tests every platform and leaves the installers as run artifacts.

A merge conflict stops here with the conflicting files listed; nothing is pushed.
Exit code 0 when the branch holds the newest release and every check passed.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
REPO = DESKTOP.parent


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO, check=check, capture_output=True, text=True)


def newest_tag():
    tags = [t for t in git("tag", "--list", "v*").stdout.split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if not tags:
        sys.exit("no vX.Y.Z tags fetched")
    return max(tags, key=lambda t: tuple(int(n) for n in t[1:].split(".")))


def interface_ok():
    """What main.go relies on in launcher.py and the server."""
    launcher = (REPO / "launcher.py").read_text(encoding="utf-8")
    server = (REPO / "darkslide" / "server.py").read_text(encoding="utf-8")
    problems = []
    if 'env.get("PORT")' not in launcher:
        problems.append("launcher.py no longer reads PORT")
    if '"--no-browser"' not in launcher:
        problems.append("launcher.py no longer takes --no-browser")
    if '("POST", "/api/quit"' not in server:
        problems.append("the server no longer has POST /api/quit")
    for p in problems:
        print("interface: " + p)
    return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--remote", default="origin", help="the upstream remote (default: origin)")
    ap.add_argument("--push", metavar="REMOTE", help="push the branch there once everything passed")
    args = ap.parse_args()

    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        sys.exit("commit or put aside your changes first")
    git("fetch", "--quiet", "--tags", args.remote)
    tag = newest_tag()
    branch = git("branch", "--show-current").stdout.strip()
    if git("merge-base", "--is-ancestor", tag, "HEAD", check=False).returncode == 0:
        print("%s already holds %s" % (branch, tag))
    else:
        print("merging %s into %s" % (tag, branch))
        merged = git("merge", "--no-edit", "-m", "Merge upstream %s into the desktop app" % tag, tag, check=False)
        if merged.returncode != 0:
            conflicts = git("diff", "--name-only", "--diff-filter=U").stdout.split()
            git("merge", "--abort", check=False)
            print("merge conflict, nothing changed: " + ", ".join(conflicts or ["(see git output)"]))
            print(merged.stdout + merged.stderr)
            return 1

    version = re.search(r'^VERSION\s*=\s*"([^"]+)"', (REPO / "darkslide" / "__init__.py").read_text(encoding="utf-8"), re.M)
    print("program version: %s (the app takes it from darkslide/__init__.py)" % (version and version.group(1)))
    ok = interface_ok()
    ok &= subprocess.run([sys.executable, str(DESKTOP / "scripts" / "check_resources.py")], cwd=DESKTOP).returncode == 0
    for goos in ("darwin", "windows"):
        vet = subprocess.run(["go", "vet", "./..."], cwd=DESKTOP, env=dict(__import__("os").environ, GOOS=goos),
                             capture_output=True, text=True)
        if vet.returncode != 0:
            print("go vet (%s) failed:\n%s" % (goos, vet.stdout + vet.stderr))
            ok = False
    if not ok:
        print("checks failed: fix them before pushing")
        return 1
    print("checks passed")
    if args.push:
        pushed = git("push", args.push, branch, check=False)
        print(pushed.stdout + pushed.stderr)
        return pushed.returncode
    print("push the branch to run CI on every platform and get the installers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
