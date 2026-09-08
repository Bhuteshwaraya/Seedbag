# Seedbag

**Continue your project without rebuilding its history in every new AI chat.**

Long projects often outlast a single conversation. You explain what matters, explore possibilities, reject some, change direction, and gradually build a shared understanding. Then a new chat starts, and you have to reconstruct it. An important constraint gets missed. An idea you already rejected returns. Work that was unfinished gets mistaken for work that was done.

Seedbag gives that ongoing project a durable home in files that your assistant maintains. Its records keep track of:

- What you are trying to accomplish and the requirements that still matter.
- Decisions, changes of direction, and the reasons recorded behind them.
- Ideas saved for later, including when to reconsider them.
- Unresolved questions, current work, and the next step.
- What has actually been checked before progress is called complete.

You describe the work normally. The assistant handles setup, records, and saved checkpoints. Each project gets a continuation prompt you can keep and paste into a later conversation, so the next assistant can recover the project's saved context.

Your working files live locally for direct access. A **private GitHub repository** holds saved checkpoints for another device or a capable cloud assistant to retrieve. The public Seedbag repository supplies the starting framework; your project gets its own repository and independent copy.

## Start a new project

Copy this entire prompt into your AI conversation. Replace only **PROJECTNAME** with a name for the project.

```text
Create a new private project called PROJECTNAME, with a local working folder and its own private GitHub repository under my account, using https://github.com/Bhuteshwaraya/Seedbag.

Resolve the published v0.3.2 release to one exact commit. Read START_HERE.md there, follow its setup instructions, and use that same commit throughout. Handle all technical work, including first-time setup if Git, Python, or a GitHub connection is missing. Do not assume I already have a GitHub account.

Assume I know nothing about Python, Git, command lines, authentication, or choosing AI apps. Inspect your actual capabilities and choose the setup route. Preserve the goals and current work already in this conversation; do not make me repeat them.

This request authorizes the private setup and the necessary supported tool setup. Reuse working connections and settings. If I must create an account, sign in, or approve access, guide me through one plain-language action at a time. If this app cannot finish, provide one complete handoff prompt preserving my input, current state, and remaining work. Guide me to a capable destination when you can verify one.
```

You do not need to know Git or Python. If an account, sign-in, or approval needs your involvement, the assistant should guide you through one plain-language action at a time. After setup, use the project's continuation prompt to resume it; the creation prompt above is for a new project.

The project name labels the work. The person directing the AI and the person, team, or client benefiting from it may be different. No personal name or identity is assumed.

## Current status and limits

Seedbag 0.3.2 is an early release. Its runtime and setup probes have automated tests; the complete first-time installation, account connection, and use across AI applications are still being validated. See [the validation record](VALIDATION.md) for what has actually been tested.

Continuity depends on the assistant capturing important input and interpreting it faithfully. Seedbag does not automatically receive every chat message or recover conversations that were never saved. Changes saved only on one computer are unavailable elsewhere until shared to the private repository. Applications need suitable file access and tools to operate the project.

Seedbag is for new projects. Existing projects are not migrated or automatically updated.

Assistant instructions: [START_HERE.md](START_HERE.md). First-time setup: [FIRST_RUN.md](FIRST_RUN.md). Technical reference: [OPERATIONS.md](OPERATIONS.md). Evidence and limits: [VALIDATION.md](VALIDATION.md). Framework license: [MIT](LICENSE).
