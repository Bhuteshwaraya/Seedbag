# Assistant bootstrap for Seedbag 0.3.2

The human entry point is the single prompt in [README.md](README.md). This file tells the assistant how to fulfill it. The person supplies a project name and speaks normally; you handle setup, commands, records, and capability routing. Do not return installation instructions for the person to carry out or assume they can choose a suitable AI application.

This request authorizes a **new private project with a local working folder and its own private GitHub repository**, including necessary supported tool setup. Continue within that scope without repeated approval questions. Existing projects are never migrated or overwritten. Setup does not authorize an invented product, deployment, or external business action, and does not override host permission rules.

## 1. Establish the route, including first-time setup

Read the actual tools and environment available in this conversation. Determine whether you can retrieve the seed files, write a new persistent local project folder, execute Python 3.11 or newer, use local Git, and create and access a private GitHub repository. A browser, repository connector, temporary execution environment, and persistent local filesystem provide different capabilities; do not assume that access to one supplies the others.

Assume the person may have never installed Git, obtained Python, created a GitHub account, or connected it to an AI application. Read [FIRST_RUN.md](FIRST_RUN.md) at the pinned release. Supply missing tools through supported available installation routes, reuse bundled runtimes, and guide any unavoidable account creation, sign-in, or OS approval one plain-language action at a time. Missing software or an unconnected account is not itself a reason to hand off. Do not ask the person to execute commands, configure Git, choose a technical transport, or repeat their project brief.

You can acquire the pinned source and prepare non-secret setup notes while establishing the route. Verify the package manifest before running its read-only `seedbag_setup.py` helper. Local tool discovery, CLI API authentication, and ordinary Git transport are separate probe results; host connector access still needs inspection through the host. Treat helper results as evidence for your next action, not a certificate that the private project is ready. Recheck after fixing a prerequisite. Create the project repository only once the local tools and intended connection route are usable.

Inspect the reused or newly connected GitHub account and any destination preference already supplied. Use that account for the new repository unless the person explicitly selected another authorized owner. The seed author's account is only the source location. Choose a descriptive project label, a new unused folder, and an unused repository name; handle routine naming choices yourself without overwriting a collision. The project label is not a person's identity.

The initiator is the person currently directing the AI. The beneficiary may be that person, another person, a team, or a client. Preserve supplied names, roles, and attribution when relevant. Do not infer identities from accounts, device paths, or the seed's author, and do not introduce a role-registration step. A relayed request is not proof of direct approval by the person quoted.

If the whole route is available, proceed. For real sign-in or permission-screen interaction, follow FIRST_RUN.md and use the approved user-owned surface. Do not capture passwords, tokens, device codes, or authentication output in the conversation or project. Distinguish absent setup from rejected credentials, network denial, and an unreadable existing Git key. Preserve working connections and configured transports. Resume the remaining work yourself after an unavoidable human action succeeds.

If an actual capability or approval boundary prevents completion after following the applicable first-time setup route, follow the handoff section below. Do not create an orphan repository, pretend temporary files are a persistent local project, or silently substitute a local-only project for the requested local-and-private-GitHub result. Use local-only setup only when the person explicitly requests it. Preserve and identify any partial work that already exists.

## 2. Acquire one consistent seed release

Use the official source, [Bhuteshwaraya/Seedbag](https://github.com/Bhuteshwaraya/Seedbag). Resolve the requested published v0.3.2 release to an exact commit, then read this file, the first-time setup guide, technical reference, manifest, and required package files at that same commit. If you first read this guide from a moving branch, reread it from the pinned release before using it. Do not mix branch-tip documentation with runtime files from another release.

Retrieve and prepare the source yourself through available tools. Verify the manifest's listed file hashes before executing the package, and retain the release version and commit as setup provenance. If the requested release cannot be resolved or verified, report that concrete limitation; do not silently substitute another version or invent verification.

[OPERATIONS.md](OPERATIONS.md), read at the same pinned commit, contains the exact commands and record formats. All technical execution is your work. Do not ask the person to download, expand, type commands, locate Python, or configure Git. Handle installation yourself wherever the host permits; ask only for an unavoidable human interaction described in FIRST_RUN.md. If a necessary capability is unavailable, find a feasible route or supply a complete handoff.

## 3. Plant the independent private project

After prerequisite and destination checks, create the private repository through the person's reused or newly established authorized connection. Verify its actual owner, URL, and private visibility, then verify ordinary Git access to that repository. Use the returned project URL when planting into the selected new empty local directory, so the installed continuation prompt identifies this project from the beginning. If a later step fails, preserve that repository and its identity for recovery; do not retry creation under another name without accounting for the first result.

Use the installer and the available runtime according to the technical reference. The new project must contain its own framework copy and license notice; it must not depend on the source checkout remaining on the machine. Read the planted project's AGENTS.md explicitly if the AI application does not load it automatically. Configure the project's Git connection yourself. The installer's repository locator alone does not configure a remote or upload files.

Keep the local working folder in the person's intended private workspace. Verify the location you actually created. A private GitHub setting does not certify the privacy of an unrelated shared folder or an AI service's data handling; describe only the access facts you established.

## 4. Preserve the opening conversation without asking for it again

After planting, capture the meaningful opening input that is available in this conversation, including supplied project goals, requirements, deferred ideas, beneficiary context, and any existing work to continue. Save the relevant original wording, then translate it into source-linked records and reconcile the capture. Preserve the difference between the person's instruction, an assistant proposal, and quoted third-party material. The runtime does not automatically receive the host conversation; you must actually perform the capture.

Use the project name as a label. If only setup was requested, record that the workspace was created and the project goal is still unspecified. Do not infer a product from the name, invent accepted requirements, or mark implementation work complete. If goals were already supplied, preserve them and continue within their actual scope instead of asking the person to repeat them.

Make record changes through the project's runtime. Its ledger is the canonical continuity state; generated views and linked domain files serve their documented roles. Source text and hash checks cannot establish that your interpretation is complete. Keep unresolved meaning visible instead of manufacturing acceptance to satisfy a check.

## 5. Verify setup and leave one stable way to continue

Verify that the planted runtime operates from its own project copy, the captured records and generated views agree, and any claimed completed work has the required current evidence. Publish the intended project files through the documented workflow, then verify the exact remote commit and private repository visibility. Confirm that the shared files contain the same project lineage as the local working folder.

Report the verified local location and private project repository separately. A local save, local commit, successful command, and verified remote checkpoint are different observations. If publication or verification is incomplete, say exactly what is saved and what remains; do not present partial setup as finished.

Give the person the **permanent plain-language continuation prompt from the planted CONTINUE_HERE.md, unchanged**. It should already identify the actual project, with no placeholder for the person to fill. Tell them they can keep it and paste it as-is into a later conversation. Keep current milestones in the ledger and generated state, so the continuation prompt remains stable. Do not replace it with a new technical checklist or ask the person to maintain records.

If no project goal has been provided, end by asking what they want the project to accomplish. If the goal is known, acknowledge the preserved goal and continue the authorized work. Do not confuse completing setup with delivering the eventual product.

## When this application cannot finish

You own the routing problem. Use actual tool and application discovery to determine whether an accessible destination can perform the missing work. Name a destination application only when you have evidence that it is available and capable; never require a particular provider by default or claim that any AI chat can execute the runtime. If a transfer is available and authorized in the current environment, use it while preserving the work. Otherwise provide **one complete copy-and-paste handoff prompt**, ready to use without editing.

The handoff must contain:

- The supplied project label and all available goals, requirements, constraints, deferred ideas, and relevant beneficiary attribution. Preserve source wording where it matters; do not replace a supplied brief with a request to explain it again.
- The official seed URL, requested release, pinned commit if resolved, and instructions for the receiving assistant to read the bootstrap at that commit.
- Verified local paths, repository owner and URL, private-visibility observations, branch/commit identity, captures or records already saved, and the precise remaining work. Clearly distinguish verified facts, unsaved proposals, and unavailable information. If nothing has been created, say so.
- The existing authorization for the new private project and its private GitHub copy, the current capability or access obstacle, and the instruction to reuse existing partial work safely rather than create duplicates.
- The instruction to handle tools and setup itself, preserve the supplied context, verify local versus shared state, return the unchanged permanent continuation prompt, and ask for a project goal only if the handoff does not already contain one.

Accompany it with just the next unavoidable plain-language action for the person. When a capable destination is verified, identify that destination and where to paste the prompt. If no destination can be verified, say so and obtain only the minimal nontechnical fact needed to locate one; do not present an app-selection quiz or a stack of software-installation steps. The complete handoff remains available so the person does not have to reconstruct the project brief.

## Limits that remain in force

This bootstrap is an assistant workflow, not automatic chat ingestion, a dependency installer, an authentication service, or a guarantee of application capabilities. The runtime's documented constraints still apply: meaningful verification requires judgment, context overflow is explicit, and external effects have no exactly-once distributed guarantee. Use one active writer. Preserve competing candidate branches; independently diverged ledgers need deliberate reconciliation into a chosen lineage rather than an automatic merge. Planted projects remain independent and never auto-update from the public seed.
