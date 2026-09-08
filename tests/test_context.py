"""Context and generated-view failure cases, all inside disposable new projects."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import seedbag_core as core
import seedbag_context as context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".seedbag").mkdir()
        self.ledger = self.root / ".seedbag" / "ledger.json"
        self.ledger.write_bytes(core.canonical({
            "schema": 1, "seed_version": "0.3.0", "name": "New context trial — résumé",
            "repository": "", "events": [],
        }) + b"\n")

    def apply(self, *operations):
        before = core.load(self.root)
        return core.apply(self.root, list(operations), before["revision"], before["digest"])

    def file(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def capture(self, identifier="turn", text="Raw transcript detail that is not startup context"):
        self.apply({"op": "capture.add", "id": identifier, "text": text,
                    "origin": "user", "locator": "test:user-turn"})

    def item(self, identifier, text, status="accepted", **fields):
        return {"op": "item.add", "id": identifier, "kind": "requirement", "text": text,
                "status": status, "sources": ["turn"], **fields}

    def owner(self, identifier, path, dependencies=(), tags=()):
        return {"op": "owner.add", "id": identifier, "path": path,
                "summary": "Owner of " + identifier, "tags": list(tags), "requires": list(dependencies)}

    def work(self, identifier="draft", requirements=(), owners=()):
        return {"op": "work.add", "id": identifier, "title": "Prepare the current draft",
                "requires": list(requirements), "owners": list(owners), "checks": []}

    def test_selected_work_reads_its_dependency_closure_but_not_archive_or_raw_capture(self):
        self.file("domain/base.md", "Shared domain evidence — 共通\n")
        self.file("domain/current.md", "Current feature detail\n")
        archive = self.file("archive/old.md", "ARCHIVE BODY MUST NOT BE READ\n" * 5000)
        self.capture(text="RAW CAPTURE MUST NOT APPEAR IN CONTEXT")
        self.apply(
            self.owner("base", "domain/base.md"),
            self.owner("feature", "domain/current.md", ("base",)),
            self.owner("old", "archive/old.md", tags=("archive",)),
            self.item("offline", "Always preserve offline operation."),
            self.item("feature_rule", "Use the current feature owner.", **{"global": False, "owner": "feature"}),
            self.work(requirements=("feature_rule",)),
            {"op": "current.set", "summary": "A feature draft is pending.", "next_work": "draft"},
            {"op": "capture.resolve", "id": "turn", "items": ["offline", "feature_rule"], "reason": "Requirements recorded"},
        )
        original = Path.read_bytes
        reads = []

        def observed(path):
            reads.append(path)
            if path == archive:
                raise AssertionError("Unrelated archive was read")
            return original(path)

        with patch.object(Path, "read_bytes", observed):
            result = context.context(self.root)
        self.assertFalse(result["overflow"])
        self.assertEqual([owner["id"] for owner in result["owners"]], ["base", "feature"])
        self.assertIn("Always preserve offline operation", result["brief"])
        self.assertIn(self.root / "domain/base.md", reads)
        self.assertNotIn("RAW CAPTURE", context.context_json(result).decode("utf-8"))
        self.assertNotIn("ARCHIVE BODY", context.context_json(result).decode("utf-8"))

    def test_without_selected_work_registered_owner_bodies_are_not_default_context(self):
        owner_file = self.file("archive/old.md", "Old superseded conversation archive")
        self.apply(self.owner("old", "archive/old.md", tags=("archive",)))
        original = Path.read_bytes

        def observed(path):
            if path == owner_file:
                raise AssertionError("Default context loaded an unselected registered owner")
            return original(path)

        with patch.object(Path, "read_bytes", observed):
            result = context.context(self.root)
        self.assertEqual(result["owners"], [])

    def test_selected_archive_is_loaded_only_through_deliberate_work_requirement(self):
        self.file("archive/decision.md", "Original decision needed for this specific investigation.")
        self.apply(self.owner("history", "archive/decision.md", tags=("archive",)),
                   self.work("investigate", owners=("history",)))
        self.assertEqual(context.context(self.root)["owners"], [])
        chosen = context.context(self.root, work_id="investigate")
        self.assertEqual(chosen["owners"][0]["id"], "history")
        self.assertIn("specific investigation", chosen["owners"][0]["text"])

    def test_budget_counts_actual_utf8_json_and_exact_boundary_without_losing_global_constraint(self):
        self.capture()
        self.apply(self.item("global_rule", "離線で使用 — preserve café names 🌱."),
                   {"op": "capture.resolve", "id": "turn", "items": ["global_rule"], "reason": "Recorded"})
        complete = context.context(self.root, budget=100000)
        actual = context.context_json(complete)
        self.assertEqual(complete["bytes"], len(actual))
        self.assertGreater(len(actual), len(actual.decode("utf-8")))
        boundary = context.context(self.root, budget=len(actual))
        self.assertEqual(boundary, complete)
        refused = context.context(self.root, budget=len(actual) - 1)
        self.assertTrue(refused["overflow"])
        self.assertEqual(refused["required_bytes"], len(actual))
        self.assertEqual(refused["status"], "blocked")
        self.assertNotIn("brief", refused)
        self.assertNotIn("owners", refused)

    def test_large_required_owner_blocks_instead_of_truncating_or_excluding_it(self):
        self.file("domain/large.md", "Large but explicitly required evidence.\n" * 2000)
        self.apply(self.owner("large", "domain/large.md"), self.work(owners=("large",)))
        result = context.context(self.root, work_id="draft", budget=2000)
        self.assertTrue(result["overflow"])
        self.assertGreater(result["required_bytes"], 70000)
        self.assertNotIn("brief", result)
        self.assertNotIn("owners", result)

    def test_accepted_deferred_open_proposed_and_rejected_global_records_keep_dispositions(self):
        self.capture()
        self.apply(
            self.item("accepted", "Must use plain language."),
            self.item("deferred", "Print support later.", "deferred", trigger="A printer is requested"),
            self.item("open", "Source license unresolved.", "open"),
            self.item("proposal", "Online search is only proposed.", "proposed"),
            self.item("rejected", "Do not restore the rejected cards.", "rejected", reason="User chose a list"),
        )
        result = context.context(self.root)
        for phrase in ["accepted requirement", "deferred requirement", "open requirement", "proposed requirement", "rejected requirement", "A printer is requested", "User chose a list"]:
            self.assertIn(phrase, result["brief"])

    def test_invalid_dependency_and_path_refuse_before_any_context_file_read(self):
        self.file("domain/a.md", "A")
        self.file("domain/b.md", "B")
        before = self.ledger.read_bytes()
        with self.assertRaises(core.Error):
            self.apply(self.owner("a", "domain/a.md", ("b",)), self.owner("b", "domain/b.md", ("a",)))
        self.assertEqual(self.ledger.read_bytes(), before)
        with self.assertRaises(core.Error):
            self.apply(self.owner("escape", "../outside.md"))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_non_utf8_selected_owner_is_an_explicit_refusal(self):
        self.file("domain/binary.md", "temporary").write_bytes(b"\xff\xfe\x00")
        self.apply(self.owner("binary", "domain/binary.md"), self.work(owners=("binary",)))
        with self.assertRaisesRegex(core.Error, "UTF-8"):
            context.context(self.root, work_id="draft")


class GeneratedViewTests(unittest.TestCase):
    setUp = ContextTests.setUp
    apply = ContextTests.apply
    file = ContextTests.file

    def test_real_handwritten_constraint_is_preserved_and_blocks_context_and_render(self):
        context.render(self.root)
        self.apply({"op": "project.set", "purpose": "A changed canonical purpose"})
        project = self.root / "PROJECT.md"
        project.write_bytes(project.read_bytes() + b"\nMust also work without a keyboard.\n")
        state_before = (self.root / "STATE.md").read_bytes()
        project_before = project.read_bytes()
        self.assertTrue(context.check_views(self.root))
        with self.assertRaises(core.Error):
            context.render(self.root)
        with self.assertRaises(core.Error):
            context.context(self.root)
        self.assertEqual(project.read_bytes(), project_before)
        self.assertEqual((self.root / "STATE.md").read_bytes(), state_before)

    def test_forged_valid_old_header_does_not_authorize_overwriting_edited_body(self):
        context.render(self.root)
        project = self.root / "PROJECT.md"
        data = project.read_bytes()
        # Same byte length and a genuine old marker: header/digest checks alone fail this case.
        self.assertIn(b"not recorded", data)
        edited = data.replace(b"not recorded", b"new decision", 1)
        self.assertEqual(len(data), len(edited))
        project.write_bytes(edited)
        self.apply({"op": "project.set", "purpose": "New ledger revision"})
        with self.assertRaisesRegex(core.Error, "handwritten"):
            context.render(self.root)
        self.assertEqual(project.read_bytes(), edited)

    def test_crash_between_two_view_writes_repairs_exact_older_revision(self):
        first = core.load(self.root)
        context.render(self.root)
        original_state = (self.root / "STATE.md").read_bytes()
        current = self.apply({"op": "project.set", "purpose": "Survive a mid-render interruption"})
        expected = context.view_texts(current)
        # Simulate the first atomic write succeeding and the process dying before the second.
        (self.root / "PROJECT.md").write_bytes(expected["PROJECT.md"].encode("utf-8"))
        self.assertEqual(original_state, context.view_texts(first)["STATE.md"].encode("utf-8"))
        self.assertEqual(context.check_views(self.root), ["STATE.md: stale generated view"])
        outcome = context.render(self.root)
        self.assertEqual(outcome["repaired"], ["STATE.md"])
        self.assertEqual(context.check_views(self.root), [])
        self.assertEqual((self.root / "STATE.md").read_bytes(), expected["STATE.md"].encode("utf-8"))

    def test_missing_view_can_be_recreated_without_rewriting_current_view(self):
        context.render(self.root)
        project = self.root / "PROJECT.md"
        original = project.read_bytes()
        (self.root / "STATE.md").unlink()
        self.assertEqual(context.render(self.root)["repaired"], ["STATE.md"])
        self.assertEqual(project.read_bytes(), original)

    def test_user_file_is_not_replaced_even_when_other_view_is_missing(self):
        self.file("STATE.md", "My existing handwritten current state.\n")
        with self.assertRaises(core.Error):
            context.render(self.root)
        self.assertFalse((self.root / "PROJECT.md").exists())
        self.assertEqual((self.root / "STATE.md").read_text(), "My existing handwritten current state.\n")

    def test_views_and_context_do_not_replay_raw_capture_or_old_purpose_events(self):
        self.apply({"op": "project.set", "purpose": "OBSOLETE PURPOSE NOT CURRENT"})
        self.apply({"op": "capture.add", "id": "raw", "text": "SECRET RAW TRANSCRIPT",
                    "origin": "user", "locator": "test:turn"},
                   {"op": "project.set", "purpose": "Current concise purpose"})
        context.render(self.root)
        for name in context.VIEW_NAMES:
            text = (self.root / name).read_text(encoding="utf-8")
            self.assertNotIn("SECRET RAW TRANSCRIPT", text)
            self.assertNotIn("OBSOLETE PURPOSE NOT CURRENT", text)
        rendered = context.context_json(context.context(self.root)).decode("utf-8")
        self.assertNotIn("SECRET RAW TRANSCRIPT", rendered)
        self.assertNotIn("OBSOLETE PURPOSE NOT CURRENT", rendered)
        self.assertIn("raw", rendered)


if __name__ == "__main__":
    unittest.main()
