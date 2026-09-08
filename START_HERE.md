# Assistant bootstrap for Seedbag 0.4.0

The person starts with the single prompt in README.md and supplies a project name and goals. You own package retrieval, commands, supported setup, private sharing, and capability routing. Do not ask the person to learn Git or Python or repeat a brief already supplied.

The creation request authorizes a new private project and necessary supported tool setup. It does not authorize changing existing projects, an invented product, deployment, or unrelated external action. Host permissions still apply. Keep verified partial work if setup is interrupted; never create duplicate repositories to hide a failed step.

## Establish a usable route first

Inspect actual capabilities: reading the seed, writing a project folder, executing Python 3.11+, using ordinary Git, and authenticated private GitHub read and non-forced push. The synchronization runtime needs access to both the project's branch and its `seedbag-sync-claims` coordination branch. API identity, repository creation, and ordinary Git transport are distinct capabilities.

Use the person's computer when this conversation can access it. A cloud execution workspace can also create the project if it supports the same authenticated Git workflow. Its folder is cloud-hosted; do not describe it as a folder on the person's computer. The verified private checkpoint enables a later local conversation to clone and continue the same project.

Read FIRST_RUN.md at the pinned release. Reuse working settings and bundled tools. Handle supported missing-tool setup yourself; account creation, sign-in, MFA, consent, or an OS permission screen may require one plain-language user action at a time. Do not expose credentials, replace working authentication to mask a transport failure, or ask the person to select a Git transport.

A connector-only Work environment cannot complete the 0.4 synchronization route, even if it can upload individual GitHub files. Inspect that boundary before planting or creating a repository. Establish ordinary authenticated Git through a supported host route, or prepare a complete handoff preserving the brief. Do not install an unauthenticated CLI when there is no permitted connection route. The legacy initial `connector-export` utility is not a substitute for this check.

If the connection cannot create repositories but Git access is otherwise usable, guide the unavoidable account action to create one private README-initialized repository, then continue automatically. Verify its owner, numeric identity, URL, visibility, branch, and bootstrap. Never assume an incomplete listing proves emptiness. Use the authorized account, not the seed author's account, unless the person explicitly chose it.

Use a new unused folder and repository name, resolving routine naming details yourself. A project label does not identify the beneficiary. Preserve names and roles only when supplied and relevant; do not infer them from an account, device, or the seed's author.

## Acquire one release and plant once

Resolve the published v0.4.0 release of [Bhuteshwaraya/Seedbag](https://github.com/Bhuteshwaraya/Seedbag) to one exact commit. Read this guide, FIRST_RUN.md, SYNC.md, OPERATIONS.md, and the manifest from that commit. Retrieve and verify all listed file hashes before executing the package. Retain the release and commit as setup provenance. Do not mix a moving branch's instructions with another release's runtime.

After execution and transport prerequisites work, create or reuse the private repository authorized for this setup. Prefer a single-root README bootstrap on main, so the coordination reference cannot accidentally become GitHub's first/default branch. Verify its actual identity and privacy. Plant into the new empty directory with its returned URL, using the installer in OPERATIONS.md. Configure ordinary Git for that repository and the bound `main` branch. For README-initialized destinations, the bootstrap must be a single parentless README-only commit. Other pre-existing content is not a planting target.

The installed project contains its own runtime, instructions, SYNC.md, first-time helper, and MIT notice. It must run without the source checkout. Read its AGENTS.md explicitly and follow it from here onward. Run `sync-configure`, then `sync-begin --setup` with a stable conversation identity before capturing input or doing project work. This checks the new shared destination, acquires the writer claim, and preserves real bootstrap ancestry. A recorded repository URL alone does not configure Git, upload files, or open the editing gate.

## Preserve the opening conversation

Capture meaningful original input already available, including goals, constraints, deferred ideas, relevant beneficiary context, and prior work. Translate it into source-linked records and reconcile the capture honestly. Distinguish the person's directions, assistant proposals, and quoted third-party text. The program does not automatically receive the transcript.

If synchronization is temporarily blocked, preserve that input in a complete handoff or an available host-permitted recovery location; active hooks may deny arbitrary scratch-file writes. Do not invent a successful capture. If only setup and a name were requested, record that the goal is unspecified and ask what the project should achieve after setup. Do not infer an implementation from a project name.

## Verify the private checkpoint and host safeguards

Run the project's context and doctor commands. Inspect recorded facts, generated views, and current evidence for any claimed completed work. The planted README must explain where the project is, link its goals/progress, and contain the same short permanent request as CONTINUE_HERE.md with the actual locator. Write for the reader; design directions such as “friendly” are not descriptions to insert into the product.

Publish all reviewed intended project files with `sync-checkpoint --message ... --paths ...`, including the installed program, support guides, policy, records, generated views, README, and continuation file. Verify the exact remote commit, private visibility, and that GitHub's default branch is the bound project branch rather than the coordination branch; read the README and continuation file back at that commit. Incomplete savepoints preserve genuine open input but do not waive stale evidence or missing required files. Do not describe setup as complete while publication or readback remains uncertain.

On a supported Codex host, prepare callbacks with `install-host-hooks` after connection setup. Inspect generated commands, follow the actual host trust control, and verify activation. Keep this machine's ignored hook configuration local. The separate local Git snapshot hook is installed at planting; preserve existing hooks during integration. A cloud or other host without active callbacks still has runtime-command gates and assistant workflow duties; disclose the absence of a mechanical pre-tool gate rather than implying universal protection. See SYNC.md for exact boundaries.

Report the verified working location, private repository, and observed synchronization/host-hook status. For cloud creation, state that a folder on the person's computer has not yet been created. Return the short request from CONTINUE_HERE.md unchanged. Explain that the same request later lets a capable local conversation retrieve the same repository. A new conversation must never create a replacement repository or fetch a newer seed to resume.

The assistant checks before editing and checkpoints before substantive final responses. Do not make the user remember a closeout command. Preserve the stable continuation request across routine saves; changing progress belongs in the ledger and generated state.

## Handoff when this environment cannot finish

Provide one self-contained handoff containing the original brief, actual project/repository locations if any, pinned seed commit, completed and unverified steps, observed files/commits, unfinished writer ownership, and the exact remaining capability. Preserve meaningful input verbatim when feasible. Mark unknowns unknown. A temporary setup handoff is distinct from the permanent request for a verified saved project.

Identify a capable destination only when verified. If none is known, include the full handoff anyway and ask only the minimal nontechnical fact needed to find one. Never loop the person back to the same incapable environment, drop their input, or substitute an unshared folder for the requested private checkpoint.

This framework coordinates participating writers and validates concrete records; it cannot guarantee semantic fidelity, automatically ingest all chat messages, merge independently diverged ledgers, save after every crash, or provide exactly-once external effects. Existing projects remain independent and are never upgraded by this bootstrap.
