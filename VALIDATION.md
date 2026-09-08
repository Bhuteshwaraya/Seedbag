# Seedbag 0.3.2 validation

The release program passed **80 tests**, with zero failures, errors, or skips, on Windows 11 using Python 3.12.14 and Git 2.53.0.windows.3. The run took 51.434 seconds. The included `validation/tests.json` identifies the exact tested Python files by SHA-256; `validation/tests.txt` contains the complete named results. The public repository also runs the suite through GitHub Actions on Windows and Ubuntu with Python 3.11 and 3.12; consult the run for its result rather than treating configuration as a passing check.

The assistant or maintainer runs the included suite from this package. This is not a project-creation step for the user:

```sh
python -B -m unittest discover -s tests -v
```

Use an available Python 3.11+ executable. Git tests use disposable local repositories and local bare remotes. They do not require GitHub access, change a live project, or execute effects against an external service. Some fixtures remain under the command's `work/` directory for inspection.

Coverage: 23 continuity and adversarial scenarios, 14 context/view scenarios, 20 Git scenarios, 2 installed-CLI lifecycle scenarios, and 21 setup-probe scenarios. The checks cover source/disposition rules, pending input, stale transactions, history preservation, changed files and requirements, check provenance, interrupted actions and rendering, exact context budgets, generated-view edits, portable interpreter resolution, explicit incomplete savepoints, staged-file correctness, merge parents, shallow history, committed rollback, fresh-clone recovery, license-notice propagation, and a real local commit hook. The installed lifecycle checks that the permanent continuation prompt contains the project locator, contains no executable setup command, and remains byte-identical through project updates and a fresh clone. It verifies that the first-time guide and helper travel with the project and that the cloned helper runs offline.

Setup probes use deterministic subprocess fixtures for missing Git/CLI, absent or unreadable credentials, actual rejected credentials, network/TLS errors, access denial/rate limits, a valid account with an unreadable existing Git key, and successful read probes. They check secret-output suppression, preserved transport configuration, optional CLI behavior, offline execution without auth/network calls, and explicit validated network targets. These fixtures do not create an account, install missing software on a clean OS, or prove private repository push permission.

The read-only network probe was also exercised against an existing real connection. It correctly separated authenticated API access from an unreadable configured Git key. The live project-creation test remained blocked before creating a repository; private publication and fresh-device resumption through GitHub have not passed that live test. This local access fault is not repaired by the package. Controlled document reviews cover newcomer setup, existing working connections, broken transport, and unavailable local files; these are not executed ChatGPT Work cloud sessions or proof of universal assistant compliance.

The creation prompt and assistant bootstrap protocol are also reviewed as an interface: the person supplies a name and project goals, while the assistant handles technical setup and capability routing. This review does not prove that every AI application will follow the prompt or possess the required tools. An unavailable capability requires a complete handoff and an honest saved/shared status, not a fabricated installation.

The guarantees apply to cooperating use of this program. Tests do not establish universal semantic completeness, automatic chat capture, authentication of recorded source labels, every-platform compatibility, distributed exactly-once execution, or long-term performance. A declared test is only as good as its assertions and input coverage. Git hooks can be bypassed; the committed-snapshot audit is available for a reviewer or CI, but no remote branch protection is installed by this package.

`MANIFEST.json` inventories the package bytes, excluding the manifest itself. Planted projects receive their own program copy and never auto-update from this seed. The version number alone does not replace exact source identity when comparing development fixtures or releases.
