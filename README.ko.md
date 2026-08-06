# agent-sync

[English](README.md) · **한국어**

여러 대의 컴퓨터에서 LLM CLI 에이전트(Claude Code, Codex)를 쓰면 기기마다
메모리·설정이 따로 쌓입니다. agent-sync는 이를 `~/agent-sync` 폴더 하나로 모아
전 기기에 실시간 동기화합니다 — **어떤 기기에서 작업하든 에이전트가 같은 기억과
같은 설정으로 동작합니다.**

- **P2P, 내부망 전용** — 동기화는 [Syncthing](https://syncthing.net)이 담당합니다.
  클라우드 서버 없이 기기끼리 직접 암호화 통신하고, 외부 릴레이·글로벌 검색을 꺼서
  파일이 인터넷으로 나가지 않습니다. 모든 기기가 완전한 사본을 가지므로 특정
  기기가 꺼져 있어도 됩니다.
- **에이전트가 설치** — 셋업은 각 기기의 에이전트에게 지시서(`setup/HANDOFF-*.md`)를
  맡기는 방식입니다. 사람은 장치 ID를 전달하고 macOS 권한 팝업을 허용하는 것이
  전부입니다.
- **이 저장소는 뼈대만** — 스크립트와 공용 구성만 들어 있습니다. 메모리 내용과
  개인 커스텀(에이전트·스킬 정의)은 git에 포함되지 않으므로, clone해서 시작하면
  빈 상태에서 본인 기기들만의 독립 클러스터가 만들어집니다.

## 무엇이 동기화되나

| 항목 | 방식 |
|---|---|
| 프로젝트별 자동 메모리 | 세션 시작 훅이 각 git 저장소의 `.claude/settings.local.json`에 `autoMemoryDirectory`를 자동 생성 → 모든 기기가 같은 메모리 폴더 사용 |
| 전역 메모리 | `~/.claude/CLAUDE.md`(심링크)가 `memory/_global/GLOBAL.md`를 임포트 → 모든 프로젝트·모든 기기의 세션에 로드 |
| Claude Code 공유 설정 | `claude/settings.base.json`을 각 기기의 `~/.claude/settings.json`에 자동 병합 (기기 고유 항목은 보존) |
| 개인 에이전트·스킬·커맨드 | `~/.claude/agents` 등 심링크 — 기기 간 동기화, git 배포에는 미포함 |
| Codex 전역 지침 | `~/.codex/AGENTS.md` 심링크 — 같은 메모리 폴더를 읽고 쓰도록 안내 |

참고: `autoMemoryDirectory`는 커밋된 `.claude/settings.json`에서는 보안상 무시되기
때문에, 훅이 기기마다 `settings.local.json`을 자동 생성하는 방식이 유일한 방법입니다.
프로젝트마다·기기마다 수동 설정할 일은 없습니다.

## 빠른 시작

### 첫 번째 기기 (main 역할)

그 기기의 에이전트에게:

> **"`https://github.com/hierrr/agent-sync.git` 을 `~/agent-sync`로 clone하고
> `setup/HANDOFF-main.md` 읽고 수행해"**

에이전트가 셋업·검증을 마치면 이 기기의 **장치 ID**를 보고하고, **60분짜리 신규
기기 등록 창**을 엽니다(이 시간 안에 셋업하는 기기는 자동 수락, 이후 자동 종료).

main은 클러스터의 허브 1대입니다(신규 기기 소개 + 새벽 유지보수 담당). 데이터
원본이라는 뜻은 아닙니다 — 모든 기기가 완전 사본을 가집니다.

### 기기 추가 (sub 역할)

추가할 각 기기의 에이전트에게 — `<MAIN_ID>` 자리에 위에서 보고받은 장치 ID:

> **"`~/agent-sync/setup/HANDOFF-sub.md` 읽고 수행해. main ID는 `<MAIN_ID>`"**

등록 창이 열려 있으면 이걸로 끝 — 자동 수락되어 약 1분 안에 동기화가 시작됩니다.
등록 창이 닫힌 뒤라면 sub 에이전트가 알려주는 장치 ID를 main 에이전트에게 전달해
수락시키면 됩니다 (*"장치 `YYY` 수락해줘"*).

에이전트 없이 직접 실행하려면:

```bash
git clone https://github.com/hierrr/agent-sync.git ~/agent-sync
chmod +x ~/agent-sync/setup/setup-machine.sh
~/agent-sync/setup/setup-machine.sh --role main                  # 첫 기기
~/agent-sync/setup/setup-machine.sh --role sub --main-id <ID>    # 추가 기기
~/agent-sync/setup/setup-machine.sh --accept <ID>                # main에서 나중 수락
~/agent-sync/setup/setup-machine.sh --enroll [분]                # 등록 창 재개방
```

## 사람이 하는 일 (전체 요약)

| 시점 | 할 일 |
|---|---|
| 첫 기기(main) | 에이전트에게 지시 → 보고받은 **main ID를 메모** |
| 기기 추가(main 셋업 후 60분 이내) | 각 기기 에이전트에게 지시 (main ID 포함) |
| 기기 추가(나중에) | 위와 동일 + **sub ID를 main 에이전트에게 전달** |
| 각 기기 셋업 중(공통) | macOS **"Syncthing 로컬 네트워크 허용" 팝업 → 허용** 클릭 (기기당 1회) |
| 그 외 | 없음 — 페어링·수락·동기화 전부 자동 |

## 동작 방식

- **자동 메모리 연결**: Claude Code의 SessionStart 훅(`claude/hooks/ensure-automemory.sh`)이
  git 저장소를 열 때마다 그 저장소의 auto-memory 경로를 `~/agent-sync/memory/<저장소명>`
  으로 지정합니다. 저장소의 `.claude`는 git에 커밋되지 않게 로컬 exclude 처리됩니다.
- **설정 병합**: `setup/apply-settings.py`가 `claude/settings.base.json`(공유)을 각 기기의
  `~/.claude/settings.json`에 병합합니다. permissions 등 기기 로컬 항목은 보존되고,
  base가 바뀌면 감시 launchd가 자동 재적용합니다.
- **새벽 유지보수** (main 전용, 4:30): 먼저 두 기기가 같은 파일을 동시에 수정해 생긴
  Syncthing 충돌을 병합하고 — 메모리 인덱스는 합집합, 에이전트·스킬 정의는
  headless LLM 호출로 병합(원본은 `setup/logs/conflict-archive/`에 보존) — 이어서
  **dream 패스**가 각 메모리 폴더를 큐레이션합니다: 중복·모순 사실 병합, 충돌
  리뷰 사본 통합, 상대 날짜의 절대화, 프로젝트 무관 사실의 `_global/GLOBAL.md`
  승격, `MEMORY.md` 인덱스 재구축. 실행 전 폴더 전체(GLOBAL.md 포함)를
  `setup/logs/dream-archive/`에 보관했다가 사후 점검 실패 시 원자적으로 복원하며,
  변경 없는 폴더는 건너뜁니다. Claude Code 내장 auto-dream의 잠금 파일 잔존
  버그도 청소합니다.
- **Syncthing은 메뉴바 앱으로 구동**: macOS 15+에서 로컬 네트워크 권한을 받을 수 있는
  방식이 앱뿐이기 때문입니다 — 백그라운드 서비스(brew services)는 권한을 받지 못해
  내부망 통신이 조용히 차단됩니다. `syncthing` 명령은 앱 내장 CLI를 가리키는 심링크로
  제공되며, 구버전 brew 패키지가 있으면 셋업이 자동 정리합니다.
- **보안**: 장치 인증은 Syncthing 인증서 지문(장치 ID)으로 이뤄지며 이 저장소에는
  어떤 기기 정보도 들어 있지 않습니다. 등록 창이 열린 60분 동안은 main의 장치 ID를
  아는 기기의 접속이 자동 수락되므로, 장치 ID는 신뢰하는 상대에게만 전달하세요.

## 요구 사항

- macOS (Windows는 아래 베타 안내 참고)
- Claude Code CLI
- Homebrew (Syncthing 자동 설치용 — 수동 설치로 대체 가능)

## 운영

- **설정 변경**: `claude/settings.base.json` 수정 → 저장하면 Syncthing이 전파하고,
  각 기기의 감시 launchd가 자동 병합합니다.
- **역할 이전**: 새 기기에서 `--role main` 실행 + 기존 main의
  `com.palusomni.agentsync.merge` launchd 해제.
- **git 이용 수칙**: 이 저장소는 배포·개선 공유용입니다. 셋업 이후 일상 동기화에
  git은 관여하지 않으며, 스크립트를 개선했을 때만 관리 기기 한 대에서 커밋하세요.

## 문제 해결

**다른 기기에 파일이 안 넘어온다** — 페어링 상태를 확인하세요. 아무 기기에서:

```bash
syncthing cli config devices list    # 자기 ID 외에 상대 기기들이 보여야 함
syncthing cli config folders list    # agent-sync 폴더가 보여야 함
syncthing cli show connections       # connected: true 항목이 있어야 함
```

- 기기 목록은 맞는데 `connected: false`가 계속되면: 시스템 설정 > 개인정보 보호 및
  보안 > **로컬 네트워크**에 Syncthing이 허용돼 있는지, 두 기기가 같은 내부망에
  있는지 확인하세요 — 동기화가 내부망 전용이라 이 두 조건이 안 되면 연결이
  성립하지 않습니다.
- 기기 목록이 비어 있으면: sub에서 `--role sub --main-id <ID>`를 실행했는지 확인하고,
  main에서 그 기기를 수락하세요 (`--accept <sub의 장치 ID>`). 필요하면
  http://127.0.0.1:8384 (Syncthing GUI)에서 수동 조작도 가능합니다.

**세션이 예전 메모리를 본다** — 메모리는 세션 시작 시 로드됩니다. 다른 기기에서
방금 저장된 메모리는 새 세션부터 반영됩니다.

**셋업을 되돌리고 싶다** — 셋업이 만든 백업으로 복구합니다:
`~/.claude/settings.json.pre-agent-sync.bak`(설정),
`~/.claude/*.premerge.bak`(심링크 전 원본).

## Windows 지원 (베타)

네이티브 스크립트는 아직 없습니다. Windows 기기는 **그 기기의 에이전트에게 설치를
맡기는 방식**을 권장합니다 — 셸·권한 등 환경 편차가 커서, 기기 상황을 직접 확인할
수 있는 에이전트가 판단하며 진행하는 편이 안전합니다.

에이전트에게: *"이 README와 `setup/` 소스를 읽고, 아래 대응표를 참고해 이 Windows
기기에 동등한 셋업을 구성하고 각 단계를 검증해줘"* 라고 지시하세요.

| macOS 구성 요소 | Windows 대응 |
|---|---|
| `setup-machine.sh` (bash) | PowerShell로 동등 로직 수행 |
| launchd (감시·새벽 작업) | 작업 스케줄러 (Task Scheduler) |
| Syncthing 메뉴바 앱 | winget/직접 설치 (SyncTrayzor 등) |
| `~/.claude/*` 심링크 | 개발자 모드 활성화 후 심링크 (또는 junction) |
| SessionStart 훅 (bash+python3) | Git Bash 설치 권장 (없으면 훅이 PowerShell로 실행됨 — 포팅 필요) |
| 경로 `~/agent-sync` | `%USERPROFILE%\agent-sync` (Claude Code의 `~/` 확장은 OS 무관 동작) |

베타인 만큼, 구성 후 HANDOFF 문서의 검증 항목이 모두 통과하는지 반드시 확인하세요.

## 폴더 구조

```
~/agent-sync/
├── memory/                    # 자동 메모리 (Syncthing 전용, git 미포함)
│   ├── _global/GLOBAL.md      #   전역 메모리 — 모든 세션에 로드
│   └── <저장소명>/            #   프로젝트별 메모리 — 훅이 자동 지정
├── claude/
│   ├── CLAUDE.md              # 전역 지침 (~/.claude/CLAUDE.md 심링크 대상)
│   ├── agents|skills|commands/  # 개인 커스텀 (Syncthing 전용, git 미포함)
│   ├── hooks/ensure-automemory.sh
│   └── settings.base.json     # 공유 설정 (SessionStart 훅, autoDreamEnabled 등)
├── codex/AGENTS.md            # Codex 전역 지침
└── setup/                     # 셋업 스크립트, launchd 정의, 에이전트용 지시서
```

## 라이선스

[MIT](LICENSE)
