# 사내 앱과 Kiro CLI 연동 가이드 (ACP 기반)

**한국어** | [English](README.en.md)

> **English summary**
> This guide shows how to call the Kiro agent from an in-house application through the Agent Client Protocol (ACP) supported by Kiro CLI. It covers two setups: running `kiro-cli acp` on each employee's PC, and running it on a shared company server where every employee has a separate Linux account and authenticates with their own API key or SSO login. It also explains when to choose ACP over Kiro CLI headless mode or Kiro Crew. The repository includes a dependency-free Python ACP client (`examples/acp_client.py`) and server scripts (`server/`). Tested with kiro-cli 2.34.2 on macOS and Amazon Linux 2023 (October 2026).
>
> This is sample code for demonstration purposes. Review it against your organization's security and compliance requirements before using it in production.
>
> Full English version: [README.en.md](README.en.md)

사내 앱에서 Kiro 에이전트를 호출하는 방법을 처음부터 따라 할 수 있게 정리한 문서입니다.
작성 시점(2026년 10월) 기준으로 Kiro 에이전트를 HTTP로 바로 호출하는 공식 REST API는 없습니다. 대신 Kiro CLI가 공식 지원하는 연동 방식이 몇 가지 있고, 이 문서는 그중 **ACP(Agent Client Protocol)** 를 다룹니다. 다른 방식과의 차이와 ACP를 고른 이유는 [0장](#0-연동-방식-고르기)에 정리했습니다.

이 문서는 두 가지 구성을 다룹니다.

| 구성 | kiro-cli 위치 | 인증 | 이런 경우에 |
|---|---|---|---|
| **방법 1. 직원 PC** | 각 직원 PC | 직원이 PC에서 `kiro-cli login` | 데스크톱용 사내 앱. 직원 PC에 설치해도 될 때 |
| **방법 2-A. 회사 서버 + API 키** | 회사 서버 (직원별 리눅스 계정) | 직원 본인의 API 키 | 사람 없이 도는 서버형 자동화. 한 세션에서 여러 단계를 주고받아야 할 때 |
| **방법 2-B. 회사 서버 + SSO 로그인** | 회사 서버 (직원별 리눅스 계정) | 직원 본인의 회사 SSO 로그인 | 웹이나 서버형 사내 앱. 회사 SSO 정책을 그대로 따르게 하고 싶을 때 |

> 이 문서의 모든 명령과 결과는 kiro-cli 2.34.2로 직접 실행해 확인했습니다(2026년 10월). 직원 PC는 macOS, 서버는 Amazon Linux 2023입니다. 확인하지 못한 부분은 [7. 확인된 범위](#7-확인된-범위와-확인하지-못한-것)에 따로 적었습니다.

---

## 목차
0. [연동 방식 고르기](#0-연동-방식-고르기)
1. [ACP 한 장 요약](#1-acp-한-장-요약)
2. [공통 준비](#2-공통-준비)
3. [방법 1. 직원 PC에 설치된 kiro-cli 사용](#3-방법-1-직원-pc에-설치된-kiro-cli-사용)
4. [방법 2. 회사 서버에 설치된 kiro-cli 사용](#4-방법-2-회사-서버에-설치된-kiro-cli-사용)
5. [사내 앱에 붙이기](#5-사내-앱에-붙이기)
6. [자주 겪는 문제](#6-자주-겪는-문제)
7. [확인된 범위와 확인하지 못한 것](#7-확인된-범위와-확인하지-못한-것)

---

## 0. 연동 방식 고르기

외부 앱에서 Kiro 에이전트를 부르는 공식 방법은 세 가지입니다. 셋 다 결국 kiro-cli를 실행하는 구조이고, 앱이 kiro-cli와 얼마나 긴밀하게 주고받느냐가 다릅니다.

| 방식 | 부르는 방법 | 주고받는 방식 | 잘 맞는 경우 |
|---|---|---|---|
| **헤드리스 모드** | `kiro-cli chat --no-interactive "지시"` | 지시 하나를 넘기면 끝까지 실행하고 종료합니다. 도구 실행 권한은 실행 전에 옵션으로 정합니다 | CI/CD, 배치, 스크립트 |
| **ACP** (이 문서) | `kiro-cli acp`를 띄우고 stdin/stdout으로 JSON-RPC | 앱과 에이전트가 세션 내내 양방향으로 주고받습니다. 권한 요청이 올 때마다 앱이 답합니다 | 사내 앱 안에 Kiro 에이전트를 넣을 때 |
| **Kiro Crew** | Crew를 설치해 상주시키고 REST/WebSocket Gateway나 Python 클라이언트(`kirocrew-client`)로 호출 | Crew가 내부에서 ACP로 kiro-cli를 구동합니다. 메모리, 예약 작업, 서브에이전트, Slack 같은 채널 연결을 제공합니다 | 한 사람이 쓰는 상주형 개인 에이전트, 오래 걸리는 작업 맡기기 |

- **헤드리스 모드**는 `KIRO_API_KEY`로 인증하고, `--output-format stream-json`을 주면 진행 상황을 JSON Lines로 받을 수 있습니다. ([Headless mode](https://kiro.dev/docs/cli/headless/))
- **Kiro Crew**는 오픈소스(Apache 2.0)로, 사용자의 장비(로컬 또는 원격)에서 돌아가는 개인 에이전트입니다. ([Crew](https://kiro.dev/docs/crew/), [SDK / API reference](https://kiro.dev/docs/crew/apps/sdk/))

### 사내 앱에는 왜 ACP인가

직원이 사내 앱 화면에서 Kiro와 대화하며 일하는 경우를 생각하면 세 가지가 필요합니다.

1. **대화가 이어져야 합니다.** 직원은 답을 보고 다음 질문을 합니다. ACP는 `session/new`로 만든 세션 하나에 `session/prompt`를 계속 보낼 수 있습니다. 헤드리스는 한 번 실행에 지시 하나를 처리하고 끝나는 구조라, 이어서 하려면 매번 프로세스를 새로 띄워야 합니다.
2. **도구 실행을 그때그때 판단해야 합니다.** 에이전트가 파일을 만들거나 명령을 실행하려 하면 ACP는 `session/request_permission`으로 앱에 묻습니다. 앱은 직원에게 확인받거나 사내 정책에 따라 허용 또는 거부할 수 있습니다. 헤드리스는 실행 중에 물어볼 사람이 없다는 전제라서 `--trust-all-tools`나 `--trust-tools`로 미리 정해 둬야 합니다.
3. **앱이 세션을 직접 제어해야 합니다.** 작업 폴더(`cwd`)와 사내 시스템용 MCP 서버(`mcpServers`)를 세션마다 지정하고, 진행 상황(`session/update`)을 받아 앱 화면에 그대로 그릴 수 있습니다.

Kiro Crew 대신 ACP를 직접 쓰는 이유도 있습니다.
- Crew는 대시보드, 메모리, 예약 작업까지 갖춘 하나의 에이전트 제품이고, 한 사람이 자기 장비에서 쓰는 개인 에이전트로 설계됐습니다. 직원마다 자기 인증으로 쓰는 사내 앱에 붙이면, 사내 앱과 kiro-cli 사이에 Crew를 설치하고 운영하는 계층이 하나 더 생깁니다.
- Crew도 내부에서는 ACP로 kiro-cli를 구동합니다. 사내 앱이 ACP로 kiro-cli와 직접 연결하면 중간 계층 없이 같은 에이전트를 쓸 수 있습니다.
- Crew Gateway의 공식 클라이언트 패키지는 Python용만 있습니다. ACP는 프로세스를 띄워 JSON을 한 줄씩 주고받으면 되므로 Java, C#, Node.js 등 사내 앱 언어를 가리지 않습니다.

> **정리:** 정해진 작업을 한 번에 돌리면 헤드리스, 사내 앱 안에서 직원과 주고받으며 쓰면 ACP, 개인 에이전트를 상주시켜 일을 맡기려면 Kiro Crew입니다.
> 자동화라도 한 세션 안에서 여러 단계를 주고받거나 도구 실행을 하나씩 판단해야 하면 ACP가 맞습니다([4장의 2-A](#4-3-인증-방식-2-a-직원-본인의-api-키)).

---

## 1. ACP 한 장 요약

사내 앱이 `kiro-cli acp` 프로세스를 띄우고, 그 프로세스의 **표준입력/표준출력으로 JSON을 한 줄씩** 주고받습니다(JSON-RPC 2.0). 네트워크 포트를 여는 방식이 아닙니다.

```
 ┌───────────┐  stdin/stdout (JSON 한 줄씩)  ┌──────────────┐        ┌──────────┐
 │  사내 앱   │ ◄───────────────────────────► │ kiro-cli acp │ ◄────► │ Kiro 서비스│
 └───────────┘                               └──────────────┘        └──────────┘
```

대화 한 번은 이 순서로 진행됩니다.

| 순서 | 보내는 쪽 | 메시지 | 의미 |
|---|---|---|---|
| 1 | 앱 → Kiro | `initialize` | 연결 시작, 서로의 기능 확인 |
| 2 | 앱 → Kiro | `session/new` | 대화 세션 생성 (작업 폴더 `cwd` 지정) |
| 3 | 앱 → Kiro | `session/prompt` | 질문 보내기 |
| 4 | Kiro → 앱 | `session/update` (여러 번) | 답변 조각, 도구 실행 상황을 실시간으로 전달 |
| 5 | Kiro → 앱 | `session/request_permission` | "파일을 만들어도 될까요?" 같은 권한 요청. 앱이 허용/거부로 답함 |
| 6 | Kiro → 앱 | 3번 요청에 대한 응답 | 답변 끝 (`stopReason: end_turn`) |

방법 2(회사 서버)도 원리는 같습니다. 앱이 `kiro-cli acp` 대신 `ssh 직원@서버`를 실행하고, 서버가 그 직원 계정으로 `kiro-cli acp`를 실행합니다. **앱 코드는 실행 명령 한 줄만 다릅니다.**

---

## 2. 공통 준비

### 2-1. Kiro 구독
- 기업에서는 보통 **IAM Identity Center 기반 기업 구독**을 씁니다. 관리자가 직원(또는 그룹)에게 Pro, Pro+, Power 플랜을 배정합니다.
- 이 문서의 모든 방법은 **직원마다 자기 구독과 자기 인증**을 씁니다. 그래서 사용량과 기록이 직원별로 남고, 관리자 정책(MCP, 모델, 웹 접근 제한 등)도 직원별로 적용됩니다.

> 키 하나나 계정 하나를 여러 직원이 같이 쓰는 구성은 권하지 않습니다. 모든 사용량과 기록이 한 사람 이름으로 남고, 구독 한 개를 여럿이 나눠 쓰는 형태가 됩니다.

### 2-2. 예제 파일

```
kiro-acp-integration-guide/
├── README.md                  ← 이 문서 (한국어)
├── README.en.md               ← 영어 버전
├── examples/
│   └── acp_client.py          ← ACP 예제 클라이언트 (Python 3.9+, 외부 라이브러리 없음)
└── server/
    ├── add_user.sh            ← 방법 2: 서버에 직원 등록
    └── kiro-acp-entry.sh      ← 방법 2: 직원이 SSH로 접속했을 때 실행되는 유일한 프로그램
```

`acp_client.py`는 사내 앱이 할 일을 터미널에서 그대로 보여주는 예제입니다. 이 파일이 잘 동작하면, 같은 흐름을 사내 앱 언어(Java, C#, Node.js 등)로 옮기면 됩니다.

---

## 3. 방법 1. 직원 PC에 설치된 kiro-cli 사용

직원 PC에서 사내 앱이 `kiro-cli acp`를 직접 띄웁니다.

### 1단계: kiro-cli 설치
macOS, Linux:
```bash
curl -fsSL https://cli.kiro.dev/install | bash
```
Windows는 [공식 설치 문서](https://kiro.dev/docs/cli/installation/)의 PowerShell 명령을 따르세요.

확인:
```bash
kiro-cli --version
```
```
kiro-cli 2.34.2
```

### 2단계: 로그인
```bash
kiro-cli login
```
브라우저가 열리면 회사 계정으로 로그인합니다. 확인:
```bash
kiro-cli whoami
```
```
Logged in with IAM Identity Center (https://<회사>.awsapps.com/start)
Email: <직원 이메일>
```

### 3단계: ACP 연결 확인 (한 줄 테스트)
```bash
echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  | (cat; sleep 5) | kiro-cli acp
```
아래처럼 `"result"`로 시작하는 JSON 한 줄이 나오면 정상입니다.
```
{"jsonrpc":"2.0","result":{"protocolVersion":1,"agentCapabilities":{"loadSession":true, ...
```

### 4단계: 예제 클라이언트로 대화
작업할 폴더로 이동해서 실행합니다. 에이전트는 이 폴더를 작업 폴더로 씁니다.
```bash
cd ~/my-workspace
python3 /path/to/examples/acp_client.py
```
```
Connected: Kiro CLI Agent 2.34.2
Session created: 42a99e6e-...

Type a question. Press Enter on an empty line to quit.

You> hello.txt 파일에 hi 라고 써줘
Kiro>
  [Tool call] Creating hello.txt

[Permission request] Creating hello.txt
Allow? (y/N): y
  -> Allowed: Creating hello.txt
hello.txt 파일을 만들었습니다.
```
(답변 문구는 질문과 모델에 따라 달라집니다. 예제 클라이언트와 서버 스크립트의 안내 문구는 APJ 공유를 위해 영어로 되어 있습니다.)

옵션:
| 옵션 | 의미 |
|---|---|
| `--prompt "질문"` | 질문 하나만 보내고 종료 |
| `--approve ask` (기본) / `all` / `none` | 권한 요청을 매번 묻기 / 모두 허용 / 모두 거부 |
| `--cmd "kiro-cli acp --agent-engine=v3"` | V3 엔진 사용 ([6장](#6-자주-겪는-문제) 참고) |

여기까지 되면 방법 1은 끝입니다. 사내 앱에 붙이는 방법은 [5장](#5-사내-앱에-붙이기)에 있습니다.

### 방법 1에서 알아둘 점
- 에이전트는 **그 직원 PC에서 직원 권한으로** 파일을 만들고 명령을 실행합니다. 사내 앱이 작업 폴더(`cwd`)를 정해 주고, 권한 요청에 신중하게 답하게 만드세요.
- 사용량은 PC에 로그인한 직원 계정으로 잡힙니다.

---

## 4. 방법 2. 회사 서버에 설치된 kiro-cli 사용

회사 서버 한 대에 kiro-cli를 두고, 여러 직원이 각자 자기 인증으로 씁니다.

```
 직원 PC / 사내 앱                        회사 서버
 ┌───────────┐   ssh alice@서버          ┌──────────────────────────────────┐
 │ 사내 앱    │ ───────────────────────► │ 리눅스 계정 alice                 │
 │ (alice)   │   (JSON 한 줄씩 오감)       │  └ kiro-acp-entry → kiro-cli acp │
 └───────────┘                          │     인증: alice의 API 키 또는 SSO │
 ┌───────────┐   ssh bob@서버            │ 리눅스 계정 bob                   │
 │ 사내 앱    │ ───────────────────────► │  └ kiro-acp-entry → kiro-cli acp │
 │ (bob)     │                          │     인증: bob의 API 키 또는 SSO   │
 └───────────┘                          └──────────────────────────────────┘
```

핵심 원칙은 세 가지입니다.
1. **직원마다 리눅스 계정을 따로 만듭니다.** 에이전트는 그 계정 권한으로 명령을 실행합니다. 계정을 같이 쓰면 다른 직원의 파일을 읽을 수 있습니다(직접 확인함). 계정을 나누면 `Permission denied`로 막힙니다.
2. **SSH로 접속하면 셸이 아니라 `kiro-acp-entry`만 실행되게 합니다.** 직원은 서버에 셸로 들어갈 수 없고, 정해진 명령만 쓸 수 있습니다.
3. **인증은 직원 본인 것만 씁니다.** API 키(2-A)나 회사 SSO 로그인(2-B) 중 하나를 고릅니다.

### 4-1. 서버 준비 (관리자, 1회)

#### 1단계: 서버 사양 정하기
측정해 보니 `kiro-cli acp` 세션 1개가 메모리를 약 350MB(V2) ~ 435MB(V3) 씁니다. CPU보다 **메모리가 한계**입니다.

| 측정 (2 vCPU, 메모리 2GB 서버) | V2 | V3 |
|---|---|---|
| 세션 1개 메모리 | 약 350MB | 약 435MB |
| 동시 4세션 | 모두 성공, 서버 메모리 1.35GB 사용 | 모두 성공, 1.5GB 사용 |
| 세션 준비 시간 (1개 → 4개 동시) | 1.9초 → 4.0초 | 2.7초 → 8.0초 |

**동시 사용자 1명당 메모리 0.5GB**로 잡으면 여유가 있습니다. 예를 들어 동시 20명이면 메모리 16GB급 서버입니다. 짧은 질문 기준이고, 무거운 작업이나 5명 이상 동시 사용은 측정하지 않았습니다.

#### 2단계: 네트워크
- 직원 PC(또는 사내 앱 서버)에서 이 서버로 **SSH 접속**이 되어야 합니다.
- 서버에서 **바깥(HTTPS)으로** Kiro 서비스와 회사 SSO에 접속할 수 있어야 합니다.
- AWS EC2라면 22번 포트를 열지 않고 **SSM Session Manager를 통한 SSH**로도 접속할 수 있습니다. 이 문서의 테스트는 이 방식(인바운드 규칙 0개)으로 했습니다.

#### 3단계: 접속 전용 스크립트 설치
이 저장소의 `server/` 폴더를 서버에 복사합니다. 예: `scp -r server/ <관리자>@<서버>:~/`. 그다음 서버에서 실행합니다.
```bash
cd ~/server
sudo install -m 755 -o root -g root kiro-acp-entry.sh /usr/local/bin/kiro-acp-entry
```
`kiro-acp-entry`는 직원이 SSH로 접속하면 실행되는 **유일한 프로그램**입니다. 직원이 쓸 수 있는 명령은 다음과 같습니다.

| 직원이 실행하는 명령 | 동작 |
|---|---|
| `ssh 직원@서버` | `kiro-cli acp` 실행 (사내 앱이 쓰는 기본 동작) |
| `ssh 직원@서버 acp-v3` | V3 엔진으로 `kiro-cli acp` 실행 |
| `ssh 직원@서버 set-api-key < 키파일` | 내 API 키 등록 (2-A) |
| `ssh 직원@서버 remove-api-key` | 내 API 키 삭제 |
| `ssh -t 직원@서버 login` | 회사 SSO 로그인 (2-B) |
| `ssh 직원@서버 logout` | SSO 로그아웃 |
| `ssh 직원@서버 whoami` | 현재 인증 상태 확인 |
| 그 밖의 모든 명령 | `Command not allowed: ...` 로 거부 |

인증 방식은 자동으로 정해집니다. 직원 계정에 API 키가 등록돼 있으면 API 키를, 없으면 SSO 로그인 정보를 씁니다.

#### 4단계: SSO를 쓸 경우 회사 정보 설정 (2-B만)
```bash
sudo tee /etc/kiro-acp.conf <<'EOF'
KIRO_IDC_START_URL=https://<회사>.awsapps.com/start
KIRO_IDC_REGION=<IAM Identity Center 리전, 예: us-east-1>
EOF
sudo chmod 644 /etc/kiro-acp.conf
```
값을 모르면 이미 로그인한 직원 PC에서 `kiro-cli whoami`를 실행하세요. Start URL이 표시됩니다. 리전은 Kiro 관리자에게 확인합니다.

### 4-2. 직원 등록 (관리자, 직원마다)

#### 1단계: 직원이 SSH 키를 만들어 공개키를 전달
직원 PC에서:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/kiro-server -C "alice@company"
cat ~/.ssh/kiro-server.pub      # 이 한 줄을 관리자에게 전달 (공개키라 전달해도 안전)
```

#### 2단계: 관리자가 서버에 직원 등록
서버의 `~/server` 폴더에서 실행합니다.
```bash
chmod +x add_user.sh
sudo ./add_user.sh alice "ssh-ed25519 AAAAC3Nza... alice@company"
```
마지막에 이렇게 나오면 성공입니다(위쪽에는 kiro-cli 설치 메시지가 나옵니다).
```
kiro-cli 2.34.2
Done: registered alice. Next, set up authentication (guide 2-A or 2-B).
```
이 스크립트는 다음 일을 합니다.
- 직원 전용 리눅스 계정을 만듭니다. 홈 폴더 권한은 700이라 다른 직원이 볼 수 없습니다.
- 그 계정에 kiro-cli를 설치합니다.
- SSH로 접속하면 `kiro-acp-entry`만 실행되게 설정합니다(`restrict,pty,command=...`). 셸, 포트 포워딩은 막히고 로그인 화면용 터미널만 허용됩니다.

#### 3단계: 직원 PC에 접속 설정 (선택, 편의용)
`~/.ssh/config`에 추가하면 이후 `ssh kiro-server`로 짧게 접속할 수 있습니다.
```
Host kiro-server
    HostName <서버 주소>
    User alice
    IdentityFile ~/.ssh/kiro-server
    IdentitiesOnly yes
```
이제 인증을 설정합니다. 2-A와 2-B 중 하나를 고르세요.

### 4-3. 인증 방식 2-A: 직원 본인의 API 키

#### 1단계: 관리자가 API 키 발급 허용
기업 구독은 **기본적으로 API 키 발급이 꺼져 있습니다**([관련 문서](https://kiro.dev/docs/enterprise/governance/)). Kiro 관리자가 먼저 허용해야 합니다.

#### 2단계: 직원이 API 키 발급
1. [app.kiro.dev](https://app.kiro.dev)에 회사 계정으로 로그인합니다.
2. **Settings → API keys**로 이동합니다.
3. 키 이름을 입력하고(예: `kiro-server`) 생성합니다.
4. 키는 **이때 한 번만** 보입니다. `ksk_`로 시작합니다.

> 키는 비밀번호와 같습니다. 메신저, 메일, 문서, 채팅에 붙여넣지 마세요. 실수로 노출됐다면 바로 삭제하고 새로 발급하세요.

#### 3단계: 직원 PC에 키를 잠시 저장
```bash
(umask 077; cat > ~/.kiro-key)
```
실행하면 입력 대기 상태가 됩니다. 키를 붙여넣고 Enter, Ctrl+D를 누릅니다. 화면 기록이나 셸 기록에 남지 않습니다.

#### 4단계: 서버에 키 등록
```bash
ssh kiro-server set-api-key < ~/.kiro-key
```
```
API key registered.
```
키는 서버의 직원 계정에만 권한 600으로 저장되고, 화면에 출력되지 않습니다. 등록이 끝나면 PC의 임시 파일은 지워도 됩니다(`rm ~/.kiro-key`).

#### 5단계: 확인
```bash
ssh kiro-server whoami
```
```
Authenticated with API key
Email: <직원 이메일>
```
본인 이메일이 나오면 사용량도 본인에게 잡힙니다. 이어서 [4-5. 연결 확인](#4-5-연결-확인-2-a-2-b-공통)으로 가세요.

### 4-4. 인증 방식 2-B: 직원 본인의 회사 SSO 로그인

서버에 오래 남는 키를 두지 않고, 회사 SSO 로그인을 그대로 씁니다. 관리자가 [4-1의 4단계](#4단계-sso를-쓸-경우-회사-정보-설정-2-b만)를 해 둬야 합니다.

#### 1단계: 로그인 시작
직원 PC에서(**`-t` 필수**):
```bash
ssh -t kiro-server login
```
Start URL과 Region이 미리 채워진 상태로 두 번 묻습니다. 둘 다 **Enter**만 누르면 됩니다.
```
✔ Enter Start URL · https://<회사>.awsapps.com/start
✔ Enter Region · us-east-1
Confirm the following code in the browser
Code: ABCD-EFGH
Open this URL: https://<회사>.awsapps.com/start/#/device?user_code=ABCD-EFGH
▰▱▱▱▱▱▱ Logging in...
```

#### 2단계: 브라우저에서 승인
1. 표시된 URL을 직원 PC 브라우저에서 엽니다. 코드는 몇 분 안에 만료되니 바로 진행하세요.
2. 회사 계정으로 로그인합니다.
3. "Authorization requested" 화면의 코드가 터미널 코드와 **같은지 확인**하고 **Confirm and continue**를 누릅니다.
4. 이어서 접근 허용(Allow) 화면이 나오면 허용합니다.

터미널에 다음이 나오면 완료입니다.
```
Device authorized
Logged in successfully
```

> 코드가 다르거나 본인이 시작한 로그인이 아니면 **Cancel**을 누르세요. 남이 보낸 승인 링크를 누르면 내 계정이 그 사람 서버에 로그인됩니다.

#### 3단계: 확인
```bash
ssh kiro-server whoami
```
```
Logged in with IAM Identity Center (https://<회사>.awsapps.com/start)
Email: <직원 이메일>
```
- 로그인 정보는 서버의 직원 계정에만 저장됩니다(`~/.local/share/kiro-cli/data.sqlite3`, 권한 600). 다른 직원 계정에서는 읽을 수 없습니다(직접 확인함).
- 그만 쓸 때는 `ssh kiro-server logout`. 로그아웃하면 바로 `kiro-cli acp`가 시작되지 않습니다(직접 확인함).
- SSO 세션이 만료되면 1단계부터 다시 로그인합니다. 만료 시간은 회사의 IAM Identity Center 설정에 따릅니다.

### 4-5. 연결 확인 (2-A, 2-B 공통)
직원 PC에서 예제 클라이언트로 서버의 kiro-cli와 대화합니다. 원격 서버라서 작업 폴더(`--cwd`)는 **서버 기준 경로**로 줍니다(직원 계정의 `~/work`).
```bash
python3 examples/acp_client.py --cmd "ssh kiro-server" --cwd /home/alice/work
```
```
Connected: Kiro CLI Agent 2.34.2
Session created: ...

You> hello.txt 파일에 hi 라고 써줘
Kiro>
  [Tool call] Creating hello.txt
...
```
V3 엔진은 `--cmd "ssh kiro-server acp-v3"`로 씁니다.

인증이 안 된 상태(키 미등록, 로그인 전, 로그아웃 후)라면 이렇게 나옵니다. 4-3 또는 4-4로 돌아가 인증을 설정하세요.
```
Error: Lost connection to kiro-cli.
error: You are not logged in, please log in with kiro-cli login
```

### 2-A와 2-B 고르기

| | 2-A. API 키 | 2-B. SSO 로그인 |
|---|---|---|
| 관리자 사전 작업 | API 키 발급 허용 (기본 꺼짐) | `/etc/kiro-acp.conf` 설정 |
| 직원 첫 설정 | 웹에서 키 발급 → `set-api-key` | `ssh -t ... login` → 브라우저 승인 |
| 서버에 남는 것 | 오래 유효한 키 | 회사 SSO 세션 정보 |
| 다시 인증 | 키가 유효한 동안 불필요 | SSO 세션이 만료되면 필요 |
| 회사 SSO 정책(MFA, 세션 시간) 적용 | 키 발급할 때만 | 로그인할 때마다 |
| 어울리는 경우 | 사람이 매번 승인하기 어려운 자동화 | 사람이 쓰는 사내 앱 |

---

## 5. 사내 앱에 붙이기

`examples/acp_client.py`의 흐름을 사내 앱 언어로 옮기면 됩니다. 방법 1과 방법 2의 차이는 **프로세스를 띄우는 명령**뿐입니다.

| 구성 | 사내 앱이 실행할 명령 | `session/new`의 `cwd` |
|---|---|---|
| 방법 1 | `kiro-cli acp` | 직원 PC의 작업 폴더 |
| 방법 2 | `ssh -i <직원 키> <직원>@<서버>` | 서버의 `/home/<직원>/work` |

구현할 때 꼭 지켜야 할 것:
1. **메시지를 한 줄씩 읽고, 종류로 구분하세요.**
   - `id`와 `method`가 둘 다 있으면 에이전트의 요청이므로 반드시 답해야 합니다.
   - `method`만 있으면 알림입니다.
   - `id`만 있으면 내가 보낸 요청에 대한 응답입니다.
2. **에이전트의 요청에는 반드시 답하세요.** 모르는 요청이라도 오류로 답해야 에이전트가 기다리며 멈추지 않습니다.
3. **권한 요청은 `optionId`가 아니라 `kind`로 고르세요.** `optionId`는 엔진마다 다릅니다. 예를 들어 허용은 V2에서 `allow_once`, V3에서 `accept`입니다. `kind`(`allow_once`, `reject_once` 등)는 같습니다.
4. **stderr도 계속 읽어서 비워 주세요.** 안 읽으면 버퍼가 차서 kiro-cli가 멈출 수 있습니다.
5. **답변은 받는 대로 화면에 표시하세요.** `session/update`의 `agent_message_chunk`가 답변 조각입니다.
6. **사내 시스템 연결은 `session/new`의 `mcpServers`로** MCP 서버를 넘기는 방식으로 확장할 수 있습니다. 이 문서에서는 다루지 않았습니다.

데스크톱 GUI 예제가 필요하면 AWS 공식 샘플 [aws-samples/sample-kiro-acp-ui](https://github.com/aws-samples/sample-kiro-acp-ui)도 참고하세요(Python, tkinter). 이 샘플도 실행 명령을 `ssh ...`로 바꾸면 방법 2에서 그대로 동작합니다. 다만 V3 엔진에서는 모델 목록이 비어 보입니다. V3는 모델 목록을 `configOptions`로 보내기 때문입니다.

---

## 6. 자주 겪는 문제

| 증상 | 원인 | 해결 |
|---|---|---|
| `error: You are not logged in, please log in with kiro-cli login` 후 바로 종료 | 그 계정에 로그인도 API 키도 없음 | 방법 1: `kiro-cli login`. 방법 2: `set-api-key` 또는 `ssh -t ... login` |
| 서버 로그인에서 `invalid value for field 'region'` | 터미널 없이 실행됨 | `ssh -t`로 실행. `-t`가 없으면 `kiro-acp-entry`가 안내 문구를 띄웁니다 |
| `the following arguments are not supported with --agent-engine=v3: --trust-all-tools` | V3는 이 옵션을 지원하지 않음 | V3에서는 권한 요청에 앱이 답하거나, V3 권한 정책 파일을 사용 |
| V3에서 모델 목록이 비어 있음 | V3는 모델 목록을 `session/new` 응답의 `configOptions`(id `model`)로 보냄 | `models`와 `configOptions` 둘 다 읽기 |
| `Command not allowed: ...` | 방법 2에서 정해진 명령 외에는 막혀 있음 | [4-1의 표](#3단계-접속-전용-스크립트-설치)에 있는 명령만 사용 |
| `Invalid key format (it must start with ksk_).` | 키가 아닌 값을 등록하려 함 | `ksk_`로 시작하는 키를 다시 확인 |
| SSH 접속 때 `post-quantum key exchange` 경고 | 서버 OpenSSH 버전 안내 | 동작에는 영향 없음. 서버 OpenSSH 업그레이드 검토 |
| 응답이 오다가 멈춤 | 앱이 에이전트 요청에 답하지 않았거나 stderr를 안 비움 | [5장](#5-사내-앱에-붙이기)의 1, 2, 4번 확인 |

---

## 7. 확인된 범위와 확인하지 못한 것

**직접 실행해서 확인한 것** (kiro-cli 2.34.2, V2 기본 엔진과 V3)
- 방법 1: 예제 클라이언트로 질문 답변, 권한 허용/거부(거부하면 파일이 생성되지 않음), 같은 세션의 이어지는 대화
- 방법 2-A: `add_user.sh`로 새 직원 등록 → `set-api-key` → `whoami`에 키 주인 이메일 표시 → 예제 클라이언트로 원격 파일 생성(V2, V3). 키가 없으면 시작 단계에서 종료, 잘못된 형식의 키는 등록 거부
- 방법 2-B: `add_user.sh`로 새 직원 등록 → `ssh -t ... login` → 브라우저 승인 → API 키 없이 예제 클라이언트로 원격 파일 생성(V2, V3) → `logout` 후 바로 차단. `-t` 없이 `login`하면 안내 문구와 함께 거부
- 직원 계정 분리: 다른 직원의 파일, 로그인 정보, 프로세스 환경변수를 읽지 못함. 계정을 같이 쓰면 읽힘
- 접속 제한: 정해진 명령 외 실행 거부(`cat /etc/passwd`, `bash -i`), 포트 포워딩 차단
- 동시 사용: 세션 4개 동시 실행(V2, V3 각각)

**확인하지 못한 것** (도입 전에 Kiro 팀 또는 관리자에게 확인 권장)
- 서로 다른 두 직원의 키나 로그인으로 사용량이 각자에게 분리되어 집계되는지 (테스트는 한 계정으로만 진행. 문서와 `whoami` 결과로는 그렇게 동작해야 함)
- IAM Identity Center에서 직원을 삭제하거나 구독을 해제했을 때, 서버에 남은 API 키나 SSO 로그인이 즉시 막히는지
- API 키 발급을 그룹 단위로만 허용할 수 있는지, 키 유효기간을 관리자가 강제할 수 있는지
- 직원별 사용량(초과 크레딧) 상한을 걸 수 있는지
- SSO 세션의 실제 만료와 자동 갱신 주기
- 동시 5세션 이상, 오래 걸리는 작업에서의 자원 사용량과 Kiro 서비스 요청 한도
- Windows 직원 PC에서 방법 1과 예제 클라이언트 동작

---

## 참고 문서
- [ACP integrations](https://kiro.dev/docs/acp/) · [Kiro CLI ACP](https://kiro.dev/docs/cli/acp/)
- [Headless mode (API 키)](https://kiro.dev/docs/cli/headless/)
- [V3 ACP client migration](https://kiro.dev/docs/cli/v3/acp-migration/)
- [Enterprise governance (API 키 허용)](https://kiro.dev/docs/enterprise/governance/)
- [Kiro CLI 설치](https://kiro.dev/docs/cli/installation/)
- [Kiro Crew](https://kiro.dev/docs/crew/) · [Crew SDK / API reference](https://kiro.dev/docs/crew/apps/sdk/)
- [aws-samples/sample-kiro-acp-ui](https://github.com/aws-samples/sample-kiro-acp-ui)

---

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
