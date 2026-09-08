"""Read-only setup probes; network is opt-in. No credentials or raw errors are emitted.

This checks executables, CLI identity, and read-only Git transport. It cannot
inspect an assistant's connectors or prove private-repository creation/push
permissions, persistent folder suitability, or that the whole setup can finish.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys


LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
MISSING_REPOSITORY = "Network probes require an explicit --repository HTTPS GitHub URL."


def repository_url(value):
    match = re.fullmatch(r"https://github\.com/(" + LOGIN + r")/([A-Za-z0-9_.-]{1,100})", value)
    if not match or match[2] in {".", "..", ".git"}:
        raise argparse.ArgumentTypeError("Use an HTTPS github.com owner/repository URL without credentials or extra URL components.")
    return value


def timeout_seconds(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if not 1 <= number <= 120:
        raise argparse.ArgumentTypeError("Timeout must be an integer from 1 through 120 seconds.")
    return number


def classify_error(stderr, service):
    """Interpret privately captured diagnostics; return only fixed categories."""
    message = stderr.lower()
    if service == "git" and (
        ("load key" in message and any(term in message for term in ("permission denied", "invalid format")))
        or "unprotected private key file" in message or "bad permissions" in message
    ):
        return "transport_access_blocked"
    if service == "api" and (re.search(r"\bhttp\s*401\b", message) or "bad credentials" in message):
        return "bad_credentials"
    if service == "api" and (re.search(r"\bhttp\s*429\b", message) or "rate limit" in message):
        return "api_rate_limited"
    if service == "api" and re.search(r"\bhttp\s*403\b", message):
        return "api_access_denied"
    if any(term in message for term in ("connectex", "socket in a way forbidden", "network is unreachable")):
        return "network_access_blocked"
    if re.search(r"connect to host .*permission denied", message):
        return "network_access_blocked"
    if any(term in message for term in ("could not resolve", "no such host", "name resolution", "connection refused", "connection timed out")):
        return "network_unavailable"
    if any(term in message for term in ("x509", "tls handshake", "certificate verify", "ssl certificate")):
        return "tls_failed"
    if service == "git" and any(term in message for term in ("permission denied (publickey)", "authentication failed")):
        return "transport_authentication_failed"
    return "api_error_unknown" if service == "api" else "transport_error_unknown"


def run_probe(argv, env, timeout, *, discard=False):
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
            stderr=subprocess.DEVNULL if discard else subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env, timeout=timeout,
        )
        return result, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "missing"
    except PermissionError:
        return None, "executable_access_blocked"
    except OSError:
        return None, "execution_error"


def discover(name, env, timeout):
    executable = shutil.which(name)
    if executable is None:
        return None, {"status": "missing"}
    result, error = run_probe([executable, "--version"], env, timeout)
    if error:
        return executable, {"status": error}
    if result.returncode:
        return executable, {"status": "version_probe_failed"}
    version = re.search(r"\b" + re.escape(name) + r" version ([0-9]+(?:\.[0-9]+)+(?:\.windows\.[0-9]+)?)\b", result.stdout)
    return executable, {"status": "available" if version else "version_unrecognized", "version": version[1] if version else None}


def preflight(*, network=False, repository=None, timeout=20):
    if network and repository is None:
        raise argparse.ArgumentTypeError(MISSING_REPOSITORY)
    if repository is not None:
        repository_url(repository)
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1", "GCM_INTERACTIVE": "never", "SSH_ASKPASS_REQUIRE": "never"})
    probes = {"python": {
        "status": "available" if sys.version_info >= (3, 11) else "unsupported",
        "version": ".".join(str(part) for part in sys.version_info[:3]),
    }}
    git, probes["git"] = discover("git", env, timeout)
    gh, probes["github_cli"] = discover("gh", env, timeout)
    for name in ("github_cli_auth", "github_api", "git_transport"):
        probes[name] = {"status": "not_inspected"}
    if network:
        if not gh or probes["github_cli"]["status"] != "available":
            probes["github_cli_auth"] = {"status": "cli_unavailable"}
            probes["github_api"] = {"status": "cli_unavailable"}
        else:
            auth, error = run_probe([gh, "auth", "token", "--hostname", "github.com"], env, timeout, discard=True)
            probes["github_cli_auth"] = {"status": error or ("credential_readable" if auth.returncode == 0 else "no_readable_cli_auth")}
            if error or auth.returncode != 0:
                probes["github_api"] = {"status": "not_inspected_without_readable_cli_auth"}
            else:
                response, error = run_probe([gh, "api", "user", "--hostname", "github.com", "--jq", "{login: .login, id: .id}"], env, timeout)
                if error:
                    probes["github_api"] = {"status": error}
                elif response.returncode:
                    probes["github_api"] = {"status": classify_error(response.stderr + response.stdout, "api")}
                else:
                    try:
                        account = json.loads(response.stdout)
                        valid = (isinstance(account, dict) and set(account) == {"login", "id"}
                                 and isinstance(account["login"], str) and re.fullmatch(LOGIN, account["login"])
                                 and type(account["id"]) is int and account["id"] > 0)
                    except (ValueError, TypeError):
                        valid = False
                    probes["github_api"] = ({"status": "authenticated", "account": account} if valid
                                            else {"status": "identity_response_invalid"})
        if not git or probes["git"]["status"] != "available":
            probes["git_transport"] = {"status": "git_unavailable"}
        else:
            response, error = run_probe([git, "ls-remote", "--", repository, "HEAD"], env, timeout)
            probes["git_transport"] = {"status": error or (
                "read_succeeded" if response.returncode == 0 else classify_error(response.stderr, "git"))}
    local_passed = all(probes[name]["status"] == "available" for name in ("python", "git"))
    if not local_passed:
        status = "probes_blocked"
    elif not network:
        status = "local_probes_passed"
    elif probes["git_transport"]["status"] != "read_succeeded":
        status = "probes_blocked"
    elif probes["github_cli"]["status"] != "available":
        status = "probes_incomplete"
    else:
        status = "network_probes_passed" if probes["github_api"]["status"] == "authenticated" else "probes_blocked"
    return {
        "schema_version": 1, "mode": "network" if network else "offline", "repository": repository,
        "status": status,
        "probes": probes, "route_readiness": "requires_assistant_judgment",
        "assistant_connectors": "unknown_not_inspected",
        "not_proven": ["private_repository_creation_permission", "private_repository_push_permission",
                       "persistent_local_folder_suitability", "complete_setup_route"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Inspect local executables only (the default); no authentication or network calls.")
    mode.add_argument("--network", action="store_true", help="Also query CLI identity and read the supplied GitHub repository through normal Git transport.")
    parser.add_argument("--repository", type=repository_url, help="Explicit repository to read; required with --network.")
    parser.add_argument("--timeout", type=timeout_seconds, default=20, help="Maximum seconds for each subprocess probe (1-120).")
    args = parser.parse_args(argv)
    if args.network and args.repository is None:
        parser.error(MISSING_REPOSITORY)
    print(json.dumps(preflight(network=args.network, repository=args.repository, timeout=args.timeout), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
