# solo 역할 기기 셋업 지시서 — Claude Code 에이전트용

이 문서는 **이 기기에서 실행되는 에이전트**가 수행한다. 스크립트가 작업을 하고,
에이전트는 실행·검증·사용자 안내를 담당한다. 시스템 개요는 README.md 참고.

solo는 단일 기기 모드다: 한 기기 안에서 여러 에이전트(Claude Code, Codex)의
메모리·설정 통합과 새벽 메모리 유지보수만 설치하고, Syncthing과 기기 간 동기화
구성은 설치하지 않는다.

## 셋업

1. `~/agent-sync` 확인 — 없으면:
   `git clone https://github.com/hierrr/agent-sync.git ~/agent-sync`
2. 실행: `chmod +x ~/agent-sync/setup/setup-machine.sh && ~/agent-sync/setup/setup-machine.sh --role solo`
3. 검증 (전부 확인):
   - `ls -la ~/.claude/` 에서 agents, skills, commands, CLAUDE.md 가 `~/agent-sync` 심링크인지
   - `jq '.hooks.SessionStart, .autoDreamEnabled' ~/.claude/settings.json` 이 훅과 true를 출력하는지
   - `launchctl list | grep agentsync` 에 settings-watch 와 merge 두 항목이 있는지
     (git-align·heal 항목은 없는 것이 정상)
   - 훅 파이프 테스트: 아무 git 저장소에서 `echo '{}' | ~/agent-sync/claude/hooks/ensure-automemory.sh`
     실행 후 그 저장소의 `.claude/settings.local.json` 에 autoMemoryDirectory 가 생겼는지
   - `[ -f ~/agent-sync/memory/_global/GLOBAL.md ] && echo OK` 가 OK를 출력하는지
     (전역 메모리 뼈대가 생성됐는지)
   - `git -C ~/agent-sync status --short` 출력이 비어 있는지 (셋업이 git 추적
     파일을 더럽히지 않음 — 기존 CLAUDE.md가 있던 기기 포함)
   - 셋업 전부터 쓰던 저장소가 있다면: 그 저장소에서 세션을 열거나 훅 파이프 테스트 후,
     `~/agent-sync/memory/<저장소명>/` 에 기존 `~/.claude/projects/<키>/memory/` 파일들이
     복사돼 있는지 (원본은 그대로 유지됨)
   - `env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/python3 ~/agent-sync/setup/merge-sync-conflicts.py --check-claude`
     가 claude 경로를 출력하는지 (launchd의 빈 PATH 환경에서 새벽 작업이 claude를 찾는지)
4. **사용자에게 다음 형식으로 안내한다**:

   > 셋업과 검증이 끝났습니다. 이 기기는 단일 기기(solo) 모드입니다 — 에이전트 간
   > 메모리·설정 통합과 새벽 유지보수가 켜졌고, Syncthing·기기 간 동기화는 설치하지
   > 않았습니다. 나중에 기기를 추가하고 싶으시면 이 기기에서
   > `setup-machine.sh --role main` 을 실행하라고 지시해 주세요 — 기존 구성은
   > 그대로 유지되고 동기화 구성만 더해집니다.

## 주의

- `setup/` 안의 스크립트를 수정하지 않는다 (개선은 저장소에 커밋해 배포).
- `~/.claude/settings.json.pre-agent-sync.bak`, `*.premerge.bak` 은 롤백용 백업 — 지우지 말 것.
- 기존 `~/.claude/projects/*/memory/` 는 원본 보존용으로 건드리지 않는다.
- 문제가 생기면 임의로 우회하지 말고 증상 그대로 사용자에게 보고한다.
