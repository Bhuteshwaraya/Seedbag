# Seedbag 0.4.0 validation

The release program passed **184 tests**, with zero failures, errors, or skips, on Windows using Python 3.12.14 and Git 2.53.0.windows.3. The run took 550.162 seconds. [tests.json](validation/tests.json) records the exact tested Python file hashes; [tests.txt](validation/tests.txt) contains the named results. The public GitHub Actions workflow also runs Windows and Ubuntu with Python 3.11 and 3.12. Consult its actual run result; configured checks alone are not evidence of a pass.

The maintainer or assistant runs the suite, not the person starting a project:

```sh
python -B -m unittest discover -s tests -v
```

## Synchronization and interruption tests

The suite exercises actual local Git repositories and bare remotes for clean equality, audited fast-forward, unpublished local commits, explicit dirty-file checkpoints, bootstrap ancestry, a two-writer acquisition race, writer release, changed remote identity, reserved coordination branches, corruption, hidden index flags, interrupted acquisition/publication/release, and same-folder session recovery. Unknown session identities cannot borrow another writer. A missing launcher does not downgrade installed core gates. The public Git publication API uses the bound checkpoint path; coordination metadata is excluded from project candidates.

Fresh readiness checks read both the project branch and writer reference in one network observation. Cached status cannot open the gate. New record mutations and declared executions stop on failed synchronization. Existing effect outcomes remain recordable without admitting another execution. Diverged histories and unfinished work in another workspace remain preserved and blocked; the suite does not establish automatic semantic reconciliation.

Legacy Git snapshot/lineage unit tests intentionally exercise the private low-level transport primitive to model writers outside coordination. Separate installed CLI, sync, and adversarial tests exercise the public guarded path with real Git. No production switch disables synchronization for those installed tests.

## Host callbacks

Direct callback tests cover the documented denial JSON, unexpected exceptions, exact recovery command parsing, injection rejection, regular-file inspection without links, local-only behavior, one bounded Stop continuation, current session identity, and preservation of existing hook configuration. A real Git/ledger integration executes callback entry, a mutation under the same implicit host identity, dirty closeout refusal, an explicit checkpoint, and idempotent released closeout. The generated platform command is actually executed from a nested project folder.

Fault injection also exercises cumulative Git deadlines and a descendant process retaining stdio. The runtime uses temporary-file stdio so killing a timed-out Git parent does not leave the hook waiting on a child's output pipes. These checks bound normal Git waits; CPU hangs, a missing interpreter, forced termination, exempt tools, or a host that does not execute the callback remain outside this cooperative mechanism.

The installed Codex 0.153.4 app-server successfully discovered all four generated definitions in an isolated test configuration, selected the Windows commands, and reported no warnings or errors. It correctly marked them **untrusted**. No real user's trust settings were changed. Definition discovery is not activation: a complete model-loop test proving all actual tool interception was **not performed**. Outer code-orchestration and nested-tool routing are not exhaustively verified. Applications must establish their actual supported coverage and trust before claiming active pre-tool protection. No broad JavaScript recovery bypass is installed.

## Real private GitHub handoff

A dedicated synthetic private repository and three Windows working folders exercised the installed program over real authenticated GitHub Git. The test preserved the README bootstrap ancestry, recorded an opening request, published and verified a checkpoint, saved a change from a second workspace, and brought the older first copy forward automatically. It blocked a competing writer, preserved an unfinished local file, recovered that stopped session in the same folder, and shared its exact intended file. A fresh private clone recovered the same state. All three final trees matched, the permanent continuation request remained unchanged, the writer was released, and GitHub remained private with main as its default branch.

The flow took 275.702 seconds. [sync-live.json](validation/sync-live.json) records its scope and exact installed source hashes without private repository identifiers or machine paths. That development snapshot preceded the final reserved-branch, timeout-stdio, and recovery-diagnostic hardening. The final full suite covers those later changes; do not describe the earlier live run as byte-identical to the release. A subsequent read-only probe using the final Git transport verified both known private references in 1.297 seconds under a 10-second deadline.

This proves the Git/file handoff mechanics using actual GitHub. It is not a newly launched Work cloud conversation or universal automatic routing between applications. A cloud workspace needs the same authenticated ordinary Git access. Connector-only Work cannot complete this backend, and the setup instructions require a supported connection or a complete handoff before calling setup finished.

## Continuity and prior cloud evidence

The suite retains checks for source/disposition rules, pending input, stale transactions, immutable history, generated-view edits, real byte budgets, declared verification inputs, incomplete checkpoints, current evidence for completed work, uncertain external effects, private-output suppression in setup probes, and permanent continuation files surviving publication and a fresh clone. Test assertions establish these concrete mechanics, not the semantic completeness of an assistant's interpretation.

Earlier releases had an assisted Work-to-local test using an installed 0.3.4 project. Work saved an initial snapshot through connector operations after another authorized environment provisioned the private repository; a later local copy recovered it. That evidence does not prove unassisted 0.4 cloud creation or its new writer protocol. The retained connector exporter has separate byte/snapshot tests and reports preparation only; it is no longer an alternative synchronized setup route.

That earlier Work test also reported a higher ledger revision followed by a readable earlier revision. The originally reported higher-revision file was not retained, so the cause remains unexplained. A separate observed save-before-render failure led to explicit partial-save/readback reporting in 0.3.5, retained here. Neither that fix nor the synchronization gate proves uninterrupted cloud filesystem persistence or repairs an unexplained rollback.

Clean-OS dependency installation, new-account sign-in, unassisted current-release creation, every-host callback activation, long-term scaling, and conversational fidelity remain unverified. Seedbag does not automatically receive the entire transcript, authenticate source labels, merge independently diverged ledgers, or provide exactly-once external execution. Remote branch protection is not installed. Local hooks and the runtime are cooperative controls that a different application or modified program can bypass.

MANIFEST.json inventories explicit package files except itself; temporary fixtures and private case studies are excluded. Planted projects keep their own runtime and never auto-update. Existing user projects were not modified during this release's tests.
