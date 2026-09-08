"""Seedbag: append-only structured continuity with atomic local transactions.

This is cooperative project tooling, not a security boundary against an actor
who can replace its executable or rewrite all Git history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

VERSION = "0.3.0"
LEDGER = ".seedbag/ledger.json"
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
KINDS = {"requirement", "decision", "idea", "fact", "question"}
STATUSES = {"proposed", "accepted", "deferred", "open", "rejected", "superseded"}


class Error(Exception):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Error(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_object_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(Error(f"Invalid number: {value}")))
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot read JSON from {path}: {exc}") from exc


def _need(condition, message):
    if not condition:
        raise Error(message)


def _text(value, label, empty=False):
    _need(isinstance(value, str) and "\0" not in value and (empty or bool(value.strip())), f"{label} must be text")
    return value


def _id(value):
    _need(isinstance(value, str) and ID.fullmatch(value), f"Invalid ID: {value!r}")
    return value


def _ids(value, label):
    _need(isinstance(value, list), f"{label} must be a list")
    for entry in value:
        _id(entry)
    _need(len(set(value)) == len(value), f"Duplicate IDs in {label}")
    return list(value)


def _fields(op, required, optional=()):
    _need(isinstance(op, dict), "Operation must be an object")
    _need(set(required) <= op.keys(), f"Missing fields for {op.get('op')}: {set(required) - op.keys()}")
    _need(not (op.keys() - set(required) - set(optional) - {"op"}), f"Unknown fields for {op.get('op')}")


def _linked(path):
    try:
        st = path.lstat()
        return path.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def _safe_ancestry(path):
    for part in [path, *path.parents]:
        _need(not _linked(part), f"Linked/reparse path is not supported: {part}")


def safe_path(root, relative):
    _text(relative, "Relative file path")
    _need("\\" not in relative and ":" not in relative, "Use a project-relative path with forward slashes")
    rel = PurePosixPath(relative)
    _need(not rel.is_absolute() and all(p not in {".", ".."} for p in relative.split("/")) and "//" not in relative, "Path must stay inside this project")
    _need(rel.parts and rel.parts[0].lower() not in {".git", ".seedbag", ".seedbag-local"}, "Reserved internal path")
    root = Path(root).absolute()
    target = root.joinpath(*rel.parts)
    _safe_ancestry(target)
    _need(target.resolve().is_relative_to(root.resolve()), "Path leaves project")
    return target


def input_digest(root, paths):
    _need(isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths), "Inputs must name exact files")
    _need(len(set(paths)) == len(paths), "Inputs must be distinct existing files")
    entries = []
    for relative in sorted(paths):
        path = safe_path(root, relative)
        _need(path.is_file(), f"Missing input: {relative}")
        entries.append([relative, hashlib.sha256(path.read_bytes()).hexdigest()])
    return digest(entries)


@contextmanager
def project_lock(root):
    root = Path(root).absolute()
    _safe_ancestry(root)
    directory = root / ".seedbag-local"
    _safe_ancestry(directory)
    directory.mkdir(exist_ok=True)
    path = directory / "lock"
    _safe_ancestry(path)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        start = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - start > 5:
                    raise Error("Another local writer is active; preserve its work and retry after it finishes")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path, data):
    path = Path(path)
    _safe_ancestry(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".seedbag-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _initial(ledger):
    return {"project": {"name": ledger["name"], "purpose": ""}, "captures": {}, "items": {},
            "owners": {}, "work": {}, "checks": {}, "runs": {}, "effects": {},
            "current": {"summary": "New project", "next_work": None}}


def _get(state, category, ident):
    _id(ident)
    _need(ident in state[category], f"Unknown {category} ID: {ident}")
    return state[category][ident]


def _new(state, category, ident):
    _id(ident)
    _need(ident not in state[category], f"ID already exists; preserve its history: {ident}")


def _argv(value):
    _need(isinstance(value, list) and value, "argv must be a nonempty argument list")
    for arg in value:
        _text(arg, "Command argument", empty=True)
    _text(value[0], "Executable")
    return list(value)


def _apply_op(state, operation, *, internal=False):
    op = copy.deepcopy(operation)
    name = op.get("op") if isinstance(op, dict) else None
    ident = op.get("id") if isinstance(op, dict) else None
    if name == "capture.add":
        _fields(op, ["id", "text", "origin", "locator"])
        _new(state, "captures", ident)
        _text(op["text"], "Capture text")
        _text(op["locator"], "Source locator")
        _need(op["origin"] in {"user", "assistant", "source"}, "Unknown capture origin")
        state["captures"][ident] = {k: v for k, v in op.items() if k != "op"}
        state["captures"][ident].update(disposition="pending", items=[], reason="")
    elif name == "capture.resolve":
        _fields(op, ["id", "items", "reason"])
        item = _get(state, "captures", ident)
        _need(item["disposition"] == "pending", "Capture already resolved; append a new correction instead")
        linked = _ids(op["items"], "Capture item links")
        _text(op["reason"], "Capture disposition reason")
        for linked_id in linked:
            record = _get(state, "items", linked_id)
            _need(ident in record["sources"], f"Item {linked_id} does not cite capture {ident}")
        item.update(disposition="resolved", items=linked, reason=op["reason"])
    elif name == "project.set":
        _fields(op, ["purpose"])
        state["project"]["purpose"] = _text(op["purpose"], "Purpose")
    elif name == "item.add":
        _fields(op, ["id", "kind", "text", "status", "sources"], ["global", "owner", "trigger", "reason", "replacement"])
        _new(state, "items", ident)
        _need(op["kind"] in KINDS and op["status"] in STATUSES, "Unknown item kind/status")
        _text(op["text"], "Item text")
        sources = _ids(op["sources"], "Item sources")
        _need(sources, "Every item requires source provenance")
        for source in sources:
            _get(state, "captures", source)
        item = {k: v for k, v in op.items() if k != "op"}
        item.update({k: op.get(k, default) for k, default in [("global", True), ("owner", None), ("trigger", ""), ("reason", ""), ("replacement", None)]})
        _need(type(item["global"]) is bool, "global must be a boolean")
        state["items"][ident] = item
        _validate_item(state, item)
    elif name == "item.status":
        _fields(op, ["id", "status", "reason", "source"], ["replacement", "trigger"])
        item = _get(state, "items", ident)
        source = _get(state, "captures", op["source"])
        _need(source["origin"] == "user", "A disposition change needs a recorded user source")
        _need(op["status"] in STATUSES and op["status"] != item["status"], "Supply a different valid disposition")
        _text(op["reason"], "Disposition reason")
        item.update(status=op["status"], reason=op["reason"], replacement=op.get("replacement"), trigger=op.get("trigger", item["trigger"]))
        if op["source"] not in item["sources"]:
            item["sources"].append(op["source"])
        _validate_item(state, item)
    elif name == "item.route":
        _fields(op, ["id", "global", "owner", "reason"])
        item = _get(state, "items", ident)
        _need(type(op["global"]) is bool, "global must be a boolean")
        _text(op["reason"], "Routing reason")
        if op["owner"] is not None:
            _id(op["owner"])
        _need(op["global"] or op["owner"] is not None, "A scoped item needs an owner route")
        item.update({"global": op["global"], "owner": op["owner"], "routing_reason": op["reason"]})
    elif name == "owner.add":
        _fields(op, ["id", "path", "summary", "tags", "requires"])
        _new(state, "owners", ident)
        _text(op["path"], "Owner path")
        _text(op["summary"], "Owner summary")
        _need(isinstance(op["tags"], list) and all(isinstance(x, str) and x.strip() for x in op["tags"]), "Tags must be text")
        _ids(op["requires"], "Owner dependencies")
        _need(op["path"].lower() not in {"project.md", "state.md", "agents.md", "continue_here.md"}, "Generated/instruction files cannot own domain records")
        _need(all(x["path"].casefold() != op["path"].casefold() for x in state["owners"].values()), "One owner per file")
        state["owners"][ident] = {k: v for k, v in op.items() if k != "op"}
    elif name == "owner.move":
        _fields(op, ["id", "path", "reason"])
        owner = _get(state, "owners", ident)
        _text(op["path"], "New owner path")
        _text(op["reason"], "Owner move reason")
        _need(op["path"].lower() not in {"project.md", "state.md", "agents.md", "continue_here.md"}, "Generated/instruction files cannot own domain records")
        _need(all(x["id"] == ident or x["path"].casefold() != op["path"].casefold() for x in state["owners"].values()), "One owner per file")
        owner.update(path=op["path"], move_reason=op["reason"])
    elif name == "work.add":
        _fields(op, ["id", "title", "requires", "owners", "checks"])
        _new(state, "work", ident)
        _text(op["title"], "Work title")
        for field in ["requires", "owners", "checks"]:
            _ids(op[field], field)
        state["work"][ident] = {k: v for k, v in op.items() if k != "op"}
        state["work"][ident].update(status="planned", note="")
    elif name == "work.revise":
        _fields(op, ["id", "requires", "owners", "checks", "reason"])
        item = _get(state, "work", ident)
        _need(item["status"] != "done", "Reopen completed work before revising its scope")
        _text(op["reason"], "Work revision reason")
        for field in ["requires", "owners", "checks"]:
            _ids(op[field], field)
            item[field] = op[field]
        item.update(status="planned", note=op["reason"])
    elif name == "work.status":
        _fields(op, ["id", "status", "note"])
        item = _get(state, "work", ident)
        _need(op["status"] in {"planned", "in_progress", "blocked", "done"}, "Unknown work status")
        _text(op["note"], "Work status evidence/note")
        if op["status"] == "done":
            _need(item["checks"], "Completion needs at least one declared verification check")
            for check_id in item["checks"]:
                _need(check_id in state["runs"] and state["runs"][check_id]["code"] == 0, f"Missing passing check: {check_id}")
            _need(not any(c["disposition"] == "pending" for c in state["captures"].values()), "Unprocessed captures block completion")
            _need(not any(e["status"] in {"running", "returned"} for e in state["effects"].values()), "Unresolved external effect blocks completion")
        item.update(status=op["status"], note=op["note"])
    elif name == "current.set":
        _fields(op, ["summary", "next_work"])
        _text(op["summary"], "Current summary")
        if op["next_work"] is not None:
            _id(op["next_work"])
        state["current"] = {"summary": op["summary"], "next_work": op["next_work"]}
    elif name == "check.add":
        _fields(op, ["id", "argv", "inputs", "timeout"])
        _new(state, "checks", ident)
        _argv(op["argv"])
        _need(isinstance(op["inputs"], list) and op["inputs"] and all(isinstance(x, str) for x in op["inputs"]), "Declare exact input files")
        _need(type(op["timeout"]) is int and 1 <= op["timeout"] <= 300, "Check timeout must be 1..300 seconds")
        state["checks"][ident] = {k: v for k, v in op.items() if k != "op"}
    elif name == "_check.result":
        _need(internal, "Check results can only be recorded by the check runner")
        _fields(op, ["id", "code", "input_digest", "requirements_digest", "output"])
        _get(state, "checks", ident)
        _need(type(op["code"]) is int, "Invalid exit code")
        _text(op["input_digest"], "Input digest")
        _text(op["requirements_digest"], "Requirements digest")
        _text(op["output"], "Check output", empty=True)
        state["runs"][ident] = {k: v for k, v in op.items() if k not in {"op", "id"}}
    elif name == "effect.add":
        _fields(op, ["id", "argv", "inputs", "description", "prepared_binding"])
        _new(state, "effects", ident)
        _argv(op["argv"])
        _text(op["description"], "Effect description")
        _need(isinstance(op["inputs"], list) and op["inputs"], "Effect needs declared input files")
        _text(op["prepared_binding"], "Prepared input binding")
        _need(not any(e["status"] in {"running", "returned"} and e["argv"] == op["argv"] and set(e["inputs"]) == set(op["inputs"])
                      for e in state["effects"].values()), "An unresolved attempt exists for this command/input scope; reconcile it before creating another ID")
        state["effects"][ident] = {k: v for k, v in op.items() if k != "op"}
        state["effects"][ident].update(status="prepared", binding=None)
    elif name == "effect.begin":
        _fields(op, ["id", "binding"])
        item = _get(state, "effects", ident)
        _need(item["status"] == "prepared", "Operation already attempted; reconcile its outcome instead of replaying")
        _need(not any(other_id != ident and e["status"] in {"running", "returned"} and e["argv"] == item["argv"]
                      and set(e["inputs"]) == set(item["inputs"]) for other_id, e in state["effects"].items()),
              "Another prepared ID already attempted this scope; reconcile its outcome before execution")
        _text(op["binding"], "Effect input binding")
        _need(op["binding"] == item["prepared_binding"], "Prepared operation inputs changed; review and prepare a new scope before execution")
        item.update(status="running", binding=op["binding"])
    elif name == "effect.return":
        _fields(op, ["id", "code", "output"])
        item = _get(state, "effects", ident)
        _need(item["status"] == "running", "Operation is not awaiting a return")
        _need(type(op["code"]) is int, "Invalid exit code")
        _text(op["output"], "Operation output", empty=True)
        item.update(status="returned", code=op["code"], output=op["output"])
    elif name == "effect.resolve":
        _fields(op, ["id", "outcome", "receipt", "receipt_digest"])
        item = _get(state, "effects", ident)
        _need(item["status"] in {"running", "returned"}, "Operation is not unresolved")
        _need(op["outcome"] in {"confirmed", "not_performed"}, "Unknown outcome")
        _text(op["receipt"], "Receipt path")
        _text(op["receipt_digest"], "Receipt digest")
        item.update(status=op["outcome"], receipt=op["receipt"], receipt_digest=op["receipt_digest"])
    else:
        raise Error(f"Unsupported operation: {name}; records cannot be silently removed or rewritten")


def _validate_item(state, item):
    _need(item["global"] or item["owner"] is not None, "A scoped item needs an owner route")
    if item["status"] == "accepted":
        _need(any(state["captures"][s]["origin"] == "user" for s in item["sources"]), "Accepted records need a user-origin source; an assistant proposal is not a user decision")
    if item["status"] == "deferred":
        _text(item["trigger"], "Deferred resurfacing trigger")
    if item["status"] in {"rejected", "superseded"}:
        _text(item["reason"], "Disposition reason")
    if item["status"] == "superseded":
        _id(item["replacement"])
        _need(item["replacement"] != item["id"], "Item cannot replace itself")


def _validate_state(state):
    for item in state["items"].values():
        _validate_item(state, item)
        if item["owner"] is not None:
            _get(state, "owners", item["owner"])
        if item["status"] == "superseded":
            _get(state, "items", item["replacement"])
    for item in state["work"].values():
        for field, category in [("requires", "items"), ("owners", "owners"), ("checks", "checks")]:
            for ident in item[field]:
                _get(state, category, ident)
    if state["current"]["next_work"] is not None:
        next_work = _get(state, "work", state["current"]["next_work"])
        _need(next_work["status"] != "done", "Current next work cannot point to completed work")
    def visit(ident, visiting, visited):
        _need(ident not in visiting, "Owner dependency cycle")
        if ident in visited:
            return
        owner = _get(state, "owners", ident)
        visiting.add(ident)
        for dependency in owner["requires"]:
            visit(dependency, visiting, visited)
        visiting.remove(ident)
        visited.add(ident)
    visited = set()
    for ident in state["owners"]:
        visit(ident, set(), visited)
    for ident in state["items"]:
        seen = set()
        item = state["items"][ident]
        while item["status"] == "superseded":
            _need(item["id"] not in seen, "Replacement cycle")
            seen.add(item["id"])
            item = state["items"][item["replacement"]]


def snapshot_from_ledger(ledger):
    _need(isinstance(ledger, dict) and set(ledger) == {"schema", "seed_version", "name", "repository", "events"}, "Unknown/malformed ledger schema")
    _need(type(ledger["schema"]) is int and ledger["schema"] == 1 and ledger["seed_version"] == VERSION, "Unsupported ledger version; do not auto-upgrade planted projects")
    _text(ledger["name"], "Project name")
    _text(ledger["repository"], "Repository", empty=True)
    _need(isinstance(ledger["events"], list), "events must be a list")
    state = _initial(ledger)
    previous = digest({k: v for k, v in ledger.items() if k != "events"})
    for number, event in enumerate(ledger["events"], 1):
        _need(isinstance(event, dict) and set(event) == {"revision", "previous", "operations", "digest"}, "Malformed event")
        _need(type(event["revision"]) is int and event["revision"] == number and event["previous"] == previous, "Broken event sequence or rewritten history")
        _need(event["digest"] == digest({k: v for k, v in event.items() if k != "digest"}), "Event digest mismatch")
        _need(isinstance(event["operations"], list) and event["operations"], "Empty/malformed event")
        for operation in event["operations"]:
            _apply_op(state, operation, internal=True)
        _validate_state(state)
        previous = event["digest"]
    return {"ledger": copy.deepcopy(ledger), "state": state, "revision": len(ledger["events"]), "digest": previous}


def _paths(root, state):
    for owner in state["owners"].values():
        _need(safe_path(root, owner["path"]).is_file(), f"Missing owner file: {owner['path']}")
    for definition in [*state["checks"].values(), *state["effects"].values()]:
        for relative in definition["inputs"]:
            safe_path(root, relative)


def load(root):
    root = Path(root).absolute()
    path = root / LEDGER
    _safe_ancestry(path)
    snapshot = snapshot_from_ledger(read_json(path))
    _paths(root, snapshot["state"])
    return snapshot


def validate(root):
    return load(root)


def snapshot_at(root, revision):
    ledger = load(root)["ledger"]
    _need(type(revision) is int and 0 <= revision <= len(ledger["events"]), "Unknown historical revision")
    ledger["events"] = ledger["events"][:revision]
    return snapshot_from_ledger(ledger)


def validate_parent(root, old_ledger):
    old = snapshot_from_ledger(old_ledger)
    new = load(root)
    _need({k: v for k, v in old_ledger.items() if k != "events"} == {k: v for k, v in new["ledger"].items() if k != "events"}, "Project identity or seed lineage changed")
    _need(len(new["ledger"]["events"]) >= old["revision"] and new["ledger"]["events"][:old["revision"]] == old_ledger["events"], "Committed event history was removed or rewritten; preserve both branches and reconcile")
    return new


def requirements_digest(state, check_id):
    """A pass is bound to declared requirements, not just unchanged code bytes."""
    selected = {i for i, item in state["items"].items() if item["global"] and item["status"] == "accepted"}
    work_scopes = []
    for ident, work in sorted(state["work"].items()):
        if check_id in work["checks"]:
            selected.update(work["requires"])
            work_scopes.append([ident, work["requires"], work["owners"], work["checks"]])
    return digest({"items": [state["items"][i] for i in sorted(selected)], "work": work_scopes})


def readiness(snapshot, root=None):
    state = snapshot["state"]
    problems = []
    for ident, capture in state["captures"].items():
        if capture["disposition"] == "pending":
            problems.append(f"Unprocessed capture: {ident}")
    for ident, effect in state["effects"].items():
        if effect["status"] in {"running", "returned"}:
            problems.append(f"Unresolved external effect: {ident}; inspect receipt/state before retrying")
        elif root is not None and effect["status"] in {"confirmed", "not_performed"}:
            try:
                if input_digest(root, [effect["receipt"]]) != effect["receipt_digest"]:
                    problems.append(f"Changed effect receipt: {ident}")
            except Error as exc:
                problems.append(str(exc))
    for ident, work in state["work"].items():
        if work["status"] != "done":
            continue
        if not work["checks"]:
            problems.append(f"Completed work has no check: {ident}")
        for check_id in work["checks"]:
            run = state["runs"].get(check_id)
            if not run or run["code"] != 0:
                problems.append(f"Missing/failed check for {ident}: {check_id}")
            elif run["requirements_digest"] != requirements_digest(state, check_id):
                problems.append(f"Stale check requirements: {check_id}; requirements changed since verification")
            elif root is not None:
                try:
                    if input_digest(root, state["checks"][check_id]["inputs"]) != run["input_digest"]:
                        problems.append(f"Stale check inputs: {check_id}; recheck or reopen the work")
                except Error as exc:
                    problems.append(str(exc))
    return problems


def _commit(root, old, operations, *, internal=False):
    state = copy.deepcopy(old["state"])
    operations = copy.deepcopy(operations)
    _need(isinstance(operations, list) and operations, "Supply a nonempty operations list")
    for op in operations:
        if isinstance(op, dict) and op.get("op") == "effect.add":
            _fields(op, ["id", "argv", "inputs", "description"])
            op["prepared_binding"] = input_digest(root, op["inputs"])
        if isinstance(op, dict) and op.get("op") == "effect.resolve":
            _fields(op, ["id", "outcome", "receipt"], ["receipt_digest"] if internal else [])
            _need("receipt_digest" not in op or internal, "Receipt digest is computed, not supplied")
            op["receipt_digest"] = input_digest(root, [op["receipt"]])
        if isinstance(op, dict) and op.get("op") == "effect.begin":
            definition = _get(state, "effects", op["id"])
            _need(op.get("binding") == input_digest(root, definition["inputs"]), "Operation input binding changed")
        _apply_op(state, op, internal=internal)
    _validate_state(state)
    _paths(root, state)
    provisional = {"state": state}
    if any(op.get("op") == "work.status" and op.get("status") == "done" for op in operations):
        problems = readiness(provisional, root)
        _need(not problems, "; ".join(problems))
    ledger = copy.deepcopy(old["ledger"])
    event = {"revision": old["revision"] + 1, "previous": old["digest"], "operations": operations}
    event["digest"] = digest(event)
    ledger["events"].append(event)
    snapshot = snapshot_from_ledger(ledger)
    atomic_write(Path(root) / LEDGER, json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
    return snapshot


def apply(root, operations, expected_revision, expected_digest):
    with project_lock(root):
        old = load(root)
        _need(type(expected_revision) is int and expected_revision == old["revision"] and expected_digest == old["digest"], "Stale revision or digest; reread and reconcile before writing")
        try:
            return _commit(root, old, operations)
        except (KeyError, TypeError, ValueError) as exc:
            raise Error(f"Malformed operation payload: {exc}") from exc


def initialize(root, name, repository=""):
    root = Path(root).absolute()
    _safe_ancestry(root)
    _text(name, "Project name")
    _text(repository, "Repository", empty=True)
    _need(not root.exists() or (root.is_dir() and not any(root.iterdir())), "Plant into a new empty directory; existing projects are never migrated")
    root.mkdir(parents=True, exist_ok=True)
    ledger = {"schema": 1, "seed_version": VERSION, "name": name, "repository": repository, "events": []}
    atomic_write(root / LEDGER, json.dumps(ledger, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return load(root)


def _execute(argv, root, timeout):
    try:
        # Persist a portable interpreter name, not this device's installation
        # path. Resolve only the executable token; never interpolate a shell.
        command = [sys.executable if argv[0] == "@python" else argv[0], *argv[1:]]
        # Bound memory even when a check is noisy. Full output remains a task's
        # responsibility; the continuity receipt keeps a labelled tail.
        with tempfile.TemporaryFile() as stream:
            result = subprocess.run(command, cwd=root, shell=False, stdout=stream, stderr=stream, timeout=timeout)
            length = stream.tell()
            stream.seek(max(0, length - 16000))
            output = stream.read().decode("utf-8", errors="replace")
            if length > 16000:
                output = "[output tail; earlier bytes omitted]\n" + output
        return result.returncode, output[-16000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def run_check(root, ident):
    before = load(root)
    definition = _get(before["state"], "checks", ident)
    binding = input_digest(root, definition["inputs"])
    code, output = _execute(definition["argv"], root, definition["timeout"])
    with project_lock(root):
        now = load(root)
        _need(now["digest"] == before["digest"] and input_digest(root, definition["inputs"]) == binding, "Project/inputs changed while check ran; result was not recorded as current")
        snapshot = _commit(root, now, [{"op": "_check.result", "id": ident, "code": code, "input_digest": binding,
                                       "requirements_digest": requirements_digest(now["state"], ident), "output": output}], internal=True)
    return {"id": ident, "code": code, "input_digest": binding, "output": output, "revision": snapshot["revision"]}


def run_effect(root, ident, timeout=60):
    before = load(root)
    definition = _get(before["state"], "effects", ident)
    binding = input_digest(root, definition["inputs"])
    # Persist uncertainty before a subprocess can possibly produce an effect.
    apply(root, [{"op": "effect.begin", "id": ident, "binding": binding}], before["revision"], before["digest"])
    code, output = _execute(definition["argv"], root, timeout)
    now = load(root)
    apply(root, [{"op": "effect.return", "id": ident, "code": code, "output": output}], now["revision"], now["digest"])
    return {"id": ident, "code": code, "status": "returned", "output": output,
            "next": "Inspect the external result and resolve with a receipt. Do not rerun this ID."}
