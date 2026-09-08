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
ACTION_MESSAGES = {
    "reuse_available_tools": "Reuse the available execution tools; do not reinstall tools that passed their probes.",
    "supply_supported_python": "Locate or supply a supported Python interpreter through the host's supported route.",
    "supply_missing_git": "Locate or supply missing Git through the host's supported route.",
    "verify_git_installation": "Inspect the failed Git executable/version probe before changing the installation.",
    "inspect_existing_connection": "Check existing host connections and protected configuration before sign-in; GitHub CLI is optional when another supported route supplies the required operations.",
    "reuse_authenticated_connection": "Reuse the authenticated account connection; do not repeat login or replace working credentials.",
    "renew_rejected_connection": "The API explicitly rejected its credential; renew the existing connection through the approved user-owned sign-in surface.",
    "preserve_credentials": "Preserve existing credentials and transport choices while diagnosing the reported fault; this fault alone is not evidence that login must be reset.",
    "resolve_network_access": "Use the host's supported network access route for the selected repository; do not replace credentials to cross a network boundary.",
    "resolve_network_failure": "Check the reported network or service failure through the host's supported route; do not change the connection protocol automatically.",
    "verify_tls": "Check the TLS failure through the supported trust/network route; keep certificate verification enabled.",
    "check_api_access": "Check account permissions and service restrictions for the failed API request; do not infer expired credentials from a denial.",
    "respect_api_rate_limit": "Respect the reported API rate limit and retry through the supported route when allowed.",
    "inspect_api_failure": "Inspect the failed API or identity probe using sanitized evidence; do not assume a credential failure.",
    "reuse_working_transport": "Reuse the configured Git transport that passed its read probe.",
    "verify_private_publication": "Verify the intended private repository and its authorized publication checkpoint; a successful read alone does not prove private write access.",
    "verify_repository_ownership": "Verify the exact checkout and its ownership under the intended execution user. Use only an exact trusted-path exception if justified and permitted; never wildcard safe.directory trust.",
    "verify_ssh_host": "Verify the SSH host identity against the provider's current published fingerprints before changing known hosts; do not disable host verification.",
    "inspect_key_format": "Inspect the configured key format through the supported user-owned route without exposing key contents; do not treat malformed key data as an ACL failure.",
    "verify_key_access": "Verify supported execution under the intended user before considering an exact-file ownership or access repair through the host's permitted approval route; do not widen key access.",
    "inspect_git_helper": "Inspect the named Git helper and installation from a fresh supported execution context. Preserve authentication and configured transport; do not copy helpers, inject credentials, or bypass host rules.",
    "inspect_transport_authentication": "Check the configured Git credential/key route and repository authorization; a Git authentication failure alone does not justify resetting working API credentials.",
    "inspect_transport_failure": "Inspect the failed Git transport probe through the supported execution route using sanitized evidence before changing authentication or configuration.",
}


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
    if service == "git" and "detected dubious ownership in repository" in message:
        return "repository_ownership_untrusted"
    if service == "git" and any(term in message for term in (
        "host key verification failed", "remote host identification has changed",
    )):
        return "ssh_host_verification_failed"
    if service == "git" and "load key" in message and "invalid format" in message:
        return "transport_key_invalid"
    if service == "git" and (
        ("load key" in message and "permission denied" in message)
        or "unprotected private key file" in message or "bad permissions" in message
    ):
        return "transport_access_blocked"
    if service == "git" and re.search(r"(?:git-)?remote-https?\b|(?:git-)?credential-(?:manager|[a-z0-9_-]+)\b", message) and any(
        term in message for term in ("cannot spawn", "cannot run", "could not execute", "unable to find remote helper",
                                    "not a git command", "no such file", "died of signal", "access violation", "0xc0000005")
    ):
        return "transport_helper_failed"
    if service == "git" and "unable to find remote helper for 'http" in message:
        return "transport_helper_failed"
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


def recommended_actions(probes, *, network):
    """Select fixed guidance from observations, without performing more probes."""
    selected = []

    def add(action):
        if action not in selected:
            selected.append(action)

    if probes["python"]["status"] == "available" or probes["git"]["status"] == "available":
        add("reuse_available_tools")
    if probes["python"]["status"] != "available":
        add("supply_supported_python")
    if probes["git"]["status"] == "missing":
        add("supply_missing_git")
    elif probes["git"]["status"] != "available":
        add("verify_git_installation")
    if network:
        api = probes["github_api"]["status"]
        if probes["github_cli"]["status"] != "available" or probes["github_cli_auth"]["status"] != "credential_readable":
            add("inspect_existing_connection")
        if api == "authenticated":
            add("reuse_authenticated_connection")
        elif api == "bad_credentials":
            add("renew_rejected_connection")
        elif api not in {"cli_unavailable", "not_inspected_without_readable_cli_auth"}:
            add("preserve_credentials")
            add({
                "network_access_blocked": "resolve_network_access", "network_unavailable": "resolve_network_failure",
                "timeout": "resolve_network_failure", "tls_failed": "verify_tls",
                "api_access_denied": "check_api_access", "api_rate_limited": "respect_api_rate_limit",
            }.get(api, "inspect_api_failure"))
        transport = probes["git_transport"]["status"]
        if transport == "read_succeeded":
            add("reuse_working_transport")
            add("verify_private_publication")
        elif transport != "git_unavailable":
            add("preserve_credentials")
            add({
                "network_access_blocked": "resolve_network_access", "network_unavailable": "resolve_network_failure",
                "timeout": "resolve_network_failure", "tls_failed": "verify_tls",
                "repository_ownership_untrusted": "verify_repository_ownership",
                "ssh_host_verification_failed": "verify_ssh_host", "transport_key_invalid": "inspect_key_format",
                "transport_access_blocked": "verify_key_access", "transport_helper_failed": "inspect_git_helper",
                "transport_authentication_failed": "inspect_transport_authentication",
            }.get(transport, "inspect_transport_failure"))
    return [{"id": action, "message": ACTION_MESSAGES[action]} for action in selected]


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
        "recommended_actions": recommended_actions(probes, network=network),
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
