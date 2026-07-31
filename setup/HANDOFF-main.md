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
