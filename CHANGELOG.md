# Changelog

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
