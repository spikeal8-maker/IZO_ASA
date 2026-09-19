#!/bin/sh
set -eu

fail() {
    printf '%s\n' "SANDBOX_BOUNDARY_FAIL $1" >&2
    exit 71
}

if env | grep -Eq '^(GH_TOKEN|GITHUB_TOKEN)='; then
    fail "github token environment is present"
fi
printf '%s\n' "TOKEN_ENV_ABSENT=PASS"

if command -v gh >/dev/null 2>&1; then
    if gh auth status >/dev/null 2>&1; then
        fail "gh owner auth is available"
    fi
fi
printf '%s\n' "GH_AUTH_UNAVAILABLE=PASS"

for name in USERPROFILE APPDATA LOCALAPPDATA; do
    if printenv "$name" >/dev/null 2>&1; then
        fail "Windows profile environment is present: $name"
    fi
done
for path in /mnt/c /host_mnt/c /run/desktop/mnt/host/c /windows-profile; do
    if [ -e "$path" ]; then
        fail "Windows host path is reachable: $path"
    fi
done

if command -v git-credential-manager >/dev/null 2>&1; then
    fail "Windows Git Credential Manager is reachable"
fi
printf '%s\n' "WINDOWS_CREDENTIAL_STORE_UNREACHABLE=PASS"

if [ ! -r "$HOME/.ssh/id_ed25519" ] || [ ! -r "$HOME/.ssh/known_hosts" ]; then
    fail "sanitized SSH identity is unavailable"
fi

repo="${IZO_REPOSITORY:-spikeal8-maker/IZO_ASA}"
https_url="https://github.com/${repo}.git"
ssh_url="git@github.com:${repo}.git"

https_log="$(mktemp)"
if git -C /tmp -c credential.helper= -c core.askPass=/bin/false \
    ls-remote "$https_url" HEAD >/dev/null 2>"$https_log"; then
    fail "private HTTPS access unexpectedly succeeded"
fi
if ! grep -Eiq \
    'could not read Username|Authentication failed|Repository not found|terminal prompts disabled' \
    "$https_log"; then
    fail "private HTTPS failed without an authentication-denial signature"
fi
rm -f "$https_log"
printf '%s\n' "HTTPS_PRIVATE_ACCESS_DENIED=PASS"
ssh_head="$(
    git -C /tmp ls-remote "$ssh_url" HEAD 2>/dev/null |
    awk 'NR == 1 { print $1 }'
)"
case "$ssh_head" in
    [0-9a-f][0-9a-f][0-9a-f]*)
        ;;
    *)
        fail "SSH read did not return a commit id"
        ;;
esac
printf '%s\n' "SSH_READ_FETCH=PASS"

probe_dir="$(mktemp -d)"
push_main_log="$(mktemp)"
push_feature_log="$(mktemp)"
cleanup() {
    rm -rf "$probe_dir"
    rm -f "$push_main_log" "$push_feature_log"
}
trap cleanup EXIT INT TERM

git -C "$probe_dir" init -q
git -C "$probe_dir" config user.name "IZO Agent Sandbox Probe"
git -C "$probe_dir" config user.email "sandbox-probe@example.invalid"
git -C "$probe_dir" remote add origin "$ssh_url"
base_sha="${IZO_PACKAGE_BASE_SHA:-}"
if [ -n "$base_sha" ]; then
    git -C "$probe_dir" fetch -q --depth=1 origin "$base_sha"
else
    git -C "$probe_dir" fetch -q --depth=1 origin refs/heads/main
fi
git -C "$probe_dir" checkout -q --detach FETCH_HEAD

if git -C "$probe_dir" push --no-verify --dry-run \
    origin HEAD:refs/heads/main \
    >/dev/null 2>"$push_main_log"; then
    fail "read-only deploy key unexpectedly accepted main push"
fi
if ! grep -Eiq \
    'marked as read only|write access|permission.*denied|read-only' \
    "$push_main_log"; then
    cat "$push_main_log" >&2
    fail "main push failed without a server-side read-only denial signature"
fi
printf '%s\n' "PUSH_MAIN_SERVER_SIDE_DENIED=PASS"

if git -C "$probe_dir" push --no-verify --dry-run \
    origin HEAD:refs/heads/agent/credential-isolation-probe \
    >/dev/null 2>"$push_feature_log"; then
    fail "read-only deploy key unexpectedly accepted feature push"
fi
if ! grep -Eiq \
    'marked as read only|write access|permission.*denied|read-only' \
    "$push_feature_log"; then
    cat "$push_feature_log" >&2
    fail "feature push failed without a server-side read-only denial signature"
fi
printf '%s\n' "PUSH_FEATURE_SERVER_SIDE_DENIED=PASS"

printf '%s\n' "SANDBOX_BOUNDARY_OK repo=$repo"
