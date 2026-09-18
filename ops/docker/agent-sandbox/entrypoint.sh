#!/bin/sh
set -eu

fail() {
    printf '%s\n' "AGENT_SANDBOX_ENTRYPOINT_ERROR $1" >&2
    exit 70
}

if env | grep -Eq '^(GH_TOKEN|GITHUB_TOKEN)='; then
    fail "GITHUB_TOKEN_ENV_PRESENT"
fi

for name in USERPROFILE APPDATA LOCALAPPDATA; do
    if printenv "$name" >/dev/null 2>&1; then
        fail "WINDOWS_PROFILE_ENV_PRESENT name=$name"
    fi
done

if [ ! -r /run/izo-ssh/id ]; then
    fail "READONLY_DEPLOY_KEY_UNAVAILABLE"
fi
if [ ! -r /run/izo-ssh/known_hosts ]; then
    fail "KNOWN_HOSTS_UNAVAILABLE"
fi

umask 077
mkdir -p "$HOME/.ssh" "$HOME/.config/gh"
cp /run/izo-ssh/id "$HOME/.ssh/id_ed25519"
cp /run/izo-ssh/known_hosts "$HOME/.ssh/known_hosts"
chmod 600 "$HOME/.ssh/id_ed25519"
chmod 644 "$HOME/.ssh/known_hosts"

cat > "$HOME/.gitconfig" <<'EOF'
[credential]
    helper =
[core]
    askPass = /bin/false
EOF
chmod 600 "$HOME/.gitconfig"

export GIT_CONFIG_GLOBAL="$HOME/.gitconfig"
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/known_hosts"

if [ "$#" -eq 1 ] && [ "$1" = "boundary-probe" ]; then
    exec /usr/local/bin/izo-agent-boundary-probe
fi

git_dir="/tmp/izo-agent-git"
rm -rf "$git_dir"
git init --bare -q "$git_dir"
git --git-dir="$git_dir" remote add origin "git@github.com:${IZO_REPOSITORY}.git"
git --git-dir="$git_dir" fetch -q --depth=1 origin "${IZO_PACKAGE_BASE_SHA}"
git --git-dir="$git_dir" update-ref refs/heads/package FETCH_HEAD
git --git-dir="$git_dir" symbolic-ref HEAD refs/heads/package
git --git-dir="$git_dir" config core.bare false
git --git-dir="$git_dir" config core.autocrlf true
git --git-dir="$git_dir" config core.filemode false
git --git-dir="$git_dir" config core.symlinks false

export GIT_DIR="$git_dir"
export GIT_WORK_TREE=/workspace
git read-tree FETCH_HEAD

printf '%s\n' "AGENT_SANDBOX_GIT_VIEW base=${IZO_PACKAGE_BASE_SHA} metadata=ephemeral"
exec "$@"
