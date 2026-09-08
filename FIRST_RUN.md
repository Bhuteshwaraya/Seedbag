# First-time setup — instructions for the assistant

Assume the person may have no Git, Python, GitHub account, or connected integration. Missing prerequisites are setup work for you, not a reason by themselves to send the person to another application. The person supplies the project name and goals. Handle discovery, supported installation, configuration, and verification. Account creation, sign-in, MFA, consent, and OS approval may require the person; give only the next unavoidable plain-language action and resume when it is complete.

This guide also travels with each planted project for use on another device. Resume an existing project's repository and records; do not create a replacement project or fetch a newer seed. For a new project, first resolve its requested seed release and read this guide at that exact commit. Preserve the supplied brief throughout setup. Keep non-secret setup notes and verified partial locations when interruption is possible, but never put credentials in those notes or the project.

## Inspect before changing the machine

Read host instructions and actual capabilities first. A local shell, persistent project filesystem, cloud workspace, repository connector, and browser are distinct capabilities. A new project can begin either in a persistent folder on the person's computer or in a cloud execution workspace that can run Python and ordinary Git and publish the private repository. Choose from verified capabilities, not the application's name. A cloud workspace is temporary unless its persistence is established; the verified private GitHub checkpoint is the durable handoff to another environment. Do not describe cloud files as a folder on the person's computer.

When the person later requests a computer-local copy, that conversation must actually have access to the computer's filesystem. If it does not, identify a verified capable route or preserve a complete continuation handoff. You may prepare source files and setup notes before a project exists. Do not create a new project's repository until the execution tools and intended authentication/transport route are usable. A connector that only reads or writes repository files does not replace the runtime and Git publication workflow.

Inspect available bundled runtimes and installed tools. Use an existing Python 3.11+ interpreter and Git wherever available, including supported bundled locations absent from PATH. Reuse existing GitHub connections and honor configured Git protocols, credential helpers, SSH commands, and explicit host rules. Inspect only necessary configuration metadata; do not dump environment variables, authentication files, keys, or credential responses.

For new-project acquisition, verify the seed package manifest before running its read-only `seedbag_setup.py` helper with the available interpreter. For an existing planted project, use the helper from that project's own verified checkout at the selected saved commit; inspect relevant local changes before execution. Planted projects do not carry the source-package manifest and do not need to retrieve it from the seed. The helper reports local tool discovery by default. `--network` additionally probes CLI account access and ordinary Git access. Its safe classifications help distinguish missing tools, missing or unreadable credentials, denied networking, rejected credentials, and transport failures. It never installs software, signs in, changes Git settings, or creates a repository. It cannot discover host connector permissions or certify a private push. Read its JSON and combine it with actual host tool evidence; do not treat a successful probe process as completed setup. Commands are for you, not the person.

Every network probe requires an explicit `--repository` HTTPS URL. For a new project, the public seed URL can serve as a preliminary transport probe. For an existing planted project, use that project's actual GitHub URL from its records; do not contact the seed during continuation. The helper refuses a network probe without a selected target. This URL selects a read target; it does not override the host's configured Git transport or credentials. Use `--offline` when only local work is needed.

## Supply missing tools

If the host has execution and permits tool installation, obtain only missing dependencies through its existing supported package manager or the vendor's official installer. This applies to the actual working environment, including a capable cloud workspace; installing there does not install software on the person's computer. Use the least disruptive supported scope. Do not install a second package manager merely to avoid understanding the current environment. A permission boundary requires the host's approved route; do not bypass it. The creation prompt authorizes necessary supported setup, but does not grant OS privileges or override host restrictions.

Examples to verify against the current official instructions before running:

| Host | Assistant-owned route |
| --- | --- |
| Windows with WinGet | Install missing Git with `winget install --id Git.Git -e --source winget`. Install GitHub CLI only if the chosen connection route needs it, using `winget install --id GitHub.cli --source winget`. |
| macOS with Homebrew already installed | Install missing tools with `brew install git` or `brew install gh`. Without Homebrew, Git documents Apple's Command Line Tools route; inspect the official alternatives before selecting one. |
| Linux | Detect the distribution and use its supported Git package. Use GitHub's current distribution-specific instructions for CLI packages if needed; there is no universal Linux install command. |
| Python unavailable | First inspect the application's bundled runtime. Otherwise use a supported Python 3.11+ package or official installer matching the detected OS. |

Do not assume an installer made an executable immediately discoverable in the existing shell. Locate and verify the actual executable after installation, or use a fresh supported execution session. Continue automatically from a successful install. For an unavoidable OS prompt, describe its verified application and expected action plainly rather than giving installation commands to the person.

Official installation references: [Git on Windows](https://git-scm.com/install/windows), [Git on macOS](https://git-scm.com/install/mac), [Git on Linux](https://git-scm.com/install/linux), [GitHub CLI installation](https://github.com/cli/cli#installation), [Python downloads](https://www.python.org/downloads/), [Microsoft WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/). Recheck instructions when using them; package availability and installers change.

## Establish an account connection

If an existing integration identifies the authorized account, reuse it. CLI authentication is not mandatory when another supported integration supplies the needed operations; ordinary Git still needs a working transport for this release's publish workflow. A successful repository API request alone does not prove that Git can clone or push.

If there is no usable account connection, use the application's verified GitHub connection flow when available. If the person has no account, guide them to GitHub's official account-creation page and let them complete their own identity and email verification. Preserve the brief; do not ask for it again after sign-in. Avoid assuming a particular settings button exists: inspect the actual UI or current product documentation before naming it.

When GitHub CLI is the appropriate supported route, its browser login flow can establish a connection. Use a user-owned authentication surface that is not captured in assistant tool output, logs, screenshots, or project files; the flow may display a one-time device code. Never start a captured `gh auth login` process that would leak that code into the conversation. Never ask for a password, token, key, or one-time code in chat. If no suitable authentication surface is available, preserve a complete handoff and explain the exact missing capability rather than inventing a completed sign-in.

On a genuinely unconfigured host, GitHub documents HTTPS with its credential manager or CLI-managed credentials. Choose and configure the supported route yourself only after checking host rules and existing settings. Do not replace working SSH or HTTPS configuration, unconditionally run `gh auth setup-git`, mint a new key, or change a host-wide protocol to work around a connection error. Do not choose insecure credential storage or put credential configuration inside a project. Let the approved authentication tool own credentials; successful login alone is not evidence of secure storage.

If Git author identity is unset, configure it for the new repository using the verified account's appropriate identity and privacy preference; do not change global identity or infer the project's beneficiary from that account. Preserve a suitable existing identity. This is your configuration work, not a Git questionnaire for the person.

Official connection references: [Creating a GitHub account](https://docs.github.com/en/account-and-profile/how-tos/account-management/creating-an-account-on-github), [CLI browser login and storage behavior](https://cli.github.com/manual/gh_auth_login), [Git credential setup](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).

## Distinguish missing setup from broken access

For CLI probes, credential readability and authenticated API access are separate observations. The helper discards credential output. If doing equivalent probes yourself, discard both output streams from `gh auth token --hostname github.com`; then request only necessary non-secret account fields from `gh api user`. Do not assume `gh auth status --json` exit zero proves authentication: that mode can return zero despite account errors.

| Observation | Next action for the assistant |
| --- | --- |
| A tool is missing | Supply it through the supported installation route, then rediscover it. |
| No readable credential and no working connector | Guide first-time sign-in on the approved user-owned surface. Investigate an existing protected configuration before treating it as absent. |
| API returns an actual 401 or Bad credentials | Guide renewal of the existing connection. |
| Socket denial, DNS/TLS failure, timeout, 403, or rate limit | Resolve or report that specific access/service condition; do not label the credential expired. |
| API works but Git cannot read its configured key/helper | Preserve the working account connection. Investigate the supported execution/permission route; do not reset authentication, expose keys, weaken permissions, or bypass an explicit transport rule. |
| Public Git read succeeds | Continue to private repository creation/access verification. This alone does not prove private write permission. |

If the host requires explicit approval for a narrowly scoped permissions repair, prepare the exact target and proposed access change for review and ask once through the permitted route. Explain the actual refusal plainly. Ordinary project-setup authorization is not a reason to bypass a host rejection of privileged access changes. Preserve the working account and project brief while the necessary approval is pending; continue independent work that does not require that repair.

References: [CLI token probe](https://cli.github.com/manual/gh_auth_token), [CLI status behavior](https://cli.github.com/manual/gh_auth_status), [GitHub API troubleshooting](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api).

## Finish setup and prove the result

For new-project setup, return to the pinned START_HERE.md. Create the new **private** repository using the authorized person's account. Verify the real owner and visibility. Configure and test the intended ordinary Git transport against that repository, install/capture the project, publish its complete intended files, and verify the exact remote checkpoint. The published README.md must provide friendly recovery instructions and the same permanent continuation prompt saved in CONTINUE_HERE.md. Use the publication gate and read the files back from the verified commit; instructions only printed in a chat do not satisfy this requirement. Account sign-in, a public read, a workspace save, a local Git commit, and private upload are distinct steps. For an existing project, follow its planted AGENTS.md and the continuation section below; do not repeat new-project setup.

For a project created in the cloud, report the verified private GitHub checkpoint and explain that no folder on the person's computer has been created yet. Give the unchanged permanent prompt and the project's GitHub front-page link so the person can find it again. Computer-local creation can happen later without creating a different project.

## Bring an existing project into a local folder

The saved continuation prompt identifies the project's own repository. First look for an appropriate existing local copy and inspect its remote identity, branch, saved state, and uncommitted changes. Preserve that work before fetching or reconciling shared changes. Do not overwrite an unrelated folder, reset a divergent checkout, or treat GitHub as automatically newer than unsaved local work.

If no suitable local copy exists and the host can write to the person's computer, use ordinary Git to clone the same private repository into a new empty local folder. Reuse the authorized account connection and configured transport. A private repository requires access on this device; follow the setup sections above if a tool or connection is missing. Do not ask the person to run clone commands or choose Git settings. Merely reading repository files through a browser or connector is not a verified Git checkout.

Confirm the actual local path, repository identity, branch and selected commit, required project files, and the recorded project lineage. Read its own AGENTS.md and inspect the installed program and relevant local changes before execution. Run that project's own context and doctor commands to restore the saved goals, decisions, unresolved items, and next work. Install its local Git hook through the supported host route where permitted; active hooks are not transferred by cloning. Compare local and shared state explicitly, and report any incomplete verification honestly.

Preserve the project's permanent continuation prompt. Do not fetch a newer seed, rerun the project installer, initialize a replacement ledger, or create another GitHub repository for a new device or conversation. These instructions govern continuation of this project; they do not authorize changing other existing projects. Once the local copy is verified, work from that folder and continue the same project within the person's authorization.

If a real capability or approval boundary prevents completion, record the precise remaining step and all observed partial state in one complete handoff. The person should receive one useful next action; do not loop them through the same failing environment or send them away solely because a tool has not yet been installed.
