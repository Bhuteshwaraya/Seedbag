# Seedbag 0.3.3 operations — for the assistant

The person starts with the creation prompt in README.md. Read START_HERE.md for your setup and routing duties. The commands below are for you to execute through available tools, never a checklist to assign to a person who asked you to handle setup. You also own obtaining the package, locating an available interpreter, Git setup, and a complete handoff when this application lacks the necessary capabilities.

If dependencies or account access are missing, follow FIRST_RUN.md before deciding that a handoff is necessary. The standalone `python -B seedbag_setup.py --offline` discovers local tools without authentication or network calls. `python -B seedbag_setup.py --network --repository https://github.com/OWNER/PROJECT` adds CLI identity and ordinary Git read probes; substitute the actual project URL when continuing an existing project. Exit zero means the probes ran, not that setup succeeded: inspect the JSON statuses and the limits listed in `not_proven`. Host connector permissions remain unknown to this local helper. It never installs, logs in, creates repositories, changes settings, or proves a private push.

This reference is for an assistant operating a **newly planted future project** in an AI application with project-file access and Python execution. The person directing it can speak normally; the assistant handles commands and structured records. Read `AGENTS.md` explicitly if the application does not load it automatically. Translate meaningful input using the person's actual request and existing authorization; recorded provenance is not a repeated permission ritual.

The **initiator** is the person currently directing the AI. The intended beneficiary may instead be another person, team, organization, or client. `init --name` supplies a project label, not an initiator or beneficiary identity. Preserve relevant roles and attribution when supplied; do not insert a default personal name or infer one from the seed author, account, or filesystem. There is no required identity-registration step. If the initiator relays someone else's request, preserve that attribution without claiming direct approval from the other person. Capture origins are provenance labels, not an identity or role-permission system.

Run commands inside the planted project. `python` below means an installed Python 3.11+ executable; check `python --version` and substitute `python3` or an available `py -3.11` launcher when appropriate. To target a project from elsewhere, put the global option before the command: `python /path/to/project/seedbag.py --root /path/to/project context`. The paths are placeholders for the actual project location.

## Files and authority

`.seedbag/ledger.json` is the canonical continuity state. Each validated transaction appends a revision linked to the previous digest. `PROJECT.md` and `STATE.md` are deterministic views of that ledger. The product itself remains in ordinary domain files, code, and artifacts; the ledger routes the assistant to those files rather than copying all of them into every continuation.

`README.md` is the planted project's human recovery page. It links goals, progress, and the permanent prompt in `CONTINUE_HERE.md`. The installer generates both entry files from the same paragraph. Their marked prompt blocks must match; the continuation locator must identify the repository recorded in the ledger. `doctor`, the staged gate, and committed audits check required project files and those blocks. Snapshot audits also preserve the entire continuation file against ledger-bearing parents. The README prose outside its prompt block may develop with the project. Repository relocation has no supported migration command in this release; do not rewrite the entry during ordinary work.

Use the same files in this project's working directory and its own Git repository. Unpushed changes exist only on that device. Different branches are candidate histories of the same project; neither location nor recency establishes acceptance. The original seed repository is only the planting source. There are no automatic upgrades or migration commands.

Creation can run in a temporary cloud workspace with Python, Git, and authorized private publication. Verify a complete remote checkpoint before calling that setup durable; report computer-local availability separately. On a later computer, inspect a matching existing folder or clone the same repository into a new empty destination using ordinary Git. Verify the selected commit and project identity, inspect the installed program, run its own `context` and `doctor`, and install its local hook. Do not run `init` to resume. A connector download can provide a verified read-only snapshot, but is not a Git checkout or proof of writable synchronization.

`.seedbag-local/` contains local working state such as the advisory lock and is ignored by Git. The default `.gitattributes` preserves exact bytes (`* -text`), because automatic newline conversion can invalidate evidence between the working directory, staged snapshot, and another device. Reconsider that policy only together with its effect on byte-bound checks.

## Command reference

| Command | Actual behavior |
| --- | --- |
| `init DEST --name NAME [--repository URL] [--no-git]` | Plants into a new or empty directory. NAME labels the project, not a person. Copies the runtime and instructions, initializes the ledger, and renders views. By default initializes Git `main` and installs a local hook. `--no-git` leaves files local. URL is a recorded locator only. |
| `capture --file FILE --id ID --origin user\|assistant\|source --locator TEXT` | Reads UTF-8 text, accepts an optional BOM, saves the decoded text as a pending immutable capture, and renders views. FILE can be an external temporary text file. No host transcript is fetched. |
| `apply --file FILE` | Applies an explicit JSON transaction against its expected revision/digest, then renders views. No direct event editing. |
| `inspect [--kind KIND] [--id ID]` | Returns a current record or category with the current revision/digest. Default kind is `current`. |
| `context [--work ID] [--budget BYTES]` | Emits bounded relevant context; defaults to the current `next_work` and 24,000 actual UTF-8 output bytes. It performs no remote fetch. |
| `render` | Creates missing views or repairs an exact recognizable older generated revision. Refuses handwritten or unrecognized content. |
| `doctor` | Validates the ledger, current generated views, pending captures/effects, and evidence for work marked done. Does not execute checks. |
| `check ID` | Executes the declared command in the project directory, then records its result only if the ledger and declared input bytes remained unchanged. |
| `status [--fetch]` | Reports dirty files, local commit, ahead/behind/divergence, cached/shared-reference freshness, and candidate branch metadata. `--fetch` fetches configured remotes. |
| `candidate REF` | Reads `STATE.md` at an exact remote-tracking ref discovered through status, without checkout or promotion. This is candidate text, not validation of the candidate's claims. |
| `publish --message TEXT --paths FILE... [--remote NAME] [--branch NAME] [--incomplete]` | Stages exact intended files, validates the staged snapshot, commits when needed, fetches, performs a normal push, and reads back the exact remote tip. Defaults to remote `origin` and the current local branch name. |
| `gate [--incomplete]` | Checks the full staged Git index, including generated views, referenced files, current completion evidence, and preserved committed ledger history. Does not commit. |
| `audit --base REF [--commit REF] [--incomplete]` | Audits a committed snapshot against an explicit base and its immediate parents without checkout. Commit defaults to `HEAD`. Useful for a reviewer or a configured CI job; running it does not install remote CI or branch protection. |
| `install-hook` | Installs an optional local pre-commit gate using this project's runtime and the current Python executable. Refuses to overwrite an existing hook or configured hooks path. |
| `effect-run ID [--timeout SECONDS]` | Persists an attempt before running the declared, already authorized command. A returned command remains unresolved until its external outcome is inspected. Default timeout 60 seconds; valid range 1–300. |
| `effect-resolve ID --receipt FILE --outcome confirmed\|not_performed` | Records the inspected outcome and exact receipt-file binding for a running/returned attempt. Does not rerun it. |

Inspection kinds are `project`, `captures`, `items`, `owners`, `work`, `checks`, `runs`, `effects`, and `current`. Commands normally emit one JSON result. Exit 2 indicates a refusal, failed check, context overflow, or unresolved effect execution. In particular, `effect-run` deliberately exits 2 even if its subprocess returned zero. Inspect the JSON, not the exit status alone.

## Resume and retrieve only what is relevant

```sh
python seedbag.py context
python seedbag.py inspect --kind current
python seedbag.py inspect --kind captures --id request_001
python seedbag.py inspect --kind items --id offline
python seedbag.py inspect --kind owners --id display
python seedbag.py context --work build_index --budget 32000
```

`context` includes current global accepted, proposed, deferred, open, and rejected records, plus superseded-global replacement pointers. It includes records explicitly required by the selected work and follows that work's explicit owner routes and transitive owner dependencies. Tags do not trigger automatic document loading. Without selected work, registered document bodies are not loaded by default. An archive can be read if deliberately registered and required; ordinary continuation does not scan archives or replay raw captures into model context.

The successful response's `bytes` counts the entire emitted JSON including metadata and its trailing newline. Overflow returns a concise blocked result with `required_bytes`; no partial content is emitted. Select a genuinely narrower work route, inspect a named record, or explicitly raise the budget. Do not demote a global requirement just to make the output fit. `status: ready` here means context was assembled within budget. The separate `checkpoint_ready` and `readiness_problems` fields report current ledger/evidence readiness, including stale completed checks and uncertain effects. Also act on `views_need_render`; `doctor` checks generated-view problems together with readiness. None of these fields establishes overall project completion or user acceptance.

Read a capture with `inspect --kind captures --id ID` to retrieve its original saved text and disposition. `inspect --kind captures` returns the whole category and can be large. There is no separate archive-search command. Full historical operations remain in `.seedbag/ledger.json`; inspect the specific event or a prior Git snapshot read-only when lineage matters. A source locator is descriptive text, not an automatic fetch connector. Read a named owner file through ordinary file tools after inspecting its route.

At a device handoff with network access:

```sh
python seedbag.py status --fetch
python seedbag.py candidate refs/remotes/origin/candidate-layout
```

Use an actual ref from status, not the illustrative name above. Metadata is limited to the first 100 candidate refs; `candidate_count` and `candidate_overflow` disclose a larger set, which requires deliberate Git inspection. Cached references without fetch are not proof of the live remote. Compare relevant candidate content and changes before deciding where to resume. No candidate is automatically accepted.

## Capture first, then record meaning

Suppose the user actually says: “Build an offline index. Start with cards. Printing can wait until paper copies are requested.” Save that exact relevant text in a UTF-8 temporary file, then:

```sh
python seedbag.py capture --file /path/to/request.txt --id request_001 --origin user --locator "Current user request: offline index"
python seedbag.py inspect
```

Use unique IDs beginning with a letter, followed by letters, digits, underscores, or hyphens; maximum length is 64. A capture is pending until explicitly reconciled. The schema's `user` origin refers to actual input from the person directing the AI, without assuming a particular identity or beneficiary. Do not label assistant ideas or fetched text as user input.

An apply file has **exactly** the three top-level fields shown below. Replace the illustrative revision and digest with the latest `inspect` or `context` values before applying. The assistant prepares this file; the user does not need to edit JSON.

```json
{
  "expected_revision": 1,
  "expected_digest": "REPLACE_WITH_CURRENT_DIGEST",
  "operations": [
    {"op": "project.set", "purpose": "Create a useful local index."},
    {"op": "item.add", "id": "offline", "kind": "requirement", "text": "The index must work offline.", "status": "accepted", "sources": ["request_001"]},
    {"op": "item.add", "id": "cards", "kind": "decision", "text": "Start with a card presentation.", "status": "accepted", "sources": ["request_001"]},
    {"op": "item.add", "id": "printing", "kind": "idea", "text": "Support printing later.", "status": "deferred", "trigger": "Paper copies are requested", "sources": ["request_001"]},
    {"op": "capture.resolve", "id": "request_001", "items": ["offline", "cards", "printing"], "reason": "Recorded the constraint, initial direction, and deferred trigger."},
    {"op": "current.set", "summary": "Initial scope recorded; implementation is not yet planned.", "next_work": null}
  ]
}
```

```sh
python seedbag.py apply --file /path/to/transaction.json
```

A stale revision/digest refuses the transaction. Reread and reconcile the competing change; do not just substitute a new digest without reviewing it. Operations are processed in order, with final reference/path validation. A capture's linked items must cite that capture. `items: []` is permitted with an explicit reason when there was no durable content; it is not a way to dismiss a substantive requirement.

If the assistant proposes an alternative, capture it with origin `assistant` and store the item as `proposed`. An accepted item must cite at least one user-origin capture. That mechanical condition does not establish that the cited text actually approved the proposal. Use existing genuine authorization without inventing a fresh approval requirement.

## Exact transaction operation fields

Every object includes `op`. Fields below are required unless described as optional. Unknown fields are rejected.

| Operation | Fields and rules |
| --- | --- |
| `capture.add` | `id`, `text`, `origin`, `locator`. Same record shape as the capture command; text is immutable. |
| `capture.resolve` | `id`, `items` (item-ID list), `reason`. Resolves a pending capture once. |
| `project.set` | `purpose`. Replaces the current purpose while preserving the old event. Requirements belong in named items. |
| `item.add` | `id`, `kind`, `text`, `status`, nonempty `sources` (capture IDs). Optional `global` (default true), `owner` (default null), `trigger` and `reason` (default empty), `replacement` (default null). Text is immutable. |
| `item.status` | `id`, `status`, `reason`, `source` (a user-origin capture ID). Optional `replacement`, `trigger`. Status must change. The source is added to the item's provenance. |
| `item.route` | `id`, `global` (boolean), `owner` (owner ID or null), `reason`. A non-global item must have an owner route. Changes routing without rewriting its text. |
| `owner.add` | `id`, `path`, `summary`, `tags` (text list), `requires` (owner-ID list). One owner per file, no dependency cycles. Owner files must exist by transaction validation. |
| `owner.move` | `id`, `path`, `reason`. Changes a route to an existing file; does not move the file itself. |
| `work.add` | `id`, `title`, `requires` (item IDs), `owners` (owner IDs), `checks` (check IDs). Starts as `planned`. |
| `work.revise` | `id`, `requires`, `owners`, `checks`, `reason`. Replaces those scope lists and sets status to `planned`. Reopen done work first. |
| `work.status` | `id`, `status`, `note`. Status is `planned`, `in_progress`, `blocked`, or `done`. Done has evidence requirements below. |
| `current.set` | `summary`, `next_work` (work ID or null). The single current account; next work cannot be done. |
| `check.add` | `id`, `argv` (argument list), `inputs` (nonempty exact relative file list), `timeout` (integer 1–300). Definitions are immutable; use a new check ID and revise affected work to change a definition. |
| `effect.add` | `id`, `argv`, `inputs` (nonempty exact relative file list), `description`. Computes the prepared input binding itself. Do not supply `prepared_binding`. |
| `effect.resolve` | `id`, `outcome` (`confirmed` or `not_performed`), `receipt` (relative existing file). Computes the receipt binding itself; do not supply `receipt_digest`. Prefer the CLI wrapper. |

Item kinds: `requirement`, `decision`, `idea`, `fact`, `question`. Item statuses: `proposed`, `accepted`, `deferred`, `open`, `rejected`, `superseded`. Deferred items require a nonempty trigger. Rejected and superseded items require a reason. Superseded items also require an existing replacement item; replacement cycles are rejected.

The check runner owns `_check.result`; `apply` cannot manufacture a passing result. The effect runner writes `effect.begin` and `effect.return`; operate that lifecycle through `effect-run`, not handwritten attempt/outcome events.

Use normalized project-relative paths with forward slashes. Owner/check/effect inputs must stay inside the project; reserved `.git`, `.seedbag`, and `.seedbag-local` paths and linked/reparse paths are rejected. Checks name individual files, not directories or globs. Domain owners cannot be generated views or instruction files. Selected owner content must be UTF-8 text.

## Rewrite a plan without erasing its history

If the user subsequently requests plain list lines instead of cards, first capture that request as `correction_001`. Then put these operations in a new transaction using the latest revision/digest:

```json
[
  {"op": "item.add", "id": "list_lines", "kind": "decision", "text": "Use plain list lines.", "status": "accepted", "sources": ["correction_001"]},
  {"op": "item.status", "id": "cards", "status": "superseded", "source": "correction_001", "reason": "The user selected a plain list.", "replacement": "list_lines"},
  {"op": "capture.resolve", "id": "correction_001", "items": ["cards", "list_lines"], "reason": "Explicitly replaced the old display direction."}
]
```

This is the `operations` array, not a complete apply file. The offline requirement and printing trigger remain. Revise relevant work to require the replacement and rerun affected verification before renewing completion claims. There is no delete-record operation.

As the domain grows, add real owner documents, route genuinely scoped records to them with `item.route`, and use `work.revise` to name each work item's required knowledge and files. Core global requirements should remain global. The runtime follows explicit routes; it cannot infer that a poorly chosen work scope missed a necessary domain record.

## Declare and run meaningful verification

Create the domain document, implementation, and check script first. For example, after `domain/display.md`, `indexer.py`, and `checks/verify_index.py` exist, the following operations register a scoped work item:

```json
[
  {"op": "owner.add", "id": "display", "path": "domain/display.md", "summary": "Current display behavior and acceptance examples", "tags": ["display"], "requires": []},
  {"op": "check.add", "id": "verify_index", "argv": ["@python", "checks/verify_index.py"], "inputs": ["indexer.py", "checks/verify_index.py", "domain/display.md"], "timeout": 30},
  {"op": "work.add", "id": "build_index", "title": "Implement and verify the index", "requires": ["offline", "list_lines"], "owners": ["display"], "checks": ["verify_index"]},
  {"op": "current.set", "summary": "Implementing the corrected index behavior.", "next_work": "build_index"}
]
```

`@python` is supported in the executable position (`argv[0]`) and resolves to the Python interpreter running Seedbag on the current device. Other arguments are literal, and commands run without a shell in the project directory. Using an absolute executable path instead ties that definition to a machine. Declared commands run with normal host permissions; this is not a sandbox or a permission grant.

```sh
python seedbag.py check verify_index
python seedbag.py inspect --kind runs --id verify_index
```

Choose a check that exercises actual behavior and name every file that affects its claim, including test data and any output artifact being certified. Generate an artifact before the check if that artifact is an input: changing declared inputs during the run prevents the result from being recorded as current. Only a bounded output tail is stored; preserve a full report as a separate artifact when needed.

The pass is bound to exact input bytes, accepted global records, and the required item/scope records of work using that check. A later relevant requirement or input change invalidates the completion evidence. A check that forgot an input or tested the wrong behavior can still be weak; hashes cannot establish semantic coverage.

After passing evidence is current, mark the work done and clear or advance `next_work` in the same transaction:

```json
[
  {"op": "current.set", "summary": "Index implementation verified; printing remains deferred.", "next_work": null},
  {"op": "work.status", "id": "build_index", "status": "done", "note": "Behavioral checks passed on the current declared inputs."}
]
```

Done work needs at least one declared check, all its checks passing and current, no pending captures, and no unresolved running/returned effects. Other done work with stale evidence can also block a new completion transaction. Reopen affected work or recheck it honestly. A text note alone cannot establish completion.

## Local saves, checkpoints, and interrupted work

Successful capture/apply/check operations save locally. They do not upload anything. A regular `publish` requires reconciled captures and effects plus valid evidence for work already marked done. Planned, in-progress, or blocked work can remain; a regular checkpoint is not a certificate that the entire project is finished.

For a newly planted project, the first publication needs the complete planted program and state. An illustrative initial file list is:

```sh
python seedbag.py publish --message "Initial project checkpoint" --paths seedbag.py seedbag_setup.py FIRST_RUN.md SEEDBAG_LICENSE.txt AGENTS.md PROJECT.md STATE.md README.md CONTINUE_HERE.md .gitignore .gitattributes .seedbag/ledger.json .seedbag/runtime/seedbag_core.py .seedbag/runtime/seedbag_context.py .seedbag/runtime/seedbag_git.py
```

Add every registered owner, required input, receipt, and intended domain file that exists in your actual project. This command requires an already configured remote. For later checkpoints, name the intended changed files; already committed unchanged files remain in the staged snapshot. Directories, duplicate paths, unresolved Git conflicts, unrelated pre-staged files, and mismatched staged/working versions of an intended file are refused. Review the index after any failed publication: files may already have been staged or committed locally before a network refusal.

For an interruption with unprocessed capture text or an uncertain external attempt, use an explicitly incomplete savepoint:

```sh
python seedbag.py publish --incomplete --message "Savepoint: request still pending" --paths .seedbag/ledger.json PROJECT.md STATE.md
```

Use the full initial list if this is the first publication, plus any needed domain files. `--incomplete` permits pending captures and unresolved running/returned effects, reports `snapshot_only: true`, and preserves readiness warnings. It does **not** waive malformed history, invalid generated views, changed receipts, or stale/missing checks for work claiming to be done. An unresolved effect remains a do-not-retry record on resume.

For a local commit without sharing, use ordinary Git staging and commit commands. Run `python seedbag.py gate` after staging if the optional hook is absent. `gate --incomplete` checks an interrupted snapshot, but does not automatically configure a later ordinary `git commit`; the installed hook defaults to the regular gate. The normal interrupted publication path above handles its hook flag itself.

Publication never force-pushes, automatically merges, resets, or discards another branch. If a shared branch is ahead or divergent, the local commit is preserved and publication stops. The guard preserves the exact ledger prefix of every immediate merge parent. Consequently, independently diverged event ledgers cannot be joined by a two-parent merge, even after manually resolving their JSON. Code-only merges or ledgers whose histories remain prefix-compatible can pass. For divergent ledgers, preserve the separate candidate branch, review its intent and provenance, and explicitly record the selected changes as new transactions in the chosen lineage. Do not claim the original competing events were merged. This version supports portable checkpoints with one active writer, not automatic distributed reconciliation.

## Hooks and committed-snapshot auditing

Planting with Git installs the local hook; cloning does not copy Git hooks. After cloning, `install-hook` binds a new hook to that clone's runtime and this device's Python. Existing hooks and `core.hooksPath` are preserved by refusal. Integrate `python seedbag.py gate` explicitly into an existing hook/workflow if desired. To start without a hook, plant with `--no-git`, then initialize ordinary Git yourself; do not assume an unimplemented `--no-hook` flag exists.

The gate inspects staged index bytes and preserves the ledger history of each prospective commit parent, rather than reading an unstaged version of the files. For a committed review, use explicit refs:

```sh
python seedbag.py audit --commit HEAD --base origin/main
```

The audit pins the selected commit and base to object IDs, requires the base to be an ancestor, and reads exact committed files without checkout, index changes, or fetch. It validates the selected snapshot and ledger-prefix preservation against the base and every immediate commit parent. It does not execute checks again or audit every intermediate historical snapshot. Choose the actual intended review base and fetch needed history separately; missing parent objects cause refusal. It is a callable building block for review/CI, not installed remote CI or protected-branch enforcement. Local hooks can be bypassed, and an actor able to replace this program or rewrite all history is outside its cooperative guarantees.

## Conservative external effects

Most continuity operations only record state. `effect-run` is for a declared external command that is already authorized by the user and host. First use `effect.add` to record its ID, literal argument list, exact input files, and description. The runtime computes its prepared byte binding. Use `@python` as the executable for a portable Python adapter when applicable.

Before the command can run, its state becomes `running`. On return it becomes `returned`, even on exit zero. A crash or timeout can leave the external outcome uncertain. Inspect the target system, save genuine outcome evidence in a project-relative receipt file, then:

```sh
python seedbag.py inspect --kind effects --id operation_001
python seedbag.py effect-resolve operation_001 --receipt evidence/operation_001.json --outcome confirmed
```

Use `not_performed` only when evidence establishes that outcome. The receipt's bytes are bound and later checked; its contents are not independently interpreted or verified by this generic program. Do not write an invented success receipt.

An attempted ID cannot run again, even after a `not_performed` resolution. Equivalent unresolved command/input scopes also block obvious replacement IDs. This is a conservative local guard, **not an exactly-once distributed execution guarantee**: disconnected devices can act from unsynchronized histories, differently expressed commands can hide the same effect, and the external system can have its own partial failures. Keep one writer and use target-system idempotency or an appropriate adapter where such operations require it. Do not create a fresh ID to bypass uncertainty.

## Recover without losing evidence

- **Known stale or missing generated view:** run `render`. An old marker alone is insufficient; the complete old file must match the rendering of its recorded historical revision before replacement is allowed.
- **Handwritten generated view:** preserve that file's contents, interpret any meaningful additions into source-linked records, and explicitly reconcile the derived file. `render` will not silently destroy the edits. An apply command may already have saved the ledger before its render step refused; inspect current revision before retrying.
- **Stale writer:** reread the ledger and reconcile changed records. The local process lock and expected revision/digest prevent ordinary same-project overwrites; they do not coordinate disconnected clones.
- **Failed check or changed requirements:** leave work open, or reopen previously done work, repair the issue, then rerun the meaningful check. A successful earlier receipt is not a current pass.
- **Uncertain push:** inspect local commits and fetch/read the intended remote before retrying. A commit may exist locally even when sharing failed. Claim shared state only when the exact intended commit is verified remotely.
- **Runtime unavailable in the AI application:** read `AGENTS.md`, the available generated views, and relevant domain owners, preserving branch/commit identity when reading a shared repository. Label proposed edits as unsaved and checks as unrun until a writer with file access and Python execution actually applies them. A change of AI provider or device does not itself transfer access or synchronize files.

This version has no history-compaction, automatic chat-ingestion, automatic semantic merge, or remote deployment/permission service. Its tests cover concrete mechanics with disposable fixtures; ongoing conversational fidelity and long-term scaling still require real evidence.
