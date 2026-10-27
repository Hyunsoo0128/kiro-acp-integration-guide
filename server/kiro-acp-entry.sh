#!/bin/bash
# When an employee connects over SSH, only this script runs instead of a shell
# (set with command= in authorized_keys).
# Install location: /usr/local/bin/kiro-acp-entry (owned by root, mode 755)
#
# Employees can use only the commands below. Everything else is refused.
#   ssh user@server                       -> run kiro-cli acp (the default, used by the in-house app)
#   ssh user@server acp-v3                -> run kiro-cli acp with the V3 engine
#   ssh user@server set-api-key < keyfile -> register my API key (method 2-A)
#   ssh user@server remove-api-key        -> delete my API key
#   ssh -t user@server login              -> company SSO login (method 2-B, -t required)
#   ssh user@server logout                -> SSO logout
#   ssh user@server whoami                -> show current authentication status
#
# The authentication method is chosen automatically:
#   if ~/.kiro_api_key exists, use the API key; otherwise use this account's SSO login.
set -euo pipefail

KIRO_CLI="$HOME/.local/bin/kiro-cli"
KEY_FILE="$HOME/.kiro_api_key"
WORK_DIR="$HOME/work"
CONF=/etc/kiro-acp.conf   # set by the administrator: KIRO_IDC_START_URL, KIRO_IDC_REGION

use_api_key_if_present() {
  if [ -f "$KEY_FILE" ]; then
    KIRO_API_KEY="$(cat "$KEY_FILE")"
    export KIRO_API_KEY
  else
    unset KIRO_API_KEY
  fi
}

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# SSH_ORIGINAL_COMMAND: the command the employee put after ssh (empty if none)
case "${SSH_ORIGINAL_COMMAND:-}" in
  "")
    use_api_key_if_present
    exec "$KIRO_CLI" acp
    ;;
  acp-v3)
    use_api_key_if_present
    exec "$KIRO_CLI" acp --agent-engine=v3
    ;;
  set-api-key)
    # Save the key from stdin in this account only. It is never printed.
    umask 077
    IFS= read -r key || true
    key="${key//[$'\r\n ']/}"
    if [[ "$key" != ksk_* ]]; then
      echo "Invalid key format (it must start with ksk_)." >&2
      exit 1
    fi
    printf '%s\n' "$key" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "API key registered."
    ;;
  remove-api-key)
    rm -f "$KEY_FILE"
    echo "API key deleted."
    ;;
  login)
    if [ ! -t 0 ]; then
      echo "Login needs a terminal. Run: ssh -t user@server login" >&2
      exit 1
    fi
    # shellcheck disable=SC1090
    [ -f "$CONF" ] && . "$CONF"
    : "${KIRO_IDC_START_URL:?The administrator must set KIRO_IDC_START_URL in $CONF}"
    : "${KIRO_IDC_REGION:?The administrator must set KIRO_IDC_REGION in $CONF}"
    unset KIRO_API_KEY
    exec "$KIRO_CLI" login --license pro \
      --identity-provider "$KIRO_IDC_START_URL" --region "$KIRO_IDC_REGION" --use-device-flow
    ;;
  logout)
    unset KIRO_API_KEY
    exec "$KIRO_CLI" logout
    ;;
  whoami)
    use_api_key_if_present
    exec "$KIRO_CLI" whoami
    ;;
  *)
    echo "Command not allowed: ${SSH_ORIGINAL_COMMAND}" >&2
    exit 1
    ;;
esac
