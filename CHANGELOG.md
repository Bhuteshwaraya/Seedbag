# Changelog

## 0.3.5

New projects save a short continuation request: `Continue my project: PROJECT-LOCATION`. Ordinary wording is welcome. The README directs the assistant to AGENTS.md, where setup, recovery, local-folder, and authorization instructions live. The saved request remains stable and mechanically tied to the project's locator.

Add `connector-export` for a new project's first parentless checkpoint. It exports audited committed blobs and their exact tree for connected GitHub tools, reports prepared rather than shared state, and leaves remote identity, privacy, non-forced publication, and exact readback explicit. A connector-only environment can use a verified README-only private repository created through an account action or authorized assistance. Later writes use the actual published history through authenticated Git.

Distinguish a saved mutation followed by failed view rendering from a rejected mutation. Partial-save errors report the observed ledger identity and require inspection before retrying. This improves a demonstrated ambiguous result; it does not explain an observed cloud persistence discrepancy.

Existing projects retain their installed files and versions. See VALIDATION.md for the assisted live-test boundaries and remaining limitations.

## 0.3.4

Add a continuity illustration and a three-step diagram to the front page. Rewrite the page and creation/continuation prompts around the reader's next action, removing design annotations and assumptions about the reader's knowledge.

Reuse verified device-level Git setup across tasks. First-run guidance now covers the intended credential owner, fresh-context verification, local setup notes, and narrowly scoped diagnosis. The read-only helper distinguishes helper, ownership, host-key, key-format, permission, authentication, and network failures and returns fixed next-action guidance. It performs no new probes or automatic repairs.

Check whether a cloud workspace has a usable private creation/publication route before full package acquisition or unnecessary tool installation. An incomplete setup handoff is explicitly distinguished from continuing a saved project. No existing project or host configuration is upgraded.

## 0.3.3

Let a capable cloud conversation create and verify a private GitHub checkpoint before the project has a folder on the person's computer. The permanent continuation prompt now directs a local assistant to reuse an existing matching folder or clone the same repository, then continue from its own installed files. Setup guides distinguish cloud workspace, computer-local files, and verified shared checkpoints.

Every new project receives a friendly README with recovery steps, links to goals and current progress, and its exact saved continuation prompt. The runtime checks that required planted files are present, both prompt blocks agree, the repository locator matches, and ordinary checkpoints preserve the continuation file. Missing recovery files cannot pass the publication gate. Existing projects remain unchanged.

## 0.3.2

Add a first-time setup route for people without Git, Python, a GitHub account, or an existing connection. The assistant handles supported installation and configuration; the person receives only unavoidable account, consent, or OS actions. Distinguish missing tools, missing credentials, rejected credentials, denied networking, and broken Git transport through a read-only preflight helper. Preserve working connections and host rules. Planted projects carry the guide and helper for later devices and keep their existing repository.

Probe tests and controlled onboarding scenarios are separate from live account sign-in and real private Git publication. See VALIDATION.md for the actual evidence and remaining live-test boundary. Existing projects remain unchanged.

## 0.3.1

Restore initiation by one copy/paste prompt. The person provides a project name and goals; the assistant handles package retrieval, local setup, private sharing, verification, and application routing. When tools are unavailable, provide a complete handoff prompt and one unavoidable plain-language user action. Preserve opening project details and return a stable, plain-language continuation prompt. Move technical setup instructions behind the assistant-facing entry protocol.

This patch affects future planting only. Existing projects retain their installed runtime. The executable continuity checks remain in place.

## 0.3.0

First general-purpose public release of Seedbag.

- Structured, source-linked project records and append-only local transactions.
- Generated current views and bounded context selected by explicit work/document dependencies.
- Executed checks bound to declared file bytes and relevant recorded requirements.
- Interrupted savepoints, uncertain-effect records, and conservative local retry guards.
- Ordinary Git checkpoints with staged and committed history validation and exact remote-tip readback.
- Independent planting, portable @python commands, and an MIT notice included in each new project.
- Generic initiator, beneficiary/client, and project-label guidance, with no fixed personal identity or machine path.

The public source contains the reusable program, documentation, synthetic tests, and test results. It has no imported development-project history. See VALIDATION.md for tested boundaries and OPERATIONS.md for known limits.
