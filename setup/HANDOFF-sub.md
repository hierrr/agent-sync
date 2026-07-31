# sub 역할 기기 셋업 지시서 — Claude Code 에이전트용

이 문서는 **이 기기에서 실행되는 에이전트**가 수행한다. 사용자 지시에 **main의
장치 ID**가 포함되어 있어야 한다 (없으면 작업 전에 사용자에게 요청할 것).
시스템 개요는 README.md 참고.

## 수행할 작업

1. `~/agent-sync` 확인 — 없으면:
   `git clone https://github.com/hierrr/agent-sync.git ~/agent-sync`
2. 실행: `chmod +x ~/agent-sync/setup/setup-machine.sh && ~/agent-sync/setup/setup-machine.sh --role sub --main-id <MAIN_ID>`
3. 검증 (전부 확인):
   - `ls -la ~/.claude/` 에서 agents, skills, commands, CLAUDE.md 가 `~/agent-sync` 심링크인지
   - `jq '.hooks.SessionStart, .autoDreamEnabled' ~/.claude/settings.json` 이 훅과 true를 출력하는지
   - `launchctl list | grep agentsync` 에 settings-watch 가 있는지 (merge 는 main 전용 — 없어야 정상)
   - 훅 파이프 테스트: 아무 git 저장소에서 `echo '{}' | ~/agent-sync/claude/hooks/ensure-automemory.sh`
     실행 후 그 저장소의 `.claude/settings.local.json` 에 autoMemoryDirectory 가 생겼는지
   - `syncthing cli config devices list` 에 main ID가 있는지
4. **연결 확인** (main 등록 창이 열려 있으면 1~2분 내 자동 수락됨):
   `syncthing cli show connections` 에서 main이 connected 인지. 2분 정도 기다렸다
   재확인해도 된다.
5. **사용자에게 결과 안내**:
   - **연결됨**: "셋업 완료, main과 동기화가 시작됐습니다"라고 보고. 몇 분 뒤
     `~/agent-sync/memory/` 에 내용이 내려오는지도 확인해 함께 보고.
   - **연결 안 됨** (등록 창이 닫힌 경우 — 정상적인 상황): 다음 형식으로 안내한다
     (장치 ID는 스크립트 출력값):

     > 이 기기 구성은 끝났고 main의 수락만 남았습니다. 이 기기의 장치 ID는
     > `YYYYYYY-...` 입니다. main 기기의 에이전트에게
     > **"장치 `YYYYYYY-...` 수락해줘"** 라고 전달해 주세요.
     > 수락되면 자동으로 연결됩니다 (이 기기에서 더 할 일 없음).

6. **충돌 통합** (연결 후, 초기 동기화가 끝난 뒤):
   `find ~/agent-sync/claude -name '*sync-conflict*'` 로 충돌 사본을 찾는다.
   - 없으면 넘어간다. (이름이 다른 파일은 Syncthing이 알아서 합집합으로 만들므로
     충돌이 아니다.)
   - 있으면 이 기기 에이전트가 각 쌍을 비교해 직접 통합한다: 표현·형식 수준의
     차이면 더 나은 쪽 기준으로 병합해 본파일에 쓰고 충돌 사본을 지운 뒤 무엇을
     어떻게 합쳤는지 보고한다. 역할·동작이 실제로 다르면 차이를 사용자에게
     요약해 보여주고 선택을 받아 반영한다.
   - 여기서 놓친 충돌은 main의 새벽 유지보수가 AI 병합으로 정리하지만(원본은
     main의 `setup/logs/conflict-archive/`에 보존), 셋업 시점 정리가 우선이다.

## 주의

- 셋업 중 macOS가 **"Syncthing이 로컬 네트워크 기기를 찾도록 허용" 팝업**을 띄우면
  사용자에게 허용을 요청할 것 — 허용 없이는 내부망 직결이 차단되어 동기화가 안 된다
  (동기화는 내부망 전용이라 릴레이 우회도 없음). 팝업을 놓쳤으면 시스템 설정 >
  개인정보 보호 및 보안 > 로컬 네트워크에서 Syncthing을 켠다.
- `setup/` 안의 스크립트를 수정하지 않는다 (전 기기가 동일 파일 공유).
- `~/.claude/settings.json.pre-agent-sync.bak`, `*.premerge.bak` 은 롤백용 백업 — 지우지 말 것.
- 문제가 생기면 임의로 우회하지 말고 증상 그대로 사용자에게 보고한다.
