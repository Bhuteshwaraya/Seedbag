"""Deterministic views and bounded, relevant context from the canonical ledger.

Only the ledger is authoritative. Human edits to its generated views are refused,
not silently discarded. Context budgets cover the exact JSON response bytes,
including the final LF, as emitted by context_json().
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile

import seedbag_core as core


VIEW_NAMES = ("PROJECT.md", "STATE.md")
_MARKER = re.compile(
    rb"<!-- seedbag-generated:(PROJECT\.md|STATE\.md) revision=([0-9]+) "
    rb"digest=([0-9a-f]{64}) -->\n"
)
_LIVE = {"accepted", "proposed", "deferred", "open", "rejected"}


def _line(value) -> str:
    return " ".join(str(value).splitlines())


def _quoted(text: str) -> str:
    return "\n".join("> " + line for line in text.splitlines()) or "> (not recorded)"


def _item_text(identifier: str, item: dict, *, pointer_only: bool = False) -> str:
    lines = [f"### {identifier} — {item['status']} {item['kind']}"]
    if not pointer_only:
        lines.extend(["", _quoted(item["text"])])
    lines.append("")
    lines.append(f"Scope: {'global' if item.get('global', True) else 'selected work'}.")
    if item.get("owner"):
        lines.append(f"Owner: {item['owner']}.")
    if item.get("sources"):
        lines.append("Source capture IDs: " + ", ".join(item["sources"]) + ".")
    if item.get("trigger"):
        lines.append("Reconsider when: " + _line(item["trigger"]))
    if item.get("reason"):
        lines.append("Disposition reason: " + _line(item["reason"]))
    if item.get("replacement"):
        lines.append("Replaced by: " + str(item["replacement"]))
    return "\n".join(lines)


def _view_header(name: str, snapshot: dict) -> str:
    return (
        f"<!-- seedbag-generated:{name} revision={snapshot['revision']} "
        f"digest={snapshot['digest']} -->\n"
        "<!-- Derived from .seedbag/ledger.json. Use seedbag.py to record changes; "
        "do not edit this generated file by hand. -->\n"
    )


def _work_text(identifier: str, work: dict) -> str:
    lines = [f"### {identifier} — {work['status']}", "", _quoted(work["title"])]
    for key, label in (("requires", "Required items"), ("owners", "Owners"), ("checks", "Declared checks")):
        if work.get(key):
            lines.append(label + ": " + ", ".join(work[key]))
    if work.get("note"):
        lines.append("Note: " + _line(work["note"]))
    return "\n".join(lines)


def view_texts(snapshot: dict) -> dict[str, str]:
    """Render an already validated snapshot without accessing any owner files."""
    state = snapshot["state"]
    project = [
        _view_header("PROJECT.md", snapshot),
        "# " + _line(state["project"]["name"]),
        "",
        "## Purpose",
        "",
        _quoted(state["project"].get("purpose", "")),
        "",
        "## Current knowledge records",
        "",
        "Each record has one explicit disposition. Sources below are capture IDs, not replayed conversations.",
        "",
    ]
    for identifier, item in sorted(state["items"].items()):
        project.extend([_item_text(identifier, item), ""])
    if not state["items"]:
        project.extend(["No durable knowledge recorded yet.", ""])
    project.extend(["## Owner routes", "", "These are routes, not a requirement to read every file.", ""])
    for identifier, owner in sorted(state["owners"].items()):
        project.append(f"- {identifier}: `{owner['path']}` — {_line(owner['summary'])}")
        if owner.get("requires"):
            project.append("  Dependencies: " + ", ".join(owner["requires"]))
        if owner.get("tags"):
            project.append("  Tags: " + ", ".join(owner["tags"]))
    if not state["owners"]:
        project.append("No domain owners registered yet.")

    current = state["current"]
    progress = [
        _view_header("STATE.md", snapshot),
        "# Current state: " + _line(state["project"]["name"]),
        "",
        "## Current account",
        "",
        _quoted(current.get("summary", "")),
        "",
        "Next work: " + str(current.get("next_work") or "not selected"),
        "",
        "## Work and pending checks",
        "",
    ]
    for identifier, work in sorted(state["work"].items()):
        progress.extend([_work_text(identifier, work), ""])
    if not state["work"]:
        progress.extend(["No work registered yet.", ""])
    pending = sorted(identifier for identifier, capture in state["captures"].items()
                     if capture.get("disposition", "pending") == "pending")
    progress.extend([
        "## Capture reconciliation", "",
        "Pending capture IDs: " + (", ".join(pending) if pending else "none"),
        "Raw capture text remains in the ledger and is not repeated here.", "",
        "## Recorded verification evidence", "",
        "These are recorded outcomes. Freshness against current input files is checked separately.", "",
    ])
    for identifier in sorted(state["checks"]):
        run = state["runs"].get(identifier)
        if run is None:
            progress.append(f"- {identifier}: no recorded run")
        else:
            progress.append(f"- {identifier}: exit {run['code']}; input digest {run['input_digest']}")
    if not state["checks"]:
        progress.append("No checks declared.")
    progress.extend(["", "## Effect state", "", "A returned command is not evidence that its external effect was confirmed.", ""])
    for identifier, effect in sorted(state["effects"].items()):
        progress.append(f"- {identifier}: {effect['status']} — {_line(effect.get('description', ''))}")
        if effect.get("receipt"):
            progress.append("  Receipt: " + _line(effect["receipt"]))
    if not state["effects"]:
        progress.append("No effects registered.")
    progress.extend([
        "", "## Local and shared state", "",
        "This view cannot certify its own upload. Inspect Git status and verify the remote commit for a shared checkpoint.",
    ])
    return {
        "PROJECT.md": "\n".join(project).rstrip() + "\n",
        "STATE.md": "\n".join(progress).rstrip() + "\n",
    }


render_snapshot = view_texts


def _regular_view(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise core.Error(f"Generated view is not a regular unlinked file: {path.name}")
    return info


def _inspect_views(root: Path, snapshot: dict) -> dict[str, dict]:
    current = view_texts(snapshot)
    historical = {}
    result = {}
    for name in VIEW_NAMES:
        path = root / name
        info = _regular_view(path)
        if info is None:
            result[name] = {"status": "missing", "actual": None}
            continue
        # Inspect bounded metadata before loading a possibly handwritten large file.
        with path.open("rb") as source:
            marker = source.readline(256)
        match = _MARKER.fullmatch(marker)
        if match is None or match[1].decode("ascii") != name:
            raise core.Error(f"Generated view has unrecognized or handwritten content: {name}")
        revision = int(match[2])
        if revision > snapshot["revision"]:
            raise core.Error(f"Generated view names an unknown future revision: {name}")
        if revision == snapshot["revision"]:
            prior, expected = snapshot, current[name].encode("utf-8")
        else:
            if revision not in historical:
                historical[revision] = core.snapshot_at(root, revision)
            prior = historical[revision]
            expected = view_texts(prior)[name].encode("utf-8")
        if match[3].decode("ascii") != prior["digest"] or info.st_size != len(expected):
            raise core.Error(f"Generated view differs from its recorded ledger revision: {name}")
        actual = path.read_bytes()
        if actual != expected:
            raise core.Error(f"Generated view has handwritten changes: {name}")
        result[name] = {"status": "current" if revision == snapshot["revision"] else "stale", "actual": actual}
    return result


def check_views(root: Path) -> list[str]:
    """Return missing, stale, or modified-view problems; never alter files."""
    root = Path(root)
    snapshot = core.load(root)
    try:
        observed = _inspect_views(root, snapshot)
    except (core.Error, OSError) as exc:
        return [str(exc)]
    return [f"{name}: {value['status']} generated view" for name, value in observed.items()
            if value["status"] != "current"]


def _atomic_view(path: Path, data: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", prefix=".seedbag-view-", dir=path.parent, delete=False) as output:
            temporary = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def render(root: Path) -> dict:
    """Create views or repair exact older generated revisions; refuse manual edits."""
    root = Path(root)
    with core.project_lock(root):
        snapshot = core.load(root)
        observed = _inspect_views(root, snapshot)  # Preflight both before changing either.
        expected = view_texts(snapshot)
        changed = []
        for name in VIEW_NAMES:
            if observed[name]["status"] == "current":
                continue
            path = root / name
            info = _regular_view(path)
            now = None if info is None else path.read_bytes()
            if now != observed[name]["actual"]:
                raise core.Error(f"Generated view changed during rendering: {name}")
            _atomic_view(path, expected[name].encode("utf-8"))
            changed.append(name)
        return {"revision": snapshot["revision"], "digest": snapshot["digest"],
                "files": list(VIEW_NAMES), "repaired": changed}


def _owner_closure(state: dict, identifiers: set[str]) -> list[str]:
    visited, visiting, ordered = set(), set(), []

    def visit(identifier):
        if identifier in visiting:
            raise core.Error(f"Owner dependency cycle at {identifier}")
        if identifier in visited:
            return
        if identifier not in state["owners"]:
            raise core.Error(f"Missing owner: {identifier}")
        visiting.add(identifier)
        for dependency in sorted(state["owners"][identifier].get("requires", [])):
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)
        ordered.append(identifier)

    for identifier in sorted(identifiers):
        visit(identifier)
    return ordered


def context_json(result: dict) -> bytes:
    """The exact successful context output format, including one trailing LF."""
    return core.canonical(result) + b"\n"


def _with_output_bytes(result: dict) -> dict:
    result["bytes"] = 0
    for _ in range(16):
        actual = len(context_json(result))
        if result["bytes"] == actual:
            return result
        result["bytes"] = actual
    raise core.Error("Could not establish context output byte count")


def context(root: Path, work_id: str | None = None, budget: int = 24000) -> dict:
    """Select current global records and a work item's explicit owner closure.

    No owner body is read simply because it is registered or tagged relevant.
    Archives are therefore absent by default; a work dependency may deliberately
    require one. Raw captures and event history never enter this response.
    """
    if type(budget) is not int or budget <= 0:
        raise core.Error("Context budget must be a positive integer byte count")
    root = Path(root)
    snapshot = core.load(root)
    observed = _inspect_views(root, snapshot)
    state = snapshot["state"]
    selected = work_id if work_id is not None else state["current"].get("next_work")
    if selected is not None and selected not in state["work"]:
        raise core.Error(f"Unknown work item: {selected}")
    work = state["work"].get(selected)
    required = set(work.get("requires", [])) if work else set()
    owners = set(work.get("owners", [])) if work else set()
    for identifier in required:
        if identifier not in state["items"]:
            raise core.Error(f"Missing required knowledge item: {identifier}")
        if state["items"][identifier].get("owner"):
            owners.add(state["items"][identifier]["owner"])
    brief = [
        "# " + _line(state["project"]["name"]), "",
        "Purpose:", _quoted(state["project"].get("purpose", "")), "",
        "Current account:", _quoted(state["current"].get("summary", "")), "",
        "Selected work: " + str(selected or "none"), "",
        "Knowledge dispositions do not independently authorize external actions.", "",
    ]
    for identifier, item in sorted(state["items"].items()):
        is_global = item.get("global", True)
        if identifier in required or (is_global and item["status"] in _LIVE):
            brief.extend([_item_text(identifier, item), ""])
        elif is_global and item["status"] == "superseded":
            brief.extend([_item_text(identifier, item, pointer_only=True), ""])
    if work:
        brief.extend([_work_text(selected, work), ""])
    pending = sorted(identifier for identifier, capture in state["captures"].items()
                     if capture.get("disposition", "pending") == "pending")
    if pending:
        brief.extend(["Pending capture IDs requiring reconciliation: " + ", ".join(pending), ""])
    effects = [f"{identifier}: {effect['status']}" for identifier, effect in sorted(state["effects"].items())
               if effect["status"] in {"running", "returned"}]
    if effects:
        brief.extend(["Unresolved external effects (do not retry): " + "; ".join(effects), ""])
    selected_owners = []
    for identifier in _owner_closure(state, owners):
        owner = state["owners"][identifier]
        path = core.safe_path(root, owner["path"])
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeError as exc:
            raise core.Error(f"Selected context owner is not UTF-8 text: {owner['path']}") from exc
        selected_owners.append({"id": identifier, "path": owner["path"], "summary": owner["summary"], "text": text})
    readiness_problems = core.readiness(snapshot, root)
    result = _with_output_bytes({
        "revision": snapshot["revision"], "digest": snapshot["digest"],
        "status": "ready", "overflow": False, "work_id": selected,
        "brief": "\n".join(brief).rstrip() + "\n", "owners": selected_owners,
        "checkpoint_ready": not readiness_problems,
        "readiness_problems": readiness_problems,
        "views_need_render": [name for name, value in observed.items() if value["status"] != "current"],
    })
    if result["bytes"] > budget:
        return _with_output_bytes({
            "revision": snapshot["revision"], "digest": snapshot["digest"],
            "status": "blocked", "overflow": True, "required_bytes": result["bytes"], "budget": budget,
            "reason": "Context exceeds the explicit byte budget. No partial context was emitted; revise the work routes or explicitly raise the budget.",
        })
    return result
