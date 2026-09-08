# Start with Seedbag

Share this repository or the latest release ZIP with an AI assistant that can read local files and run Python. The framework does not depend on a particular model or AI provider.

You can say:

> Read Seedbag's README.md and OPERATIONS.md. Help me start a new project called <PROJECT LABEL> in a new folder using the included installer. The purpose is <PURPOSE>. The work is for <BENEFICIARY, IF RELEVANT>. Handle the commands and records for me. After planting, read the new project's AGENTS.md and continue using its own runtime. Use my project's repository for shared checkpoints when I request that setup.

Replace the placeholders with your project details; the beneficiary may be you, someone else, a team, or a client. Naming a beneficiary does not imply that person has approved anything. You can also describe the work naturally without using this exact prompt.

Download [Seedbag 0.3.0](https://github.com/Bhuteshwaraya/Seedbag/releases/tag/v0.3.0), expand the ZIP, and follow [README.md](README.md). Python 3.11+ is needed. The default installer initializes local Git; --no-git supports local-only use. GitHub access alone allows a reader to inspect files but does not provide Python execution or automatic writes.

A planted project has its own runtime and source-linked continuity ledger. The seed repository is never the project's live state store, and planted projects never auto-update from this repository.
