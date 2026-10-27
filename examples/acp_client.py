#!/usr/bin/env python3
"""Minimal example client that talks to kiro-cli over ACP (Agent Client Protocol).

It contains only the core flow an in-house app needs to integrate with kiro-cli:
  1) Start a `kiro-cli acp` process (locally, or on a server over ssh)
  2) Create a session with initialize -> session/new
  3) Send a question with session/prompt and receive streamed replies (session/update)
  4) Answer when the agent asks permission to run a tool (session/request_permission)

Uses only the Python 3.9+ standard library. No external dependencies.

Examples:
  # Method 1: kiro-cli installed on this PC
  python3 acp_client.py

  # Method 2: kiro-cli on a company server (the server runs kiro-cli acp when you connect over SSH)
  python3 acp_client.py --cmd "ssh -i ~/.ssh/kiro-server alice@kiro-server.example.com" \
      --cwd /home/alice/work

  # Send one question and exit
  python3 acp_client.py --prompt "List the files in this folder"
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading


class AcpClient:
    """Client that exchanges one JSON message per line (JSON-RPC 2.0) with kiro-cli acp."""

    def __init__(self, cmd, approve):
        # approve: "ask" (ask every time) | "all" (allow everything) | "none" (reject everything)
        self.approve = approve
        self.next_id = 0
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        # If nobody reads stderr, its buffer can fill up and block kiro-cli, so drain it separately.
        self.stderr_tail = []
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self):
        for line in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-20:]

    # ---------- Low-level send/receive ----------

    def _send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        """Read the next JSON message. Lines that are not JSON are skipped."""
        while True:
            line = self.proc.stdout.readline()
            if not line:
                tail = "\n".join(self.stderr_tail[-5:])
                raise RuntimeError(f"Lost connection to kiro-cli.\n{tail}")
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)

    def request(self, method, params, on_notification=None):
        """Send a request and wait for the response with the same id.

        Notifications and agent requests that arrive while waiting are handled, not dropped.
        """
        req_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        while True:
            msg = self._read()
            if "method" in msg and "id" in msg:
                self._handle_agent_request(msg)  # agent -> client request
            elif "method" in msg:
                if on_notification:
                    on_notification(msg)  # notification (no reply needed)
            elif msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"{method} failed: {msg['error']}")
                return msg.get("result") or {}

    # ---------- Requests sent by the agent ----------

    def _handle_agent_request(self, msg):
        if msg["method"] == "session/request_permission":
            result = self._decide_permission(msg["params"])
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        else:
            # Reply "not supported" to requests this example doesn't know,
            # so the agent doesn't hang waiting for an answer.
            self._send({"jsonrpc": "2.0", "id": msg["id"],
                        "error": {"code": -32601, "message": f"Method not found: {msg['method']}"}})

    def _decide_permission(self, params):
        title = params.get("toolCall", {}).get("title", "Unknown action")
        options = params.get("options", [])
        # optionId differs by engine (v2/v3), so always choose by kind (allow_once, reject_once, ...).
        by_kind = {o.get("kind"): o["optionId"] for o in options}

        if self.approve == "all":
            choice = "allow_once"
        elif self.approve == "none":
            choice = "reject_once"
        else:
            answer = input(f"\n[Permission request] {title}\nAllow? (y/N): ").strip().lower()
            choice = "allow_once" if answer == "y" else "reject_once"

        option_id = by_kind.get(choice)
        if option_id is None:
            return {"outcome": {"outcome": "cancelled"}}
        print(f"  -> {'Allowed' if choice == 'allow_once' else 'Rejected'}: {title}")
        return {"outcome": {"outcome": "selected", "optionId": option_id}}

    # ---------- ACP flow ----------

    def initialize(self):
        return self.request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "acp-client-example", "version": "1.0.0"},
        })

    def new_session(self, cwd):
        # cwd: the folder the agent works in. On a remote server it must be a server-side path.
        # mcpServers: MCP servers for in-house systems can be passed here (empty in this example).
        return self.request("session/new", {"cwd": cwd, "mcpServers": []})

    def prompt(self, session_id, text):
        """Send a question and print the reply as it streams in."""

        def on_update(msg):
            if msg.get("method") != "session/update":
                return  # ignore other Kiro extension notifications
            update = msg["params"].get("update", {})
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                content = update.get("content", {})
                if content.get("type") == "text":
                    print(content["text"], end="", flush=True)
            elif kind == "tool_call":
                print(f"\n  [Tool call] {update.get('title', '')}", flush=True)

        result = self.request("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": text}],
        }, on_notification=on_update)
        print()
        return result.get("stopReason")

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main():
    parser = argparse.ArgumentParser(description="kiro-cli ACP example client")
    parser.add_argument("--cmd", default="kiro-cli acp",
                        help='command that starts kiro-cli (default: "kiro-cli acp"; '
                             'for a server: "ssh user@server")')
    parser.add_argument("--cwd", default=None,
                        help="agent working folder, absolute path "
                             "(default: current folder; required with ssh)")
    parser.add_argument("--prompt", default=None, help="send one question and exit")
    parser.add_argument("--approve", choices=["ask", "all", "none"], default="ask",
                        help="how to answer tool permission requests (default: ask every time)")
    args = parser.parse_args()

    cmd = shlex.split(args.cmd)
    is_remote = cmd[0] == "ssh"
    if is_remote and not args.cwd:
        # For a remote server the working folder must be an absolute server-side path, so ask for it.
        parser.error("When connecting over ssh, set --cwd to the working folder on the server. "
                     "Example: --cwd /home/alice/work")
    cwd = args.cwd or os.getcwd()

    client = AcpClient(cmd, args.approve)
    try:
        info = client.initialize()
        agent = info.get("agentInfo", {})
        print(f"Connected: {agent.get('name', 'Kiro')} {agent.get('version', '')}".strip())

        session = client.new_session(cwd)
        session_id = session["sessionId"]
        print(f"Session created: {session_id}\n")

        if args.prompt:
            client.prompt(session_id, args.prompt)
            return
        print("Type a question. Press Enter on an empty line to quit.")
        while True:
            text = input("\nYou> ").strip()
            if not text:
                break
            print("Kiro> ", end="", flush=True)
            client.prompt(session_id, text)
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        # When kiro-cli exits (for example, not logged in), show only the cause.
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
