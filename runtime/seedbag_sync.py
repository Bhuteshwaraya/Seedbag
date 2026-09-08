"""Cooperative synchronization gate for one project and one shared branch.

Claims form a separate append-only Git history. Every claim transition is a
normal non-force push, so competing children cannot both replace one tip.
No timeout proves a missing writer saved its files. These checks coordinate
participating commands; they are not a filesystem security boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid

import seedbag_core as core
import seedbag_git as git

Error = core.Error
POLICY = ".seedbag/sync.json"
RECEIPT = ".seedbag-local/sync-session.json"
CLAIM_REF = "refs/heads/seedbag-sync-claims"
_TRUSTED = (
    "seedbag.py", "seedbag_setup.py", "AGENTS.md", "FIRST_RUN.md", "SYNC.md",
    ".gitattributes", ".gitignore", POLICY,
)


def _read(root, name, optional=False):
    path = git._no_link(Path(root), name)
    if optional and not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot read synchronization state {name}; preserve it for recovery: {exc}") from exc
    if not isinstance(value, dict):
        raise Error(f"Invalid synchronization state {name}; preserve it for recovery.")
    return value


def _write(root, name, value):
    path = git._no_link(Path(root), name)
    path.parent.mkdir(parents=True, exist_ok=True)
    core.atomic_write(path, core.canonical(value) + b"\n")


def _identity(locator):
    """Compare GitHub HTTPS and supported SSH rewrites without credentials."""
    if not isinstance(locator, str) or not locator or "\n" in locator or "\0" in locator:
        raise Error("The shared repository location is missing or invalid.")
    github = (
        r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?",
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?",
        r"ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?/?",
        r"ssh://git@ssh\.github\.com:443/([^/]+)/([^/]+?)(?:\.git)?/?",
    )
    for pattern in github:
        match = re.fullmatch(pattern, locator, re.IGNORECASE)
        if match and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in match.groups()):
            return "github:" + "/".join(match.groups()).lower()
    # Local bare repositories support deterministic tests and explicit local
    # sharing. They are not described as GitHub or as another device's files.
    if "://" not in locator and "@" not in locator:
        path = Path(locator)
        if path.is_absolute():
            return "local:" + os.path.normcase(str(path.resolve()))
    raise Error("Use the project's exact GitHub repository or an absolute local repository path; unsupported destinations require review.")


def _policy(root):
    value = _read(root, POLICY)
    expected = {"schema", "policy", "repository", "remote", "branch", "claim_ref"}
    if set(value) != expected or value["schema"] != 1 or value["policy"] not in ("strict", "local"):
        raise Error("The synchronization policy is invalid; new work is paused.")
    ledger = core.load(root)["ledger"]
    if value["repository"] != ledger["repository"]:
        raise Error("Synchronization policy and project repository disagree; preserve both before recovery.")
    if value["claim_ref"] != CLAIM_REF:
        raise Error("The shared writer claim location changed; explicit recovery is required.")
    if value["policy"] == "local":
        if value["repository"]:
            raise Error("A repository-backed project cannot disable synchronization as local-only.")
        return value
    _identity(value["repository"])
    return value


def _binding(root, policy):
    git._root(root)
    remote, branch = policy["remote"], policy["branch"]
    if not isinstance(remote, str) or not remote or remote.startswith("-") or remote not in git._text(root, "remote").splitlines():
        raise Error("The project's bound Git remote is not configured. Complete connection setup before editing.")
    if not isinstance(branch, str) or branch.startswith("-") or git._git(root, "check-ref-format", "--branch", branch, allow_failure=True).returncode:
        raise Error("The project's bound branch is invalid.")
    if f"refs/heads/{branch}" == CLAIM_REF:
        raise Error("That branch is reserved for writer coordination; it cannot also hold the project.")
    current = git._git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
    if current.returncode or current.stdout.decode().strip() != branch:
        raise Error("This checkout is on a different or detached branch; restore the bound project branch before editing.")
    for option in ((), ("--push",)):
        urls = git._text(root, "remote", "get-url", *option, "--all", remote).splitlines()
        if len(urls) != 1 or _identity(urls[0]) != _identity(policy["repository"]):
            raise Error("The configured fetch or push destination does not match this project's repository. No synchronization was attempted.")


def configure(root, remote="origin", branch=None):
    """Bind an explicitly selected existing transport; never set credentials."""
    root = Path(root).resolve()
    with core.project_lock(root):
        repository = core.load(root)["ledger"]["repository"]
        if branch is None:
            probe = git._git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
            branch = probe.stdout.decode().strip() if not probe.returncode else "main"
        value = {"schema": 1, "policy": "strict" if repository else "local",
                 "repository": repository, "remote": remote, "branch": branch,
                 "claim_ref": CLAIM_REF}
        existing = _read(root, POLICY, optional=True)
        if existing is not None and existing != value:
            raise Error("An existing synchronization binding differs. Preserve it and review the destination instead of silently rebinding.")
        if repository:
            _binding(root, value)
        if existing is None:
            _write(root, POLICY, value)
        return {"state": "configured", "policy": value, "ready_to_edit": False}


def _tip(root, policy, ref):
    data = git._git(root, "ls-remote", "--heads", policy["remote"], ref).stdout.decode("ascii").splitlines()
    if not data:
        return None
    if len(data) != 1:
        raise Error("The remote reference could not be identified exactly.")
    oid, observed_ref = data[0].split()
    if observed_ref != ref or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
        raise Error("The remote reference response is invalid.")
    return oid


def _fresh_refs(root, policy):
    refs = (f"refs/heads/{policy['branch']}", CLAIM_REF)
    values = {ref: None for ref in refs}
    for line in git._git(root, "ls-remote", "--heads", policy["remote"], *refs).stdout.decode("ascii").splitlines():
        oid, ref = line.split()
        if ref not in values or values[ref] is not None or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise Error("The shared project and writer references could not be verified exactly.")
        values[ref] = oid
    return values[refs[0]], values[CLAIM_REF]


def _fetch(root, policy, ref):
    tip = _tip(root, policy, ref)
    if tip is None:
        return None
    git._git(root, "fetch", "--no-tags", "--", policy["remote"], ref)
    fetched = git._text(root, "rev-parse", "FETCH_HEAD")
    readback = _tip(root, policy, ref)
    if fetched != tip or readback != tip:
        raise Error("The shared reference changed during inspection. Local files are preserved; inspect again before working.")
    return tip


def _changes(root):
    # Index validation detects conflicts, links and submodules before any save.
    git._index(root)
    hidden = []
    for record in git._git(root, "ls-files", "-v", "-z").stdout.split(b"\0"):
        if record and (chr(record[0]).islower() or record[:1] == b"S"):
            hidden.append(record[2:].decode("utf-8", "strict"))
    if hidden:
        raise Error("Git is hiding tracked working-file changes through assume-unchanged or skip-worktree flags. Restore ordinary file tracking before synchronization: " + ", ".join(hidden))
    return sorted(set(
        git._names(git._git(root, "diff", "--cached", "--name-only", "-z").stdout)
        + git._names(git._git(root, "diff", "--name-only", "-z").stdout)
        + git._names(git._git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    ))


def _claim(root, policy):
    tip = _fetch(root, policy, CLAIM_REF)
    if tip is None:
        return None, None
    records = git._commit_records(root, tip)
    if len(records) != 1 or records[0][0] != "claim.json":
        raise Error("The shared writer claim contains unexpected files; do not take it over.")
    try:
        claim = json.loads(git._git(root, "show", f"{tip}:claim.json").stdout)
    except (ValueError, OSError) as exc:
        raise Error("The shared writer claim cannot be read; do not take it over.") from exc
    keys = {"schema", "repository", "branch", "state", "token", "base"}
    if not isinstance(claim, dict) or set(claim) != keys or claim["schema"] != 1:
        raise Error("The shared writer claim format is not supported.")
    if claim["repository"] != policy["repository"] or claim["branch"] != policy["branch"]:
        raise Error("The shared writer claim belongs to a different project binding.")
    if claim["state"] not in ("active", "free") or (claim["state"] == "free" and claim["token"] is not None):
        raise Error("The shared writer claim state is invalid.")
    if claim["state"] == "active" and (not isinstance(claim["token"], str) or not re.fullmatch(r"[0-9a-f]{32}", claim["token"])):
        raise Error("The active writer claim identity is invalid.")
    if claim["base"] is not None and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(claim["base"])):
        raise Error("The shared writer claim base is invalid.")
    return tip, claim


def _transition(root, policy, parent, claim):
    encoded = core.canonical(claim) + b"\n"
    blob = git._git(root, "hash-object", "-w", "--stdin", input_bytes=encoded).stdout.decode().strip()
    tree = git._git(root, "mktree", input_bytes=f"100644 blob {blob}\tclaim.json\n".encode()).stdout.decode().strip()
    env = dict(os.environ)
    # Coordination metadata has its own explicit service attribution and never
    # changes the account's Git configuration or project commit attribution.
    env.update(GIT_AUTHOR_NAME="Seedbag coordination", GIT_AUTHOR_EMAIL="seedbag@users.noreply.invalid",
               GIT_COMMITTER_NAME="Seedbag coordination", GIT_COMMITTER_EMAIL="seedbag@users.noreply.invalid")
    args = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    if parent:
        args += ["-p", parent]
    args += ["-m", "Record Seedbag writer " + claim["state"]]
    commit = git._git(root, *args, env=env).stdout.decode().strip()
    try:
        git._git(root, "push", "--", policy["remote"], f"{commit}:{CLAIM_REF}")
    except Error as exc:
        raise Error("Writer claim update was rejected or is uncertain. Local files are preserved; inspect the shared claim before retrying. " + str(exc)) from exc
    if _tip(root, policy, CLAIM_REF) != commit:
        raise Error("Writer claim push returned without exact readback. New work is paused until the claim is verified.")
    return commit


def _requested_session(requested):
    if requested is None:
        requested = os.environ.get("SEEDBAG_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    if requested is not None and (not isinstance(requested, str) or not requested.strip() or len(requested) > 300):
        raise Error("Supply a nonempty local session identifier of at most 300 characters.")
    return requested


def _session(root, policy, requested=None):
    previous = _read(root, RECEIPT, optional=True)
    requested = _requested_session(requested)
    if requested is None:
        raise Error("Identify the current session before synchronization: pass --session or set SEEDBAG_SESSION_ID for this work session. An unidentified caller cannot reuse another writer's receipt.")
    if previous and previous.get("state") in ("acquiring", "ready_to_edit", "blocked", "publishing"):
        if requested is not None and requested != previous.get("session"):
            # A failed inspection or another writer's refusal did not create a
            # local ownership claim. Preserve uncertain successful acquisitions.
            claim_tip, active = _claim(root, policy)
            if active and active["state"] == "active" and active["token"] == previous.get("token"):
                raise Error("Another session owns this workspace's unfinished writer claim. Finish its checkpoint or explicitly resume that session first.")
            if previous.get("claim") is not None:
                # A release may have reached the remote before its response was
                # lost. Only verified history plus this exact clean checkpoint
                # permits a new session to discard that obsolete local receipt.
                shared = _tip(root, policy, f"refs/heads/{policy['branch']}")
                if (claim_tip is None or not _ancestry(root, previous["claim"], claim_tip)
                        or shared != previous.get("remote_tip") or git._head(root) != shared or _changes(root)):
                    raise Error("The previous session's release is not verified. Preserve local work and inspect the shared claim before changing sessions.")
        else:
            return previous
    return {"schema": 1, "session": requested, "token": uuid.uuid4().hex,
            "state": "acquiring", "remote_tip": None, "claim": None, "setup": False}


def _acquire(root, policy, receipt, base):
    tip, claim = _claim(root, policy)
    if claim and claim["state"] == "active":
        if claim["token"] != receipt.get("token"):
            raise Error("Another workspace has unfinished project work. New edits are paused; ask that workspace to save and release its checkpoint. A claim never expires automatically.")
        if receipt.get("claim") is not None and receipt["claim"] != tip:
            raise Error("This workspace's writer claim history changed unexpectedly. Inspect it before resuming.")
        receipt["claim"] = tip
        return
    receipt.update(state="acquiring", remote_tip=base)
    _write(root, RECEIPT, receipt)  # Recover our exact identity after uncertain push.
    claim = {"schema": 1, "repository": policy["repository"], "branch": policy["branch"],
             "state": "active", "token": receipt["token"], "base": base}
    receipt["claim"] = _transition(root, policy, tip, claim)
    _write(root, RECEIPT, receipt)


def _held(root, policy, receipt):
    tip, claim = _claim(root, policy)
    if not claim or claim["state"] != "active" or claim["token"] != receipt.get("token"):
        raise Error("This session no longer holds the shared writer claim. Preserve local work and synchronize before editing.")
    if receipt.get("claim") != tip:
        raise Error("The shared writer claim history changed unexpectedly. Preserve local work and inspect it before editing.")
    return tip


def _bootstrap(root, commit):
    if commit is None:
        return True
    headers = git._git(root, "cat-file", "commit", commit).stdout.split(b"\n\n", 1)[0].splitlines()
    return not any(line.startswith(b"parent ") for line in headers) and [name for name, _ in git._commit_records(root, commit)] == ["README.md"]


def _trusted(root, old, new):
    def entries(commit):
        return {name: oid for name, oid in git._commit_records(root, commit)
                if name in _TRUSTED or name.startswith(".seedbag/runtime/") or name.startswith(".codex/")}
    if entries(old) != entries(new):
        raise Error("The incoming checkpoint changes installed instructions, runtime, or synchronization settings. Review those changes before adopting them; no project files were updated.")


def _ancestry(root, older, newer):
    return git._git(root, "merge-base", "--is-ancestor", older, newer, allow_failure=True).returncode == 0


def _publish_clean(root, policy, base, incomplete):
    commit = git._head(root)
    if commit is None:
        raise Error("There is no local checkpoint to publish.")
    if base and not _ancestry(root, base, commit):
        raise Error("Both copies changed independently. Preserve both histories and reconcile before new project work.")
    audit = git.audit_commit(root, commit, base or commit, incomplete=incomplete)
    destination = f"refs/heads/{policy['branch']}"
    if _tip(root, policy, destination) != base:
        raise Error("The shared project changed before publication. Local work is preserved; no push was attempted.")
    git._git(root, "push", "--", policy["remote"], f"{commit}:{destination}")
    if _tip(root, policy, destination) != commit:
        raise Error("Publication is uncertain: the shared tip did not match exact readback. Inspect the remote before retrying; do not repeat project effects.")
    return commit, audit


def _save(root, policy, receipt, paths, message, incomplete):
    changed = _changes(root)
    if not changed:
        return None
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise Error("intended_file_paths_required: inspect the preserved changes and name each intended file before checkpointing: " + ", ".join(changed))
    if set(changed) - set(paths):
        raise Error("Unreviewed local files remain outside the intended checkpoint: " + ", ".join(sorted(set(changed) - set(paths))))
    for name in paths:
        path = git._no_link(root, name)
        if path.is_dir() or name == ".seedbag-local" or name.startswith(".seedbag-local/"):
            raise Error("Name exact intended project files; local scratch is never a checkpoint target.")
        if name.startswith(".seedbag/") and name not in (git.LEDGER, POLICY) and not name.startswith(".seedbag/runtime/"):
            raise Error("Internal working files are not publication targets: " + name)
        # An explicit argument does not override project ignore rules for new
        # files. In particular an ignored .env must never become an auto save.
        tracked = git._git(root, "ls-files", "--error-unmatch", "--", name, allow_failure=True).returncode == 0
        if not tracked and git._git(root, "check-ignore", "--quiet", "--", name, allow_failure=True).returncode == 0:
            raise Error("An ignored file is not a synchronization checkpoint target: " + name)
    staged = set(git._names(git._git(root, "diff", "--cached", "--name-only", "-z").stdout))
    unstaged = set(git._names(git._git(root, "diff", "--name-only", "-z").stdout))
    if staged & unstaged:
        raise Error("The index preserves a different version of an intended file. Reconcile that version before checkpointing: " + ", ".join(sorted(staged & unstaged)))
    if not isinstance(message, str) or not message.strip():
        raise Error("Supply a short description for the intended checkpoint.")
    git._git(root, "add", "--", *paths)
    audit = git.gate(root, incomplete=incomplete)
    if git._git(root, "diff", "--cached", "--quiet", allow_failure=True).returncode == 1:
        env = dict(os.environ)
        env.pop("SEEDBAG_INCOMPLETE_CHECKPOINT", None)
        if incomplete:
            env["SEEDBAG_INCOMPLETE_CHECKPOINT"] = "1"
        git._git(root, "commit", "-m", message, env=env)
    return audit


def _result(policy, receipt, actions=None):
    return {"state": receipt["state"], "ready_to_edit": receipt["state"] == "ready_to_edit",
            "session": receipt["session"], "commit": receipt.get("remote_tip"),
            "remote_tip": receipt.get("remote_tip"), "remote": policy["remote"],
            "branch": policy["branch"], "claim": receipt.get("claim"),
            "setup": receipt.get("setup", False), "actions": actions or [],
            "boundary": "Verified cooperating writer at this checkpoint; unpublished files on another device remain inaccessible."}


def begin(root, session=None, paths=None, message=None, incomplete=True, setup=False):
    """Freshly synchronize, then hold one writer claim until checkpoint release."""
    root = Path(root).resolve()
    with core.project_lock(root):
        policy = _policy(root)
        if policy["policy"] == "local":
            return {"state": "local_only", "ready_to_edit": True, "shared": False, "actions": []}
        _binding(root, policy)
        receipt = _session(root, policy, session)
        actions = []
        try:
            destination = f"refs/heads/{policy['branch']}"
            remote = _fetch(root, policy, destination)
            head = git._head(root)
            is_setup = bool(setup and _bootstrap(root, head) and _bootstrap(root, remote))
            if setup and not is_setup:
                raise Error("Setup is only for an unborn or README-only initial project; it cannot bypass an existing project's synchronization gate.")
            if (head is None or remote is None or _bootstrap(root, head) or _bootstrap(root, remote)) and not is_setup:
                raise Error("The initial project has no shared Seedbag checkpoint. Verify its new repository and begin an explicit setup session first.")
            _acquire(root, policy, receipt, remote)
            if _tip(root, policy, destination) != remote:
                raise Error("The project changed while acquiring its writer claim. Inspect the shared state before retrying.")
            changed = _changes(root)
            if is_setup:
                if head is None and remote is not None:
                    if git._index(root):
                        raise Error("The unborn setup index already contains work. Preserve and reconcile it before adopting the README bootstrap.")
                    git._git(root, "read-tree", remote)
                    git._git(root, "update-ref", f"refs/heads/{policy['branch']}", remote, "0" * len(remote))
                    actions.append("preserved_remote_bootstrap_ancestry")
                elif head != remote:
                    raise Error("Local and shared bootstrap commits differ. Preserve both and inspect setup before continuing.")
                receipt.update(state="ready_to_edit", remote_tip=remote, setup=True)
                _write(root, RECEIPT, receipt)
                return _result(policy, receipt, actions + ["initial_setup_verified"])
            if head != remote:
                if _ancestry(root, head, remote):
                    if changed:
                        raise Error("The shared project is newer and this workspace has unsaved files. Preserve both versions and reconcile before updating.")
                    _trusted(root, head, remote)
                    git.audit_commit(root, remote, head, incomplete=True)
                    git._git(root, "merge", "--ff-only", "--no-edit", remote)
                    if git._head(root) != remote or _changes(root):
                        raise Error("The fast-forward did not produce the exact clean checkpoint. Inspect preserved files before working.")
                    actions.append("updated_local_checkpoint")
                elif not _ancestry(root, remote, head):
                    raise Error("Both copies changed independently. Preserve both histories and reconcile before new project work.")
            if changed:
                _save(root, policy, receipt, paths, message, incomplete)
                actions.append("saved_intended_checkpoint")
            if git._head(root) != remote:
                remote, _ = _publish_clean(root, policy, remote, incomplete)
                actions.append("published_local_checkpoint")
            if _changes(root):
                raise Error("Local files changed during synchronization. Preserve and checkpoint them before starting new work.")
            git.audit_commit(root, remote, remote, incomplete=True)
            _held(root, policy, receipt)
            if _tip(root, policy, destination) != remote:
                raise Error("The shared checkpoint changed before readiness verification. New work remains paused.")
            receipt.update(state="ready_to_edit", remote_tip=remote, setup=False)
            _write(root, RECEIPT, receipt)
            return _result(policy, receipt, actions)
        except Error as exc:
            receipt.update(state="blocked", error=str(exc))
            _write(root, RECEIPT, receipt)
            raise


def require_ready(root, session=None, refresh=True):
    """Verify a current session. Does not lock; callers may hold project_lock.

    Uncommitted work is expected inside an admitted session. This guard verifies
    its unchanged shared starting point and writer claim, rather than requiring
    byte equality before every edit. A cached-only call cannot grant readiness.
    """
    root = Path(root).resolve()
    policy = _policy(root)
    if policy["policy"] == "local":
        return {"state": "local_only", "ready_to_edit": True, "shared": False}
    _binding(root, policy)
    session = _requested_session(session)
    if session is None:
        raise Error("The current session is unidentified. Supply its session identity before new project changes; a saved writer receipt cannot identify the caller.")
    receipt = _read(root, RECEIPT, optional=True)
    if not receipt or receipt.get("state") != "ready_to_edit" or (session is not None and session != receipt.get("session")):
        raise Error("Synchronization is required before new project changes. Run sync begin to recover and verify the shared starting point.")
    if not refresh:
        raise Error("A cached synchronization receipt cannot grant permission for a new work batch. Recheck the shared branch and writer claim.")
    _changes(root)  # Detect conflicts and hidden index flags, not byte equality.
    observed, claim = _fresh_refs(root, policy)
    if not claim or claim != receipt.get("claim"):
        raise Error("This session no longer holds its verified shared writer claim. Preserve local work and synchronize before editing.")
    if observed != receipt.get("remote_tip"):
        raise Error("The shared project changed after this session began. Preserve local work and reconcile before further changes.")
    head = git._head(root)
    if receipt.get("setup"):
        if not _bootstrap(root, observed) or head != observed:
            raise Error("The initial setup base changed. Reconcile setup before further changes.")
    elif head != observed:
        raise Error("A local checkpoint appeared outside synchronization. Publish and verify it before further changes.")
    return _result(policy, receipt)


def recover_session(root, session):
    """Explicitly resume this workspace's receipt in another host session.

    The caller must have established that the old session stopped. This never
    takes a claim from another workspace, discards files, or grants readiness.
    """
    root = Path(root).resolve()
    session = _requested_session(session)
    if session is None:
        raise Error("Identify the new session explicitly when resuming an unfinished workspace.")
    with core.project_lock(root):
        policy = _policy(root)
        if policy["policy"] == "local":
            return {"state": "local_only", "ready_to_edit": True, "shared": False}
        _binding(root, policy)
        receipt = _read(root, RECEIPT, optional=True)
        if not receipt or receipt.get("state") not in ("ready_to_edit", "blocked", "publishing", "acquiring"):
            raise Error("There is no unfinished local writer receipt to resume.")
        tip, claim = _claim(root, policy)
        if not claim or claim["state"] != "active" or claim["token"] != receipt.get("token"):
            raise Error("This workspace does not own the active shared claim. Do not take over another workspace's unpublished work.")
        if receipt.get("claim") not in (None, tip):
            raise Error("The writer claim history changed; inspect it before recovery.")
        shared = _fetch(root, policy, f"refs/heads/{policy['branch']}")
        if shared not in (receipt.get("remote_tip"), git._head(root)):
            raise Error("The shared project changed independently. Preserve both versions before resuming its writer.")
        previous = receipt.get("session")
        receipt.update(session=session, previous_session=previous, claim=tip, state="blocked")
        receipt["error"] = "Session resumed; synchronize preserved files before new project work."
        _write(root, RECEIPT, receipt)
        return {"state": "resumed_needs_sync", "ready_to_edit": False, "session": session,
                "previous_session": previous, "claim": tip, "changed_paths": _changes(root)}


def checkpoint(root, message, paths=None, incomplete=False, session=None, release=True):
    """Audit exact intended files, publish, verify, then release the writer."""
    root = Path(root).resolve()
    with core.project_lock(root):
        policy = _policy(root)
        if policy["policy"] == "local":
            raise Error("This project is local-only; it has no shared synchronization destination.")
        _binding(root, policy)
        session = _requested_session(session)
        if session is None:
            raise Error("Identify the current session before checkpointing; a saved writer receipt cannot identify the caller.")
        receipt = _read(root, RECEIPT, optional=True)
        if not receipt or (session is not None and session != receipt.get("session")):
            raise Error("No matching local writer receipt exists. Begin synchronization before checkpointing.")
        if receipt.get("state") == "shared_verified":
            # Stop may run after the assistant already released its checkpoint.
            # Verify that save again without taking or touching another claim.
            shared = _fetch(root, policy, f"refs/heads/{policy['branch']}")
            if _changes(root) or shared != receipt.get("remote_tip") or git._head(root) != shared:
                raise Error("Files or the shared checkpoint changed after the last release. Begin synchronization before another checkpoint.")
            audit = git.audit_commit(root, shared, shared, incomplete=incomplete)
            return {**_result(policy, receipt, ["verified_checkpoint"]), "shared": True,
                    "released": True, "snapshot_only": bool(incomplete),
                    "revision": audit["revision"], "digest": audit["digest"]}
        try:
            _held(root, policy, receipt)
            base = _fetch(root, policy, f"refs/heads/{policy['branch']}")
            head = git._head(root)
            # If a prior push succeeded but the response was lost, the remote
            # can already equal HEAD. Inspect that exact state before retrying.
            if base != receipt.get("remote_tip") and base != head:
                raise Error("The shared branch changed independently. Preserve the local checkpoint and reconcile before publication.")
            if base and head and not _ancestry(root, base, head):
                raise Error("The shared branch is ahead or divergent; no local checkpoint was changed.")
            receipt["state"] = "publishing"
            _write(root, RECEIPT, receipt)
            changed = bool(_changes(root))
            _save(root, policy, receipt, paths, message, incomplete)
            if git._head(root) != base:
                base, audit = _publish_clean(root, policy, base, incomplete)
            else:
                if base is None or _bootstrap(root, base):
                    raise Error("Initial setup must save a complete Seedbag checkpoint before releasing its writer claim.")
                audit = git.audit_commit(root, base, base, incomplete=incomplete)
            if _changes(root):
                raise Error("Files changed during the checkpoint. The writer claim remains held until those changes are preserved.")
            parent = _held(root, policy, receipt)
            if _tip(root, policy, f"refs/heads/{policy['branch']}") != base:
                raise Error("The shared checkpoint changed before claim release. Keep the writer claim and inspect both versions.")
            receipt.update(remote_tip=base, setup=False, state="ready_to_edit")
            _write(root, RECEIPT, receipt)
            if release:
                free = {"schema": 1, "repository": policy["repository"], "branch": policy["branch"],
                        "state": "free", "token": None, "base": base}
                receipt["claim"] = _transition(root, policy, parent, free)
                receipt["state"] = "shared_verified"
                _write(root, RECEIPT, receipt)
            return {**_result(policy, receipt, ["published_checkpoint"] if changed else ["verified_checkpoint"]),
                    "shared": True, "released": bool(release), "snapshot_only": bool(incomplete),
                    "revision": audit["revision"], "digest": audit["digest"]}
        except Error as exc:
            receipt.update(state="blocked", error=str(exc))
            _write(root, RECEIPT, receipt)
            raise


def status(root):
    """Read local/cached state without presenting it as fresh permission."""
    root = Path(root).resolve()
    policy = _policy(root)
    receipt = _read(root, RECEIPT, optional=True)
    state = git.status(root, fetch=False)
    return {"state": "local_only" if policy["policy"] == "local" else "not_rechecked",
            "ready_to_edit": policy["policy"] == "local", "policy": policy,
            "receipt": receipt, "changed_paths": sorted(set(state.get("staged", []) + state.get("unstaged", []) + state.get("untracked", []))),
            "git": state, "reference_freshness": "cached_not_rechecked"}
