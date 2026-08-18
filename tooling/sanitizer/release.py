#!/usr/bin/env python3
"""
Drive the `ccs-sanitize` release runbook (issue #181).

`RELEASING.md` is the explanation; this is the mechanism. It covers the three
steps of "Cutting a release" that were shell blocks to copy-paste (3, 5, 7) and
the workflow dispatch in step 4. Steps 1 and 2 stay ordinary PR work, and step 6
stays manual on purpose. See "What this cannot do" below.

Usage:
    python3 tooling/sanitizer/release.py preflight
    python3 tooling/sanitizer/release.py tag [--dry-run]
    python3 tooling/sanitizer/release.py rehearse [--dry-run]
    python3 tooling/sanitizer/release.py verify

**It takes no version argument.** `__version__` in `src/ccs_sanitize/__init__.py`
is already the single source of truth, the release workflow derives its gates
from it, and the tag is mechanically `sanitizer-v<version>`. Deriving rather than
accepting removes a whole class of release error: nothing to type is nothing to
fat-finger.

What this can and cannot write, stated precisely because a vague version of this
claim is worse than none:

- **It performs exactly two outward-facing writes.** `tag` pushes one tag.
  `rehearse` dispatches a workflow run that uploads to TestPyPI, which is a real
  public index -- so a rehearsal *is* a publish, just not to PyPI.
- **It cannot publish to PyPI.** No token, no `twine upload`, no publish action.
  A pushed tag uploads nothing on its own, because `publish-pypi` parks at the
  `pypi-sanitizer` environment. The worst outcome of a mistaken `tag` is a wasted
  CI run and a tag to delete.
- **It never approves a deployment.** `gh api .../pending_deployments -f
  state=approved` exists and is deliberately not called. RELEASING.md already
  concedes the required reviewer is the same person who cut the release;
  collapsing approval into the script that pushed the tag would remove the last
  step that happens in a different context, in front of a different screen.
- **It never deletes or force-updates anything on `origin`.** Recovery paths
  print the exact commands and stop. A convenience wrapper that cleans up after
  you is where a mistake becomes destructive.

Four mechanics that are easy to get wrong and are load-bearing here:

1. `sanitizer-ci` is read from the **check-runs** API, not the combined-status
   API. Actions results are check runs, not legacy commit statuses, so
   `GET /commits/{sha}/status` reports `{"state": "pending", "statuses": []}`
   on a commit whose checks are all green. Combined with a correct
   absent-means-failure rule, that endpoint would block every release.
2. `gh api --paginate` emits one JSON document *per page*, which is not valid
   JSON in aggregate. `--slurp` wraps them in an array. Without it, the first
   commit to carry more than one page of check runs breaks the read.
3. `gh run watch` is always invoked with `--exit-status`. Without it, it exits 0
   even when the run failed. The TestPyPI rehearsal is the only gate in the chain
   that catches a server-side metadata rejection before a version number is
   spent, so laundering a failed rehearsal into a green one is the sharpest
   failure mode this script could have.
4. A tag's SHA is peeled **on the remote** (`refs/tags/<tag>^{}`). An annotated
   tag's unpeeled ref names the tag object, not the commit, so an unpeeled read
   can never match a workflow run's `headSha`.

The predicates that decide things live as pure functions at the top of the file
and are covered by `tests/test_release.py`. They fail closed: on anything
ambiguous or unrecognized they raise rather than guess, because every one of them
guards something whose failure mode is a release that looks fine.

The subprocess wrappers below them are the untested boundary, kept thin for that
reason.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# This script lives at <repo-root>/tooling/sanitizer/release.py.
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent

VERSION_FILE = PACKAGE_ROOT / "src" / "ccs_sanitize" / "__init__.py"
CHANGELOG = PACKAGE_ROOT / "CHANGELOG.md"

DIST_NAME = "claude-code-sessions-sanitizer"
WHEEL_STEM = DIST_NAME.replace("-", "_")
TAG_PREFIX = "sanitizer-v"
WORKFLOW = "sanitizer-release.yml"
# The aggregate gate job's `name:` in sanitizer-ci.yml. Branch protection points
# at this too, so if it is ever renamed both places move together.
CHECK_NAME = "sanitizer-ci"

PYPI = "https://pypi.org"
TESTPYPI = "https://test.pypi.org"

# TestPyPI's index can lag a successful upload by a few seconds.
INSTALL_ATTEMPTS = 6
INSTALL_BACKOFF_SECONDS = 10


class ReleaseError(Exception):
    """A precondition failed. Carries a maintainer-facing message."""


# --------------------------------------------------------------------------
# Pure predicates. No I/O, no subprocess: these are the parts that decide
# things, so they are the parts worth testing.
# --------------------------------------------------------------------------


def parse_version(init_py_text):
    """Pull `__version__` out of the package's __init__.py source."""
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_py_text, re.M)
    if not match:
        raise ReleaseError("no __version__ assignment found in " + str(VERSION_FILE))
    return match.group(1)


def tag_for(version):
    """The component-scoped tag. Never a bare `v<version>`; see the README."""
    return TAG_PREFIX + version


def changelog_has_entry(changelog_text, version):
    """True when CHANGELOG.md carries a `## [<version>]` heading.

    Dots are escaped so `0.3.0` cannot be satisfied by a `0x3y0` heading.
    """
    return re.search(r"^## \[" + re.escape(version) + r"\]", changelog_text, re.M) is not None


def evaluate_check_runs(check_runs, check_name=CHECK_NAME):
    """Decide whether `check_name` is green on a commit. Returns (ok, detail).

    Fails closed. **Absent is failure, not pass** -- that is the whole point.
    `sanitizer-ci` has no tag trigger, so a commit can carry no check run at
    all, and "no status" reads as innocuous while meaning nothing was verified.

    This is advisory. Its authority is the release workflow's own `ci` job
    re-running the matrix on the tagged ref. Nothing may ever skip that on the
    strength of this local read.
    """
    matching = [run for run in check_runs if run.get("name") == check_name]
    if not matching:
        return False, "no '{}' check run on this commit".format(check_name)

    # Most recent wins: a re-run supersedes an earlier attempt. `started_at` is
    # ISO-8601 so it sorts lexicographically; `id` breaks ties deterministically.
    latest = sorted(matching, key=lambda r: (r.get("started_at") or "", r.get("id") or 0))[-1]

    status = latest.get("status")
    conclusion = latest.get("conclusion")
    if status != "completed":
        return False, "'{}' is {}, not completed".format(check_name, status)
    if conclusion != "success":
        return False, "'{}' concluded {}".format(check_name, conclusion)
    return True, "'{}' succeeded".format(check_name)


def merge_paginated(pages, key):
    """Flatten `gh api --paginate --slurp` output (a list of page objects)."""
    if not isinstance(pages, list):
        raise ReleaseError("expected a slurped page array, got " + type(pages).__name__)
    merged = []
    for page in pages:
        merged.extend(page.get(key) or [])
    return merged


def pick_dispatched_run(runs, head_sha, known_ids):
    """Identify the run our dispatch just created. Returns the run, or None.

    `gh workflow run` prints no run id, so the run has to be found afterwards.
    Matching on head SHA alone is not enough: at this point the same SHA
    already carries a parked tag-push run, and a re-rehearsal after a burned
    version adds more dispatch runs over time.

    So the caller snapshots the ids that existed before dispatching and this
    returns one that did not. Run ids are monotonic, which makes the check
    clock-independent -- a timestamp comparison would be at the mercy of skew
    between the laptop and GitHub.

    **Ambiguity raises rather than guessing.** If more than one candidate
    appears -- a second maintainer dispatching concurrently, or GitHub's
    eventually-consistent listing having omitted an older run from the
    snapshot -- picking one would risk watching a run that already concluded
    `success` and reporting a rehearsal that never gated these bytes. That is
    the false-green this whole file is built to avoid.
    """
    fresh = [
        run
        for run in runs
        if run.get("databaseId") not in known_ids
        and run.get("headSha") == head_sha
        and run.get("event") == "workflow_dispatch"
    ]
    if not fresh:
        return None
    if len(fresh) > 1:
        raise ReleaseError(
            "{} new workflow_dispatch runs appeared at {} ({}); refusing to guess "
            "which one is ours. Watch it by hand.".format(
                len(fresh), head_sha[:8], ", ".join(str(r["databaseId"]) for r in sorted(fresh, key=lambda r: r["databaseId"]))
            )
        )
    return fresh[0]


def index_has_version(index_payload, version):
    """True when `version` already exists on an index.

    `index_payload` is the parsed JSON API response, or None for a 404 (project
    does not exist yet, which is the expected state before a first release).

    A **yanked** version still exists here, and that is correct: yank is not
    delete, the number stays spent, and the index will not accept it again.

    Fails closed on an unrecognized payload. This guard's only job is to stop a
    spent version being tagged, so "I do not understand this response" must not
    resolve to "the version is free".
    """
    if index_payload is None:
        return False
    releases = index_payload.get("releases")
    if not isinstance(releases, dict):
        raise ReleaseError(
            "unrecognized index payload: no 'releases' map. Refusing to assume {} "
            "is unpublished; check the index by hand.".format(version)
        )
    return version in releases


# --------------------------------------------------------------------------
# Boundary. Thin wrappers over git / gh / pip / the index APIs.
# --------------------------------------------------------------------------


def run_cmd(cmd, capture=True, check=True, cwd=None):
    """Run a command. Absolute cwd, never a `cd` that leaks into later calls."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ReleaseError("command failed: {}\n{}".format(" ".join(cmd), detail))
    return result


def gh_json(args):
    """Run a `gh` command that emits JSON and parse it."""
    raw = run_cmd(["gh"] + args).stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseError("gh {} did not return valid JSON: {}".format(" ".join(args), exc))


def fetch_index_json(base_url, name):
    """GET an index's JSON API for a project. None on 404."""
    url = "{}/pypi/{}/json".format(base_url, name)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReleaseError("{} returned HTTP {}".format(url, exc.code))
    except urllib.error.URLError as exc:
        raise ReleaseError("could not reach {}: {}".format(url, exc.reason))


_SLUG = []


def repo_slug():
    """owner/repo for the current checkout, from gh. Resolved once."""
    if not _SLUG:
        _SLUG.append(gh_json(["repo", "view", "--json", "nameWithOwner"])["nameWithOwner"])
    return _SLUG[0]


def say(message):
    print(message, flush=True)


def ok(message):
    say("  ok    " + message)


def fail(message):
    raise ReleaseError(message)


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


def require_tools():
    for tool in ("git", "gh"):
        if shutil.which(tool) is None:
            fail("required tool not on PATH: " + tool)
    if run_cmd(["gh", "auth", "status"], check=False).returncode != 0:
        fail("gh is not authenticated; run `gh auth login`")
    # Venvs are built with sys.executable, so that is the interpreter to name.
    ok("git and gh (authenticated) present; python is " + sys.executable)


def require_clean_main():
    branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != "main":
        fail("on branch '{}'; releases are cut from main".format(branch))

    if run_cmd(["git", "status", "--porcelain"]).stdout.strip():
        fail("working tree is not clean; commit or stash first")

    run_cmd(["git", "fetch", "origin", "--quiet"])
    local = run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = run_cmd(["git", "rev-parse", "origin/main"]).stdout.strip()
    if local != remote:
        fail("main is not level with origin/main ({} vs {}); pull first".format(local[:8], remote[:8]))

    ok("on main, clean, level with origin/main at " + local[:8])
    return local


def remote_tag_sha(tag):
    """The commit a tag names on `origin`, or None if the tag is not there.

    Peeled remotely: an annotated tag's unpeeled ref names the tag *object*, so
    an unpeeled SHA can never match a workflow run's `headSha`. Peeling on the
    remote rather than locally also means a stale or missing local tag cannot
    override what origin actually has.
    """
    peeled = run_cmd(["git", "ls-remote", "origin", "refs/tags/" + tag + "^{}"]).stdout.strip()
    if peeled:
        return peeled.split()[0]
    unpeeled = run_cmd(["git", "ls-remote", "origin", "refs/tags/" + tag]).stdout.strip()
    if unpeeled:
        return unpeeled.split()[0]
    return None


def require_tag_absent(tag):
    if run_cmd(["git", "rev-parse", "--verify", "--quiet", "refs/tags/" + tag], check=False).returncode == 0:
        fail(
            "tag {} already exists locally.\n"
            "        If this is a restart after a failed release, remove it deliberately:\n"
            "          git tag -d {}\n"
            "          git push origin :refs/tags/{}".format(tag, tag, tag)
        )
    if remote_tag_sha(tag):
        fail("tag {} already exists on origin; see `git push origin :refs/tags/{}`".format(tag, tag))
    ok("tag {} is free".format(tag))


def require_ci_green(sha):
    # --slurp is mandatory with --paginate: without it gh emits one JSON
    # document per page and the aggregate is not parseable.
    path = "repos/{}/commits/{}/check-runs?per_page=100".format(repo_slug(), sha)
    runs = merge_paginated(gh_json(["api", path, "--paginate", "--slurp"]), "check_runs")
    green, detail = evaluate_check_runs(runs)
    if not green:
        fail(
            "{} on {}.\n"
            "        This is advisory -- the release workflow re-runs the full matrix on\n"
            "        the tagged ref regardless -- but a tag is annoying to undo, so it is\n"
            "        checked before the tag rather than after.".format(detail, sha[:8])
        )
    ok(detail + " on " + sha[:8])


def require_version_free(version, base_url, label):
    if index_has_version(fetch_index_json(base_url, DIST_NAME), version):
        fail(
            "{} already has {} {}.\n"
            "        If you have already rehearsed this version, that is expected and you\n"
            "        are past this step -- go on to step 6. Otherwise the number is spent:\n"
            "        no index accepts a version twice and a yanked version still counts,\n"
            "        so bump to the next patch version and start again.".format(label, DIST_NAME, version)
        )
    ok("{} does not yet have {}".format(label, version))


def preflight():
    """Everything that must hold before the tag is pushed. Read-only."""
    say("Preflight")
    require_tools()
    sha = require_clean_main()

    version = parse_version(VERSION_FILE.read_text())
    tag = tag_for(version)
    ok("version {} -> tag {}".format(version, tag))

    if not changelog_has_entry(CHANGELOG.read_text(), version):
        fail("no '## [{}]' heading in {}".format(version, CHANGELOG))
    ok("CHANGELOG has an entry for " + version)

    require_tag_absent(tag)
    require_ci_green(sha)
    require_version_free(version, PYPI, "PyPI")
    require_version_free(version, TESTPYPI, "TestPyPI")

    return version, tag, sha


# --------------------------------------------------------------------------
# Clean-environment verification, shared by `rehearse` and `verify`
# --------------------------------------------------------------------------


def verify_from_index(version, index_args, label):
    """Install the pinned version into a throwaway venv and exercise it.

    The version is **pinned** and the index is **explicit**. Unpinned, with
    `--extra-index-url` pointing at real PyPI (needed because PyYAML is not on
    TestPyPI), pip resolves the highest version across both indexes -- so a
    candidate that has not yet propagated to TestPyPI would silently install
    the previous shipped release and this would validate the wrong bytes.
    Naming the index also stops a `PIP_INDEX_URL` or a `pip.conf` mirror
    quietly answering with something other than what the index is serving.

    The assertions here mirror the smoke-test steps in sanitizer-ci.yml and
    sanitizer-release.yml. Keep the three in step: they check the same
    contract from three different vantage points (pre-merge, pre-upload,
    post-upload).
    """
    say("Verifying {} from {}".format(version, label))
    workdir = tempfile.mkdtemp(prefix="ccs-release-")
    venv = os.path.join(workdir, "venv")
    scratch = os.path.join(workdir, "scratch")
    os.makedirs(scratch)

    run_cmd([sys.executable, "-m", "venv", venv])
    python = os.path.join(venv, "bin", "python")
    cli = os.path.join(venv, "bin", "ccs-sanitize")
    run_cmd([python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])

    spec = "{}=={}".format(DIST_NAME, version)
    install = [python, "-m", "pip", "install", "--quiet", "--no-cache-dir"] + index_args + [spec]
    for attempt in range(1, INSTALL_ATTEMPTS + 1):
        result = run_cmd(install, check=False)
        if result.returncode == 0:
            break
        if attempt == INSTALL_ATTEMPTS:
            fail("could not install {} from {} after {} attempts:\n{}".format(spec, label, attempt, result.stderr))
        say("  ...    not on {} yet, retrying in {}s ({}/{})".format(label, INSTALL_BACKOFF_SECONDS, attempt, INSTALL_ATTEMPTS))
        time.sleep(INSTALL_BACKOFF_SECONDS)
    ok("installed " + spec)

    reported = run_cmd([cli, "--version"]).stdout.strip()
    if version not in reported:
        fail("--version reported '{}', expected it to contain {}".format(reported, version))
    ok("--version reports " + reported)

    # `--init` outside the checkout and outside any git repository: the
    # first-run shape for someone who installed from an index with no clone.
    # It exercises the config guard's warn-and-proceed path.
    run_cmd([cli, "--init"], cwd=scratch)
    written = sorted(p.name for p in Path(scratch).iterdir() if p.is_file())
    if ".ccs-sanitize.example.yaml" not in written:
        fail("--init did not write the example template; got " + str(written))
    # The live config is asserted by count rather than by name. Naming it in a
    # committed file is what .claude/hooks/block_secret_reads.py discourages.
    if len(written) != 2:
        fail("--init wrote {} files, expected the example and the live config".format(len(written)))
    ok("--init works outside a git repository (wrote {} files)".format(len(written)))

    say("Verification passed. Scratch dir left at {} (safe to delete).".format(workdir))


def check_attestations(version):
    """Confirm both published artifacts carry PEP 740 provenance.

    Hard-fails on a definitive 404. `sanitizer-release.yml` sets
    `attestations: true` explicitly and its own comment anticipates the action
    flipping that default, so a missing attestation is a regression worth a
    non-zero exit rather than a line of output that scrolls past. A network
    error is only a warning: not reaching the endpoint is not evidence.
    """
    missing = []
    for artifact in (
        "{}-{}-py3-none-any.whl".format(WHEEL_STEM, version),
        "{}-{}.tar.gz".format(WHEEL_STEM, version),
    ):
        url = "{}/integrity/{}/{}/{}/provenance".format(PYPI, DIST_NAME, version, artifact)
        try:
            with urllib.request.urlopen(url, timeout=30):
                ok("attestation published for " + artifact)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                missing.append(artifact)
                say("  FAIL  no attestation for {} (HTTP 404)".format(artifact))
            else:
                say("  note  attestation check for {} returned HTTP {}".format(artifact, exc.code))
        except urllib.error.URLError as exc:
            say("  note  could not reach {} ({}); check by hand".format(url, exc.reason))
    if missing:
        fail(
            "no PEP 740 attestation for: {}.\n"
            "        The upload succeeded but shipped without provenance. Check that\n"
            "        `attestations: true` still holds in sanitizer-release.yml.".format(", ".join(missing))
        )


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_preflight(_args):
    preflight()
    say("\nAll preflight checks passed. Next: release.py tag")


def cmd_tag(args):
    version, tag, sha = preflight()
    subject = run_cmd(["git", "log", "-1", "--format=%s", sha]).stdout.strip()

    say("\n  version   {}".format(version))
    say("  tag       {}".format(tag))
    say("  commit    {}  {}".format(sha[:8], subject))
    say("")
    say("  Pushing this tag starts the release workflow. It re-runs the full matrix on")
    say("  the tagged commit, builds with the pinned backend, smoke-tests the artifact,")
    say("  and then PARKS at the pypi-sanitizer gate. Nothing is uploaded to PyPI until")
    say("  you approve it by hand, which this script will not do for you.")
    say("")

    if args.dry_run:
        say("--dry-run: would run")
        say("  git tag {} {}".format(tag, sha))
        say("  git push origin {}".format(tag))
        return

    try:
        typed = input("  Type the tag to confirm: ").strip()
    except EOFError:
        fail("confirmation needs an interactive terminal; nothing was pushed")
    if typed != tag:
        fail("confirmation did not match; nothing was pushed")

    # Tag the SHA preflight validated and printed, not whatever HEAD is now.
    # The operator agreed to a specific commit, and HEAD can move while the
    # prompt is open.
    run_cmd(["git", "tag", tag, sha])
    run_cmd(["git", "push", "origin", tag])
    say("\nPushed {} at {}.".format(tag, sha[:8]))
    say("Runs: https://github.com/{}/actions/workflows/{}".format(repo_slug(), WORKFLOW))
    say("Next: release.py rehearse (do this BEFORE approving the parked run)")


def cmd_rehearse(args):
    version = parse_version(VERSION_FILE.read_text())
    tag = tag_for(version)

    say("Rehearsing {} against TestPyPI".format(tag))
    say("  note: this uploads to a real public index. It is not a dry run.")
    tag_sha = remote_tag_sha(tag)
    if not tag_sha:
        fail("tag {} is not on origin yet; run `release.py tag` first".format(tag))
    ok("tag {} is on origin at {}".format(tag, tag_sha[:8]))
    require_version_free(version, TESTPYPI, "TestPyPI")

    if args.dry_run:
        say("--dry-run: would run `gh workflow run {} --ref {}`".format(WORKFLOW, tag))
        return

    listing = ["run", "list", "--workflow", WORKFLOW, "--event", "workflow_dispatch",
               "--limit", "50", "--json", "databaseId,headSha,event,url"]
    known = {r["databaseId"] for r in gh_json(listing)}

    run_cmd(["gh", "workflow", "run", WORKFLOW, "--ref", tag])
    say("  dispatched; resolving the run id")

    dispatched = None
    for _ in range(30):
        time.sleep(4)
        dispatched = pick_dispatched_run(gh_json(listing), tag_sha, known)
        if dispatched:
            break
    if not dispatched:
        fail(
            "dispatched, but could not identify the run. Find it by hand at\n"
            "        https://github.com/{}/actions/workflows/{}".format(repo_slug(), WORKFLOW)
        )
    run_id = dispatched["databaseId"]
    say("  run " + (dispatched.get("url") or "id {}".format(run_id)))

    # --exit-status is mandatory: plain `gh run watch` exits 0 on a failed run,
    # which would turn a failed rehearsal into a green one.
    watched = run_cmd(["gh", "run", "watch", str(run_id), "--exit-status"], capture=False, check=False)
    conclusion = gh_json(["run", "view", str(run_id), "--json", "conclusion"])["conclusion"]
    if watched.returncode != 0 or conclusion != "success":
        fail("rehearsal run {} concluded '{}'".format(run_id, conclusion))
    ok("rehearsal run concluded success")

    verify_from_index(
        version,
        ["--index-url", TESTPYPI + "/simple/", "--extra-index-url", PYPI + "/simple/"],
        "TestPyPI",
    )
    say("\nRehearsal complete. Next: approve the parked pypi-sanitizer deployment by hand,")
    say("then run release.py verify")


def cmd_verify(_args):
    version = parse_version(VERSION_FILE.read_text())
    verify_from_index(version, ["--index-url", PYPI + "/simple/"], "PyPI")
    check_attestations(version)
    say("\nReleased {} {}.".format(DIST_NAME, version))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Drive the ccs-sanitize release runbook (tooling/sanitizer/RELEASING.md).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="read-only checks; run before you tag").set_defaults(func=cmd_preflight)

    p_tag = sub.add_parser("tag", help="runbook step 3: create and push the release tag")
    p_tag.add_argument("--dry-run", action="store_true", help="show what would be pushed, push nothing")
    p_tag.set_defaults(func=cmd_tag)

    p_reh = sub.add_parser("rehearse", help="runbook steps 4+5: dispatch to TestPyPI, then verify")
    p_reh.add_argument("--dry-run", action="store_true", help="show what would be dispatched, dispatch nothing")
    p_reh.set_defaults(func=cmd_rehearse)

    sub.add_parser("verify", help="runbook step 7: verify the published release").set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ReleaseError as exc:
        print("\nerror: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except (OSError, json.JSONDecodeError) as exc:
        # Reachable: a moved VERSION_FILE, an unreadable CHANGELOG, a gh that
        # returned something unparseable. A precondition message beats a stack
        # trace in the middle of a release.
        print("\nerror: {}: {}".format(type(exc).__name__, exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
