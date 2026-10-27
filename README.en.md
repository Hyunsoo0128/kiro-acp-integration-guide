# Integrating In-House Apps with Kiro CLI (ACP)

[한국어](README.md) | **English**

> This is sample code for demonstration purposes. Review it against your organization's security and compliance requirements before using it in production.

This guide walks you, step by step, through calling the Kiro agent from an in-house application.
As of this writing (October 2026), there is no official REST API for calling the Kiro agent directly over HTTP. Instead, Kiro CLI officially supports a few integration methods, and this guide covers one of them: **ACP (Agent Client Protocol)**. [Section 0](#0-choosing-an-integration-method) explains how it differs from the others and why ACP is the right fit here.

The guide covers two setups.

| Setup | Where kiro-cli runs | Authentication | Use it when |
|---|---|---|---|
| **Method 1. Employee PC** | Each employee's PC | The employee runs `kiro-cli login` on their PC | A desktop in-house app, and installing on employee PCs is acceptable |
| **Method 2-A. Company server + API key** | Company server (one Linux account per employee) | The employee's own API key | Server-side automation that runs unattended and needs multi-step exchanges within one session |
| **Method 2-B. Company server + SSO login** | Company server (one Linux account per employee) | The employee's own company SSO login | A web or server-based in-house app that should follow your company's SSO policies as-is |

> Every command and result in this guide was run and verified with kiro-cli 2.34.2 (October 2026): macOS on the employee PC and Amazon Linux 2023 on the server. Anything not verified is listed separately in [Section 7](#7-what-was-verified-and-what-was-not).

---

## Contents
0. [Choosing an integration method](#0-choosing-an-integration-method)
1. [ACP on one page](#1-acp-on-one-page)
2. [Common prerequisites](#2-common-prerequisites)
3. [Method 1. Use kiro-cli installed on the employee's PC](#3-method-1-use-kiro-cli-installed-on-the-employees-pc)
4. [Method 2. Use kiro-cli installed on a company server](#4-method-2-use-kiro-cli-installed-on-a-company-server)
5. [Integrating with your in-house app](#5-integrating-with-your-in-house-app)
6. [Troubleshooting](#6-troubleshooting)
7. [What was verified and what was not](#7-what-was-verified-and-what-was-not)

---

## 0. Choosing an integration method

There are three official ways for an external app to call the Kiro agent. All three run kiro-cli underneath. They differ in how closely the app interacts with kiro-cli.

| Method | How you call it | How it interacts | Best for |
|---|---|---|---|
| **Headless mode** | `kiro-cli chat --no-interactive "instruction"` | You pass one instruction; it runs to completion and exits. Tool permissions are set up front with options | CI/CD, batch jobs, scripts |
| **ACP** (this guide) | Start `kiro-cli acp` and exchange JSON-RPC over stdin/stdout | The app and the agent talk both ways for the whole session. The app answers each permission request as it arrives | Embedding the Kiro agent in an in-house app |
| **Kiro Crew** | Install Crew as a resident service and call it through its REST/WebSocket Gateway or the Python client (`kirocrew-client`) | Crew drives kiro-cli over ACP internally. It adds memory, scheduled jobs, sub-agents, and channel connections such as Slack | A resident personal agent for one person; handing off long-running work |

- **Headless mode** authenticates with `KIRO_API_KEY`. With `--output-format stream-json`, you get progress as JSON Lines. ([Headless mode](https://kiro.dev/docs/cli/headless/))
- **Kiro Crew** is open source (Apache 2.0): a personal agent that runs on the user's own machine, local or remote. ([Crew](https://kiro.dev/docs/crew/), [SDK / API reference](https://kiro.dev/docs/crew/apps/sdk/))

### Why ACP for in-house apps

When employees work with Kiro through a conversation inside your app's UI, you need three things.

1. **The conversation must continue.** Employees read an answer, then ask the next question. With ACP, you can keep sending `session/prompt` to one session created with `session/new`. Headless mode handles one instruction per run and exits, so continuing means starting a new process each time.
2. **Tool use must be decided case by case.** When the agent wants to create a file or run a command, ACP asks the app with `session/request_permission`. The app can confirm with the employee, or allow or reject based on company policy. Headless mode assumes nobody is around to ask during the run, so you must decide in advance with `--trust-all-tools` or `--trust-tools`.
3. **The app must control the session directly.** It sets the working folder (`cwd`) and the MCP servers for in-house systems (`mcpServers`) per session, and receives progress (`session/update`) to render in its own UI.

There are also reasons to use ACP directly instead of Kiro Crew.
- Crew is a complete agent product, with a dashboard, memory, and scheduled jobs, designed as a personal agent that one person runs on their own machine. Putting it behind an in-house app where each employee uses their own credentials adds a Crew layer to install and operate between your app and kiro-cli.
- Crew also drives kiro-cli over ACP internally. If your app connects to kiro-cli over ACP directly, it uses the same agent without the extra layer.
- The official Crew Gateway client package is Python only. ACP just needs to start a process and exchange JSON one line at a time, so any language your app uses (Java, C#, Node.js, and so on) works.

> **In short:** headless for one-shot jobs, ACP for back-and-forth work with employees inside your app, and Kiro Crew for a resident personal agent you hand work to.
> Even for automation, use ACP when you need multiple steps in one session or per-tool decisions ([Method 2-A in Section 4](#4-3-authentication-2-a-the-employees-own-api-key)).

---

## 1. ACP on one page

Your app starts a `kiro-cli acp` process and exchanges **JSON one line at a time over that process's stdin/stdout** (JSON-RPC 2.0). No network port is opened.

```
 ┌──────────┐  stdin/stdout (one JSON per line)  ┌──────────────┐        ┌──────────────┐
 │ Your app │ ◄────────────────────────────────► │ kiro-cli acp │ ◄────► │ Kiro service │
 └──────────┘                                    └──────────────┘        └──────────────┘
```

One exchange proceeds in this order.

| Step | Sender | Message | Meaning |
|---|---|---|---|
| 1 | App → Kiro | `initialize` | Start the connection and exchange capabilities |
| 2 | App → Kiro | `session/new` | Create a conversation session (sets the working folder `cwd`) |
| 3 | App → Kiro | `session/prompt` | Send a question |
| 4 | Kiro → App | `session/update` (many times) | Reply chunks and tool progress, in real time |
| 5 | Kiro → App | `session/request_permission` | A permission request such as "May I create this file?" The app answers allow or reject |
| 6 | Kiro → App | Response to step 3 | Reply finished (`stopReason: end_turn`) |

Method 2 (company server) works the same way. Instead of `kiro-cli acp`, the app runs `ssh employee@server`, and the server runs `kiro-cli acp` under that employee's account. **Only the launch command in your app changes.**

---

## 2. Common prerequisites

### 2-1. Kiro subscription
- Companies usually use an **enterprise subscription based on IAM Identity Center**. The administrator assigns Pro, Pro+, or Power plans to employees (or groups).
- Every method in this guide uses **each employee's own subscription and credentials**. Usage and records are therefore kept per employee, and admin policies (MCP, model, and web access restrictions) apply per employee.

> We don't recommend setups where many employees share one key or one account. All usage and records would land under one person's name, and one subscription would effectively be shared by many people.

### 2-2. Example files

```
kiro-acp-integration-guide/
├── README.md                  ← Korean guide
├── README.en.md               ← this guide (English)
├── examples/
│   └── acp_client.py          ← Example ACP client (Python 3.9+, no external dependencies)
└── server/
    ├── add_user.sh            ← Method 2: register an employee on the server
    └── kiro-acp-entry.sh      ← Method 2: the only program that runs when an employee connects over SSH
```

`acp_client.py` shows in a terminal exactly what your app has to do. Once it works, port the same flow to your app's language (Java, C#, Node.js, and so on).

---

## 3. Method 1. Use kiro-cli installed on the employee's PC

Your app on the employee's PC starts `kiro-cli acp` directly.

### Step 1: Install kiro-cli
macOS, Linux:
```bash
curl -fsSL https://cli.kiro.dev/install | bash
```
On Windows, follow the PowerShell command in the [official installation docs](https://kiro.dev/docs/cli/installation/).

Check:
```bash
kiro-cli --version
```
```
kiro-cli 2.34.2
```

### Step 2: Log in
```bash
kiro-cli login
```
When the browser opens, sign in with your company account. Check:
```bash
kiro-cli whoami
```
```
Logged in with IAM Identity Center (https://<company>.awsapps.com/start)
Email: <employee email>
```

### Step 3: Check the ACP connection (one-line test)
```bash
echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  | (cat; sleep 5) | kiro-cli acp
```
If you see one JSON line containing `"result"` like the one below, it works.
```
{"jsonrpc":"2.0","result":{"protocolVersion":1,"agentCapabilities":{"loadSession":true, ...
```

### Step 4: Talk to it with the example client
Move to the folder you want to work in and run the client. The agent uses this folder as its working folder.
```bash
cd ~/my-workspace
python3 /path/to/examples/acp_client.py
```
```
Connected: Kiro CLI Agent 2.34.2
Session created: 42a99e6e-...

Type a question. Press Enter on an empty line to quit.

You> Write "hi" to hello.txt
Kiro>
  [Tool call] Creating hello.txt

[Permission request] Creating hello.txt
Allow? (y/N): y
  -> Allowed: Creating hello.txt
I created hello.txt.
```
(The wording of the reply depends on the question and the model.)

Options:
| Option | Meaning |
|---|---|
| `--prompt "question"` | Send one question and exit |
| `--approve ask` (default) / `all` / `none` | For permission requests: ask every time / allow all / reject all |
| `--cmd "kiro-cli acp --agent-engine=v3"` | Use the V3 engine (see [Section 6](#6-troubleshooting)) |

That completes Method 1. [Section 5](#5-integrating-with-your-in-house-app) explains how to wire this into your app.

### Things to know about Method 1
- The agent creates files and runs commands **on that employee's PC, with that employee's permissions**. Have your app set the working folder (`cwd`) and answer permission requests carefully.
- Usage is attributed to the employee account logged in on that PC.

---

## 4. Method 2. Use kiro-cli installed on a company server

Put kiro-cli on one company server, and let many employees use it, each with their own credentials.

```
 Employee PC / your app                   Company server
 ┌──────────┐   ssh alice@server         ┌───────────────────────────────────┐
 │ Your app │ ─────────────────────────► │ Linux account alice               │
 │ (alice)  │   (one JSON per line)      │  └ kiro-acp-entry → kiro-cli acp  │
 └──────────┘                            │     auth: alice's API key or SSO  │
 ┌──────────┐   ssh bob@server           │ Linux account bob                 │
 │ Your app │ ─────────────────────────► │  └ kiro-acp-entry → kiro-cli acp  │
 │ (bob)    │                            │     auth: bob's API key or SSO    │
 └──────────┘                            └───────────────────────────────────┘
```

Three core principles:
1. **Create a separate Linux account for each employee.** The agent runs commands with that account's permissions. With a shared account, one employee can read another's files (verified). With separate accounts, it's blocked with `Permission denied`.
2. **Make SSH logins run only `kiro-acp-entry`, not a shell.** Employees can't get a shell on the server; they can only use the allowed commands.
3. **Use only the employee's own credentials.** Choose either an API key (2-A) or company SSO login (2-B).

### 4-1. Server setup (administrator, once)

#### Step 1: Size the server
In our measurements, one `kiro-cli acp` session used about 350 MB (V2) to 435 MB (V3) of memory. **Memory, not CPU, is the limit.**

| Measured (2 vCPU, 2 GB memory server) | V2 | V3 |
|---|---|---|
| Memory per session | about 350 MB | about 435 MB |
| 4 concurrent sessions | all succeeded, 1.35 GB server memory used | all succeeded, 1.5 GB used |
| Session ready time (1 → 4 concurrent) | 1.9 s → 4.0 s | 2.7 s → 8.0 s |

Plan for **0.5 GB of memory per concurrent user** to leave headroom. For example, 20 concurrent users means a server in the 16 GB class. These numbers are for short prompts; heavy tasks and 5 or more concurrent users were not measured.

#### Step 2: Network
- Employee PCs (or your app server) must be able to **SSH** to this server.
- The server must be able to reach the Kiro service and your company SSO **outbound (HTTPS)**.
- On AWS EC2, you can also connect with **SSH over SSM Session Manager** without opening port 22. The tests for this guide used that setup (zero inbound rules).

#### Step 3: Install the entry script
Copy this repository's `server/` folder to the server, for example `scp -r server/ <admin>@<server>:~/`. Then run on the server:
```bash
cd ~/server
sudo install -m 755 -o root -g root kiro-acp-entry.sh /usr/local/bin/kiro-acp-entry
```
`kiro-acp-entry` is the **only program** that runs when an employee connects over SSH. Employees can use these commands:

| Command the employee runs | What it does |
|---|---|
| `ssh employee@server` | Run `kiro-cli acp` (the default, used by your app) |
| `ssh employee@server acp-v3` | Run `kiro-cli acp` with the V3 engine |
| `ssh employee@server set-api-key < keyfile` | Register my API key (2-A) |
| `ssh employee@server remove-api-key` | Delete my API key |
| `ssh -t employee@server login` | Company SSO login (2-B) |
| `ssh employee@server logout` | SSO logout |
| `ssh employee@server whoami` | Show current authentication status |
| Anything else | Refused with `Command not allowed: ...` |

The authentication method is chosen automatically. If the employee's account has an API key registered, the API key is used; otherwise the SSO login is used.

#### Step 4: Set your company's SSO details (2-B only)
```bash
sudo tee /etc/kiro-acp.conf <<'EOF'
KIRO_IDC_START_URL=https://<company>.awsapps.com/start
KIRO_IDC_REGION=<IAM Identity Center Region, for example us-east-1>
EOF
sudo chmod 644 /etc/kiro-acp.conf
```
If you don't know the values, run `kiro-cli whoami` on an employee PC that is already logged in; it shows the Start URL. Ask your Kiro administrator for the Region.

### 4-2. Register employees (administrator, per employee)

#### Step 1: The employee creates an SSH key and sends the public key
On the employee's PC:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/kiro-server -C "alice@company"
cat ~/.ssh/kiro-server.pub      # send this one line to the administrator (it's a public key, safe to share)
```

#### Step 2: The administrator registers the employee on the server
Run in the server's `~/server` folder:
```bash
chmod +x add_user.sh
sudo ./add_user.sh alice "ssh-ed25519 AAAAC3Nza... alice@company"
```
It succeeded if the output ends like this (kiro-cli install messages appear above it):
```
kiro-cli 2.34.2
Done: registered alice. Next, set up authentication (guide 2-A or 2-B).
```
The script does the following:
- Creates a dedicated Linux account for the employee. The home folder is mode 700, so other employees can't see it.
- Installs kiro-cli in that account.
- Configures SSH so that logins run only `kiro-acp-entry` (`restrict,pty,command=...`). Shell access and port forwarding are blocked; only a terminal is allowed, for the login prompt.

#### Step 3: SSH settings on the employee's PC (optional, for convenience)
Add this to `~/.ssh/config`, and you can connect with just `ssh kiro-server` from then on.
```
Host kiro-server
    HostName <server address>
    User alice
    IdentityFile ~/.ssh/kiro-server
    IdentitiesOnly yes
```
Now set up authentication. Choose either 2-A or 2-B.

### 4-3. Authentication 2-A: the employee's own API key

#### Step 1: The administrator allows API key creation
Enterprise subscriptions have **API key creation turned off by default** ([docs](https://kiro.dev/docs/enterprise/governance/)). A Kiro administrator must allow it first.

#### Step 2: The employee creates an API key
1. Sign in to [app.kiro.dev](https://app.kiro.dev) with your company account.
2. Go to **Settings → API keys**.
3. Enter a key name (for example, `kiro-server`) and create the key.
4. The key is shown **only once, right now**. It starts with `ksk_`.

> Treat the key like a password. Don't paste it into messengers, email, documents, or chats. If it is exposed by mistake, delete it right away and create a new one.

#### Step 3: Save the key on the employee's PC temporarily
```bash
(umask 077; cat > ~/.kiro-key)
```
The command waits for input. Paste the key, press Enter, then Ctrl+D. Nothing is left in your terminal history or shell history.

#### Step 4: Register the key on the server
```bash
ssh kiro-server set-api-key < ~/.kiro-key
```
```
API key registered.
```
The key is stored only in the employee's account on the server, with mode 600, and is never printed. After registering, you can delete the temporary file on your PC (`rm ~/.kiro-key`).

#### Step 5: Check
```bash
ssh kiro-server whoami
```
```
Authenticated with API key
Email: <employee email>
```
If your own email appears, usage is attributed to you. Continue to [4-5. Verify the connection](#4-5-verify-the-connection-2-a-and-2-b).

### 4-4. Authentication 2-B: the employee's own company SSO login

Instead of keeping a long-lived key on the server, this uses your company SSO login as-is. The administrator must have completed [step 4 of 4-1](#step-4-set-your-companys-sso-details-2-b-only).

#### Step 1: Start the login
On the employee's PC (**`-t` is required**):
```bash
ssh -t kiro-server login
```
You are asked twice, with the Start URL and Region already filled in. Just press **Enter** for both.
```
✔ Enter Start URL · https://<company>.awsapps.com/start
✔ Enter Region · us-east-1
Confirm the following code in the browser
Code: ABCD-EFGH
Open this URL: https://<company>.awsapps.com/start/#/device?user_code=ABCD-EFGH
▰▱▱▱▱▱▱ Logging in...
```

#### Step 2: Approve in the browser
1. Open the URL shown in a browser on the employee's PC. The code expires within a few minutes, so do this right away.
2. Sign in with your company account.
3. On the "Authorization requested" page, **check that the code matches** the one in your terminal, then choose **Confirm and continue**.
4. If an access approval (Allow) page appears next, allow it.

It's done when the terminal shows:
```
Device authorized
Logged in successfully
```

> If the codes don't match, or you didn't start this login, choose **Cancel**. If you approve a link someone else sent you, your account gets logged in on their server.

#### Step 3: Check
```bash
ssh kiro-server whoami
```
```
Logged in with IAM Identity Center (https://<company>.awsapps.com/start)
Email: <employee email>
```
- The login data is stored only in the employee's account on the server (`~/.local/share/kiro-cli/data.sqlite3`, mode 600). Other employee accounts can't read it (verified).
- When you're done, run `ssh kiro-server logout`. After logout, `kiro-cli acp` no longer starts (verified).
- When the SSO session expires, log in again from step 1. The expiry time follows your company's IAM Identity Center settings.

### 4-5. Verify the connection (2-A and 2-B)
From the employee's PC, use the example client to talk to kiro-cli on the server. Because it's a remote server, give the working folder (`--cwd`) as a **server-side path** (the employee account's `~/work`).
```bash
python3 examples/acp_client.py --cmd "ssh kiro-server" --cwd /home/alice/work
```
```
Connected: Kiro CLI Agent 2.34.2
Session created: ...

You> Write "hi" to hello.txt
Kiro>
  [Tool call] Creating hello.txt
...
```
For the V3 engine, use `--cmd "ssh kiro-server acp-v3"`.

If you are not authenticated (no key registered, not logged in yet, or logged out), you'll see this. Go back to 4-3 or 4-4 and set up authentication.
```
Error: Lost connection to kiro-cli.
error: You are not logged in, please log in with kiro-cli login
```

### Choosing between 2-A and 2-B

| | 2-A. API key | 2-B. SSO login |
|---|---|---|
| Administrator prerequisite | Allow API key creation (off by default) | Configure `/etc/kiro-acp.conf` |
| Employee's first-time setup | Create a key on the web → `set-api-key` | `ssh -t ... login` → approve in the browser |
| What stays on the server | A long-lived key | Company SSO session data |
| Re-authentication | Not needed while the key is valid | Needed when the SSO session expires |
| Company SSO policy (MFA, session length) applies | Only when the key is created | At every login |
| Good fit | Automation where a person can't approve each time | In-house apps used by people |

---

## 5. Integrating with your in-house app

Port the flow in `examples/acp_client.py` to your app's language. The only difference between Method 1 and Method 2 is **the command that starts the process**.

| Setup | Command your app runs | `cwd` in `session/new` |
|---|---|---|
| Method 1 | `kiro-cli acp` | A working folder on the employee's PC |
| Method 2 | `ssh -i <employee key> <employee>@<server>` | `/home/<employee>/work` on the server |

Rules to follow when you implement it:
1. **Read messages one line at a time and classify them.**
   - Both `id` and `method`: a request from the agent. You must answer it.
   - `method` only: a notification.
   - `id` only: the response to a request you sent.
2. **Always answer the agent's requests.** Even for requests you don't recognize, reply with an error so the agent doesn't hang waiting.
3. **Choose permission options by `kind`, not `optionId`.** `optionId` differs by engine. For example, allow is `allow_once` in V2 and `accept` in V3. The `kind` values (`allow_once`, `reject_once`, and so on) are the same.
4. **Keep reading stderr to drain it.** If you don't, the buffer can fill up and block kiro-cli.
5. **Show replies as they arrive.** `agent_message_chunk` in `session/update` carries reply chunks.
6. **Connect in-house systems through `mcpServers` in `session/new`**, by passing MCP servers there. This guide doesn't cover that.

If you need a desktop GUI example, see the official AWS sample [aws-samples/sample-kiro-acp-ui](https://github.com/aws-samples/sample-kiro-acp-ui) (Python, tkinter). That sample also works with Method 2 once you change its launch command to `ssh ...`. With the V3 engine, though, its model list looks empty, because V3 sends the model list in `configOptions`.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Exits right after `error: You are not logged in, please log in with kiro-cli login` | The account has neither a login nor an API key | Method 1: `kiro-cli login`. Method 2: `set-api-key` or `ssh -t ... login` |
| `invalid value for field 'region'` during server login | Run without a terminal | Run with `ssh -t`. Without `-t`, `kiro-acp-entry` prints a hint instead |
| `the following arguments are not supported with --agent-engine=v3: --trust-all-tools` | V3 doesn't support this option | With V3, have your app answer permission requests, or use a V3 permission policy file |
| The model list is empty with V3 | V3 sends the model list in `configOptions` (id `model`) of the `session/new` response | Read both `models` and `configOptions` |
| `Command not allowed: ...` | In Method 2, only the allowed commands work | Use only the commands in the [table in 4-1](#step-3-install-the-entry-script) |
| `Invalid key format (it must start with ksk_).` | Tried to register something that isn't a key | Check that the key starts with `ksk_` |
| `post-quantum key exchange` warning when connecting over SSH | Notice about the server's OpenSSH version | Doesn't affect operation. Consider upgrading OpenSSH on the server |
| Replies stop partway | The app didn't answer an agent request, or didn't drain stderr | Check items 1, 2, and 4 in [Section 5](#5-integrating-with-your-in-house-app) |

---

## 7. What was verified and what was not

**Verified by actually running it** (kiro-cli 2.34.2, the default V2 engine and V3)
- Method 1: the example client answered questions, allowed and rejected permissions (no file is created when rejected), and continued a conversation in the same session
- Method 2-A: registered a new employee with `add_user.sh` → `set-api-key` → `whoami` showed the key owner's email → the example client created files remotely (V2, V3). Without a key, it exits at startup; a key in the wrong format is refused
- Method 2-B: registered a new employee with `add_user.sh` → `ssh -t ... login` → approved in the browser → the example client created files remotely without an API key (V2, V3) → blocked immediately after `logout`. Running `login` without `-t` is refused with a hint
- Per-employee accounts: an employee can't read other employees' files, login data, or process environment variables. With a shared account, they can
- Access restrictions: commands outside the allowed list are refused (`cat /etc/passwd`, `bash -i`); port forwarding is blocked
- Concurrency: 4 concurrent sessions (V2 and V3 each)

**Not verified** (check with the Kiro team or your administrator before adoption)
- Whether usage is attributed separately to two different employees' keys or logins (tests used one account only; the docs and the `whoami` output indicate it should work that way)
- Whether an API key or SSO login left on the server is blocked immediately when the employee is removed from IAM Identity Center or their subscription is removed
- Whether API key creation can be allowed only for specific groups, and whether administrators can enforce key expiry
- Whether a per-employee usage cap (overage credits) can be set
- The actual SSO session expiry and refresh interval
- Resource usage and Kiro service request limits with 5 or more concurrent sessions or long-running tasks
- Method 1 and the example client on Windows employee PCs

---

## References
- [ACP integrations](https://kiro.dev/docs/acp/) · [Kiro CLI ACP](https://kiro.dev/docs/cli/acp/)
- [Headless mode (API keys)](https://kiro.dev/docs/cli/headless/)
- [V3 ACP client migration](https://kiro.dev/docs/cli/v3/acp-migration/)
- [Enterprise governance (allowing API keys)](https://kiro.dev/docs/enterprise/governance/)
- [Kiro CLI installation](https://kiro.dev/docs/cli/installation/)
- [Kiro Crew](https://kiro.dev/docs/crew/) · [Crew SDK / API reference](https://kiro.dev/docs/crew/apps/sdk/)
- [aws-samples/sample-kiro-acp-ui](https://github.com/aws-samples/sample-kiro-acp-ui)

---

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
