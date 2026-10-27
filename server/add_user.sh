#!/bin/bash
# Registers one employee on the server. Run by the server administrator with sudo.
#
# Usage:   sudo ./add_user.sh <linux-username> "<employee's SSH public key, one line>"
# Example: sudo ./add_user.sh alice "ssh-ed25519 AAAAC3Nza... alice@laptop"
#
# What it does:
#   1) Creates a dedicated Linux account for the employee (home folder mode 700: other employees can't see it)
#   2) Installs kiro-cli in that account
#   3) Makes SSH logins run only the allowed commands (kiro-acp-entry) instead of a shell
set -euo pipefail

USER_NAME="${1:?Enter a username}"
PUBKEY="${2:?Enter the SSH public key}"
ENTRY=/usr/local/bin/kiro-acp-entry

if [ ! -x "$ENTRY" ]; then
  echo "Install kiro-acp-entry.sh at $ENTRY first (guide section 4-1, step 3)." >&2
  exit 1
fi

# 1) Create the account
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd -m "$USER_NAME"
fi
chmod 700 "/home/$USER_NAME"

# 2) Install kiro-cli (as that employee)
#    This is Kiro's official install script (https://kiro.dev/docs/cli/installation/).
#    If your security policy doesn't allow running remote scripts directly, download and review it first.
sudo -iu "$USER_NAME" bash -c 'test -x ~/.local/bin/kiro-cli || curl -fsSL https://cli.kiro.dev/install | bash'
sudo -iu "$USER_NAME" bash -c 'mkdir -p ~/work && ~/.local/bin/kiro-cli --version'

# 3) SSH login = run kiro-acp-entry only
#    restrict: blocks shell, port forwarding, agent forwarding, and so on
#    pty:      re-allows a terminal only, for the SSO login prompt (ssh -t ... login)
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
echo "restrict,pty,command=\"$ENTRY\" $PUBKEY" > "/home/$USER_NAME/.ssh/authorized_keys"
chown "$USER_NAME:$USER_NAME" "/home/$USER_NAME/.ssh/authorized_keys"
chmod 600 "/home/$USER_NAME/.ssh/authorized_keys"

echo "Done: registered $USER_NAME. Next, set up authentication (guide 2-A or 2-B)."
