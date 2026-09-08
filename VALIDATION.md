# Seedbag 0.4.1 validation

The final program passed **208 tests**, with zero failures, errors, or skips, on Windows using Python 3.12.14 and Git 2.53.0.windows.3. The complete discovered suite ran in four isolated processes with disjoint test lists and took 167.494 seconds. [tests.json](validation/tests.json) binds the result to the exact Python files, and [tests.txt](validation/tests.txt) lists the checks. The GitHub Actions workflow also runs the complete suite serially on Windows and Ubuntu with Python 3.11 and 3.12; consult the actual run result rather than treating workflow configuration as a pass.

## Actual Codex lifecycle

Two disposable projects, a local bare Git remote, and the installed Codex 0.153.4 app-server exercised real ephemeral model turns. These were actual host-dispatched callbacks, not manually supplied callback events.

- Another participating workspace owned the writer claim. Codex ran Seedbag's PreToolUse callback and reported it blocked. The requested sentinel-writing tool was never delivered, and the file was absent.
- The other workspace then saved a newer checkpoint and released its writer. The older copy's native startup callback caught up before an allowed tool read the new contents. At delivery, local and remote commits matched. Native Stop verified the clean shared checkpoint and released the writer.
- The successful pre-tool check delivered its confirmation through the host to the assistant, which quoted it accurately. Neither the prompt nor the tool result contained that wording. This gives the actual project conversation observable evidence of interception for the covered call.

All 17 assertions passed. The blocked case took 15.734 seconds; catch-up and clean closeout took 20.718 seconds. [native-host.json](validation/native-host.json) records exact installed hashes and scope. Earlier attempts involving a mixed Windows ownership fixture or an ordinary shell-policy rejection were excluded from success evidence.

The attempted write used a client-provided dynamic tool routed through Codex's native hook path. This proves that path; it does not prove every desktop-specific tool, nested wrapper, shell recovery path, or future host version. The positive case used a read tool and clean Stop. Automatic authoring of an intended dirty-file checkpoint was not part of this live test; the runtime and callback suite tests those mechanics separately. Live model turns used exact per-definition trust settings for those invocations, with ordinary workspace permissions and the existing account; no blanket trust-bypass flag or global setting change was used.

## Persistent setup configuration

The actual configure-codex helper was exercised against the installed host with a disposable settings home and a Unicode project path. It retained trust for four exact generated definitions through Codex's versioned configuration API. A fresh process confirmed persistence, a repeat wrote nothing, and unrelated settings remained intact. Configuration success correctly left active interception and overall setup unverified. [codex-configuration.json](validation/codex-configuration.json) binds this test to the final helper.

The suite also checks altered commands and host metadata, missing callbacks, changed source files, conflicting settings versions, uncertain writes, additional untrusted project configuration, bounded subprocess behavior, and privacy of diagnostics. Setup must still observe host interception in the actual project conversation. A generated file, another conversation's test, or a working-directory argument is not that evidence.

## Synchronization and continuity

Automated fixtures cover real local Git equality, audited fast-forward, explicit dirty-file checkpoints, bootstrap ancestry, competing writers, fresh remote checks, uncertain pushes/releases, same-folder interruption recovery, divergence, hidden index flags, and changed runtime or destination. They retain append-only records, source/disposition checks, bounded context, immutable continuation prompts, fresh completion evidence, and explicit handling of uncertain external effects.

Earlier v0.4 development also exercised a dedicated private GitHub repository and three working folders: publication, remote updates, local catch-up, interrupted-session recovery, and fresh-clone equality. [sync-live.json](validation/sync-live.json) retains that earlier run's exact hashes and limitations; it is historical GitHub transport evidence, not a fresh 0.4.1 cloud-chat test. The earlier assisted 0.3.4 Work-to-local demonstration likewise does not establish current unassisted cloud creation. Connector-only Work cannot operate this synchronization backend.

## Remaining boundaries

An end-to-end new-project setup through every desktop or cloud UI, clean-machine installation, account sign-in, all host tool routes, long-term scale, and perfect conversational fidelity remain unverified. A cloud workspace needs authenticated ordinary Git and a supported active host gate to complete protected setup. An inaccessible device's unpublished files cannot be retrieved from GitHub. Hooks coordinate participating work; they are not a security sandbox, a semantic merge engine, automatic chat ingestion, or a guarantee of saving after a crash.

Existing user projects and real global settings were untouched. The manifest inventories only explicit release files; temporary fixtures and private case studies are excluded. New projects keep their own installed runtime and never auto-update.
