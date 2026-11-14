#!/usr/bin/env bash
# One command readies an Ubuntu machine for this project. Run from anywhere:
#   ./scripts/bootstrap.sh            (extra arguments go to ansible-playbook, e.g. --tags verify)
# Safe to run again: everything below installs only what's missing.
set -euo pipefail

UV_VERSION="0.13.0"                       # same uv as the Dockerfile and the dev-toolchain role
cd "$(dirname "$0")/.."                   # the repo root, where ansible.cfg and bootstrap.yml live
export PATH="$HOME/.local/bin:$PATH"      # uv and ansible-core install here

# 1. What Ansible itself needs: curl (uv installer), git (ansible-galaxy clones the role),
#    python3-apt (Ansible's apt module, used by the role).
missing=()
for pkg in curl git python3-apt; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "==> Installing prerequisites: ${missing[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y -qq "${missing[@]}"
fi

# 2. uv, then ansible-core as a uv tool
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv ${UV_VERSION}"
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi
if ! command -v ansible-playbook >/dev/null 2>&1; then
  echo "==> Installing ansible-core"
  uv tool install "ansible-core>=2.17"
fi

# 3. The pinned dev-toolchain role, then the playbook
ansible-galaxy role install -r requirements.yml
# -k: ignore a password cached in THIS terminal; Ansible runs sudo without a terminal, so only
# NOPASSWD sudo counts. (sudo -n alone said "yes" right after any sudo use, then Ansible failed.)
if sudo -k -n true 2>/dev/null; then ask=(); else ask=(--ask-become-pass); fi
ansible-playbook bootstrap.yml "${ask[@]}" "$@"
