# Seedbag 0.3.0 validation

The release program passed **59 tests**, with zero failures, errors, or skips, on Windows 11 using Python 3.12.14 and Git 2.53.0.windows.3. The run took 52.800 seconds. The included `validation/tests.json` identifies the exact tested Python files by SHA-256; `validation/tests.txt` contains the complete named results. The public repository also runs the suite through GitHub Actions on Windows and Ubuntu with Python 3.11 and 3.12; consult the run for its result rather than treating configuration as a passing check.

Run the included suite from this package:

```sh
python -B -m unittest discover -s tests -v
```

Use an available Python 3.11+ executable. Git tests use disposable local repositories and local bare remotes. They do not require GitHub access, change a live project, or execute effects against an external service. Some fixtures remain under the command's `work/` directory for inspection.

Coverage: 23 continuity and adversarial scenarios, 14 context/view scenarios, 20 Git scenarios, and 2 installed-CLI lifecycle scenarios. The checks cover source/disposition rules, pending input, stale transactions, history preservation, changed files and requirements, check provenance, interrupted actions and rendering, exact context budgets, generated-view edits, portable interpreter resolution, explicit incomplete savepoints, staged-file correctness, merge parents, shallow history, committed rollback, fresh-clone recovery, license-notice propagation, and a real local commit hook.

The guarantees apply to cooperating use of this program. Tests do not establish universal semantic completeness, automatic chat capture, authentication of recorded source labels, every-platform compatibility, distributed exactly-once execution, or long-term performance. A declared test is only as good as its assertions and input coverage. Git hooks can be bypassed; the committed-snapshot audit is available for a reviewer or CI, but no remote branch protection is installed by this package.

`MANIFEST.json` inventories the package bytes, excluding the manifest itself. Planted projects receive their own program copy and never auto-update from this seed. The version number alone does not replace exact source identity when comparing development fixtures or releases.
