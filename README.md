# Seedbag 0.3.0

A local program for preserving a project's requirements, decisions, deferred ideas, current work, and verification evidence across AI conversations. **Plant it only for future projects in a new empty directory. Existing projects are not migrated.**

You talk normally. The assistant uses the program to capture relevant input, translate it into named records, and keep those records connected to their sources. You should not need to maintain JSON yourself. The program uses readable text and JSON. It does not change a model's memory or automatically receive the chat transcript.

The **initiator** is the person currently directing the AI. The intended beneficiary may be that person, someone else, a team, or a client. The project name is a label for the work, not a person's identity. Record names and roles only when supplied and relevant; do not infer them from an account, device, folder, or the seed's author. No role-registration step is required to begin.

The new project gets its own runtime and continuity ledger. Local work and the project's Git repository contain the same files and history. Git provides shared checkpoints; the seed repository is not another authority or a place to store planted projects' state. A planted project does not automatically update when this seed changes.

## Start a future project

Use Python 3.11 or newer. Git is needed for the default installation and sharing. There are no third-party Python packages, model API calls, or API keys to configure.

From this seed package directory:

```sh
python seedbag.py init ../my-new-project --name "My new project"
cd ../my-new-project
python seedbag.py context
```

Here, `python` means an installed Python 3.11+ executable. Check with `python --version`; use `python3` or, where available, `py -3.11` instead if that selects a suitable interpreter. `--name "My new project"` labels the project; choose a descriptive label for your work.

For local files without initializing Git, add `--no-git` to `init`. The directory must be new or empty. Default planting initializes a `main` branch and installs a local commit hook; it creates no commit or remote repository.

Use an AI application that can read and write the project files and run Python. Applications differ in whether they load `AGENTS.md` automatically, so explicitly ask the assistant to read it when necessary:

> Read this project's AGENTS.md and continue using its seedbag runtime. The project's purpose is … Please preserve the requirements and unresolved ideas from our work.

The assistant handles the recording commands. Its interpretation still needs judgment: a source link proves what text was recorded, not that the assistant understood every requirement correctly.

## Share the same project

If the project's intended repository URL is already known, supply it when planting:

```sh
python seedbag.py init ../my-new-project --name "My new project" --repository "PROJECT_REPOSITORY_URL"
```

Replace `PROJECT_REPOSITORY_URL` with this project's actual repository URL. That option records a locator in the project ledger and continuation prompt. **It does not create or configure a remote.** Use the intended repository through your normal Git setup, then configure its clone URL in the planted project:

```sh
git remote add origin "PROJECT_REPOSITORY_CLONE_URL"
```

Replace the clone-URL placeholder too. GitHub or another compatible Git remote can hold the same project files; ordinary Git transport and access requirements apply.

The assistant uses `publish --message ... --paths ...` with exact intended files. A local save, local commit, and verified shared checkpoint are different results; the command reports which remote commit it verified. Ordinary local work needs no network access.

On another device, clone this project's repository, run its own `seedbag.py context`, and use `status --fetch` to discover relevant published candidates before continuing. Reinstall the optional local hook there with `python seedbag.py install-hook`. Use one active writer. Keep any competing candidate branch available for review; no branch wins merely because it is newer. Independently diverged ledgers cannot be joined by a two-parent merge in this version: reviewed changes must be deliberately recorded into the chosen lineage while preserving the separate candidate branch.

## What is preserved

| File or area | Role |
| --- | --- |
| `.seedbag/ledger.json` | Canonical continuity records, raw captured text, dispositions, event history, and evidence bindings. Use commands to change it. |
| `PROJECT.md`, `STATE.md` | Generated current views for people and readers without the runtime. Handwritten changes are detected rather than overwritten. |
| `AGENTS.md`, `CONTINUE_HERE.md` | Stable operating instructions and a continuation prompt. |
| Ordinary domain documents, code, and artifacts | The project's actual work. Register relevant document owners and verification inputs as it grows. |
| `seedbag.py`, `.seedbag/runtime/` | The project's independent program copy. |
| `SEEDBAG_LICENSE.txt` | The framework's MIT license notice, copied into each new project. |

The context command keeps global dispositions and follows a selected work item's document dependencies. It measures the actual UTF-8 output budget, defaults to 24,000 bytes, and refuses overflow explicitly. It does not silently shorten a required document or drop constraints. A growing project can have many domain files; there is no lifetime file limit.

## Boundaries worth understanding

- Capture is explicit. The assistant must actually save relevant user input; the host chat is not automatically archived.
- Check results are tied to declared input bytes and recorded requirements. Choosing complete inputs and meaningful tests is still a judgment. `doctor` readiness and successful publication do not certify that the whole project is finished or user-approved.
- External-operation records prevent some local accidental retries. They provide no exactly-once guarantee across disconnected devices or external systems.
- An AI application with project-file access and Python execution can run this program. A reader with repository access alone can inspect published views and propose changes, but must not claim a check or durable write happened there. Read `AGENTS.md` explicitly when the application does not load it automatically.
- The ledger retains history and the runtime replays it locally. This version has no archive compactor or measured long-term speed/reliability guarantee. Bounded model context does not mean bounded disk history.

See [OPERATIONS.md](OPERATIONS.md) for exact commands, recording examples, interrupted savepoints, recovery, and Git checks. The included tests use disposable fixtures; they do not establish that every future conversation will preserve meaning correctly.

## License and releases

Seedbag is distributed under the [MIT License](LICENSE). New projects receive its notice as `SEEDBAG_LICENSE.txt`; this licenses the framework copy, not unrelated project content. The official source is [Bhuteshwaraya/Seedbag](https://github.com/Bhuteshwaraya/Seedbag). Download a versioned package from [GitHub Releases](https://github.com/Bhuteshwaraya/Seedbag/releases).
