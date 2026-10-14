# main 역할 기기 셋업 지시서 — Claude Code 에이전트용

이 문서는 **이 기기에서 실행되는 에이전트**가 수행한다. 스크립트가 작업을 하고,
에이전트는 실행·검증·사용자 안내를 담당한다. 시스템 개요는 README.md 참고.

main은 클러스터의 허브 1대다 (신규 기기 수락 + 새벽 유지보수). 데이터 원본이
아니며 모든 기기가 완전 사본을 가진다.

## A. 최초 셋업

1. `~/agent-sync` 확인 — 없으면:
   `git clone https://github.com/hierrr/agent-sync.git ~/agent-sync`
2. 실행: `chmod +x ~/agent-sync/setup/setup-machine.sh && ~/agent-sync/setup/setup-machine.sh --role main`
3. 검증 (전부 확인):
   - `ls -la ~/.claude/` 에서 agents, skills, commands, CLAUDE.md 가 `~/agent-sync` 심링크인지
   - `jq '.hooks.SessionStart, .autoDreamEnabled' ~/.claude/settings.json` 이 훅과 true를 출력하는지
   - `launchctl list | grep agentsync` 에 settings-watch 와 merge 두 항목이 있는지
   - 훅 파이프 테스트: 아무 git 저장소에서 `echo '{}' | ~/agent-sync/claude/hooks/ensure-automemory.sh`
     실행 후 그 저장소의 `.claude/settings.local.json` 에 autoMemoryDirectory 가 생겼는지
   - `syncthing cli config folders list` 에 agent-sync 가 있는지
   - `cat ~/agent-sync/setup/logs/enroll.pid` 존재 (60분 등록 창 열림)
   - `[ -f ~/agent-sync/memory/_global/GLOBAL.md ] && echo OK` 가 OK를 출력하는지
     (전역 메모리 뼈대가 생성됐는지)
   - `git -C ~/agent-sync status --short` 출력이 비어 있는지 (셋업이 git 추적
     파일을 더럽히지 않음 — 기존 CLAUDE.md가 있던 기기 포함)
   - 셋업 전부터 쓰던 저장소가 있다면: 그 저장소에서 세션을 열거나 훅 파이프 테스트 후,
     `~/agent-sync/memory/<저장소명>/` 에 기존 `~/.claude/projects/<키>/memory/` 파일들이
     복사돼 있는지 (원본은 그대로 유지됨. 이관은 기기·저장소별 첫 1회만 —
     `~/.claude/agent-sync-migrated/` 에 표식이 이미 있으면 재복사하지 않는 게 정상)
   - `env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/python3 ~/agent-sync/setup/merge-sync-conflicts.py --check-claude`
     가 claude 경로를 출력하는지 (launchd의 빈 PATH 환경에서 새벽 작업이 claude를 찾는지)
   - (codex 설치 기기만 해당) Codex 메모리 쓰기: 아무 git 저장소에서
     `codex sandbox -c 'sandbox_mode="workspace-write"' -- /bin/sh -c 'echo x > "$HOME/agent-sync/memory/.sbx-test" && echo CODEX_MEM_WRITE_OK; rm -f "$HOME/agent-sync/memory/.sbx-test"'`
     가 `CODEX_MEM_WRITE_OK`를 출력하는지 (모델 호출 없음). codex 미설치 기기는 건너뜀
   - (codex 설치 기기만 해당) `codex features list | grep '^memories '` 가 `false`인지 —
     agent-sync와 별개의 이중 메모리 방지. true면 바꾸지 말고 사용자에게 보고만
   - 운영 전제 점검 (읽기 전용 — 결과를 사용자에게 보고, 변경은 사용자 결정):
     - `pmset -g custom | grep -E "^ *sleep"` — 04:30에 깨어 있으려면 sleep 0(또는
       pmset repeat 예약)이어야 함
     - `fdesetup status` 와 `sysadminctl -autologin status 2>&1 | tail -1` — 무인 재부팅
       복구(자동 로그인)는 FileVault가 켜져 있으면 불가(macOS 제약). FileVault 유지 시
       재부팅 뒤 수동 로그인 1회 필요
     - `stat -f %Su /dev/console` — 현재 로그인된 콘솔 사용자. 새벽 작업(launchd gui
       도메인)과 claude 인증(로그인 키체인)은 로그인 상태가 전제
4. **사용자에게 다음 형식으로 안내한다** (장치 ID는 스크립트 출력값):

   > 셋업과 검증이 끝났습니다. 이 기기(main)의 장치 ID는 `XXXXXXX-...` 입니다.
   > 각 서브 기기의 에이전트에게 이렇게 지시하세요:
   > **"~/agent-sync/setup/HANDOFF-sub.md 읽고 수행해. main ID는 `XXXXXXX-...`"**
   > (저장소가 없는 기기라면 clone부터 하라고 문서에 안내되어 있습니다.)
   > 지금부터 60분간은 서브 셋업이 자동 수락되며, 그 이후에 추가되는 기기는
   > 해당 기기 에이전트가 알려주는 장치 ID를 저에게 전달해 주시면 됩니다.

## B. 나중에 서브 기기 수락 (사용자가 "ID 수락해줘"라고 요청할 때)

1. 실행: `~/agent-sync/setup/setup-machine.sh --accept <전달받은 ID>`
2. 1~2분 내 확인: `syncthing cli show connections` 에서 해당 기기가 connected 인지
3. 연결 성공/실패를 사용자에게 보고. 실패 시 같은 LAN 여부, 상대 기기 Syncthing
   실행 여부를 확인하고 증상 그대로 보고한다.

## 주의

- 셋업 중 macOS가 **"Syncthing이 로컬 네트워크 기기를 찾도록 허용" 팝업**을 띄우면
  사용자에게 허용을 요청할 것 — 허용 없이는 내부망 직결이 차단되어 동기화가 안 된다
  (동기화는 내부망 전용이라 릴레이 우회도 없음). 팝업을 놓쳤으면 시스템 설정 >
  개인정보 보호 및 보안 > 로컬 네트워크에서 Syncthing을 켠다.
- `setup/` 안의 스크립트를 수정하지 않는다 (전 기기가 동일 파일 공유).
- `~/.claude/settings.json.pre-agent-sync.bak`, `*.premerge.bak` 은 롤백용 백업 — 지우지 말 것.
- 기존 `~/.claude/projects/*/memory/` 는 원본 보존용으로 건드리지 않는다.
- 문제가 생기면 임의로 우회하지 말고 증상 그대로 사용자에게 보고한다.
