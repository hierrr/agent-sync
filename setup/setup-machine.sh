#!/bin/bash
# agent-sync 머신 셋업 (idempotent — 여러 번 실행해도 안전)
#
# 사용법:
#   ./setup-machine.sh --role main                  # 허브 1대. 완료 후 60분간 신규 기기 자동 수락
#   ./setup-machine.sh --role sub --main-id <ID>    # 나머지 모든 기기 (<ID> = main 셋업이 출력한 장치 ID)
#   ./setup-machine.sh --accept <ID>                # main에서 특정 기기 즉시 수락 (나중 추가용)
#   ./setup-machine.sh --enroll [분]                # main에서 신규 기기 등록 창 재개방 (기본 60분)
#   ./setup-machine.sh --enroll-stop                # 등록 창 즉시 닫기
set -euo pipefail

SYNC="$HOME/agent-sync"
LAUNCH="$HOME/Library/LaunchAgents"
ENROLL_PID="$SYNC/setup/logs/enroll.pid"
ST="/Applications/Syncthing.app/Contents/Resources/syncthing/syncthing"

ROLE="" MAIN_ID="" ACCEPT_ID="" ENROLL_ONLY="" ENROLL_MIN="60"
while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="$2"; shift 2 ;;
        --main-id) MAIN_ID="$2"; shift 2 ;;
        --accept) ACCEPT_ID="$2"; shift 2 ;;
        --enroll) ENROLL_ONLY=1; if [[ "${2:-}" =~ ^[0-9]+$ ]]; then ENROLL_MIN="$2"; shift; fi; shift ;;
        --enroll-stop)
            if [ -f "$ENROLL_PID" ] && kill "$(cat "$ENROLL_PID")" 2>/dev/null; then
                rm -f "$ENROLL_PID"; echo "등록 창을 닫았습니다."
            else
                echo "열려 있는 등록 창이 없습니다."
            fi
            exit 0 ;;
        *) echo "알 수 없는 인자: $1"; exit 1 ;;
    esac
done

# Syncthing은 메뉴바 앱(cask syncthing-app) 하나로만 설치·구동한다 — macOS 15+에서
# brew services(launchd) 데몬은 로컬 네트워크 권한을 받을 방법이 없어 LAN 다이얼이
# 조용히 차단되기 때문. CLI도 앱 내장 바이너리($ST)를 쓰고, 에이전트·문서가 쓰는
# `syncthing` 명령은 /usr/local/bin 심링크로 제공한다. 구 brew formula는 발견 시
# 서비스 중지 후 제거한다. 앱 최초 실행 시 뜨는 "로컬 네트워크 허용" 팝업은
# 사용자가 직접 허용해야 한다.
ensure_syncthing() {
    [ -d "/Applications/Syncthing.app" ] || { echo "installing Syncthing.app..."; brew install --cask syncthing-app; }
    if brew list --formula syncthing >/dev/null 2>&1; then
        brew services stop syncthing >/dev/null 2>&1 || true
        brew uninstall syncthing >/dev/null 2>&1 && echo "removed legacy brew formula syncthing"
    fi
    ln -sfn "$ST" /usr/local/bin/syncthing 2>/dev/null || true
    pgrep -x Syncthing >/dev/null 2>&1 || open -a Syncthing
    osascript -e 'tell application "System Events" to get login item "Syncthing"' >/dev/null 2>&1 || \
        osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Syncthing.app", hidden:true}' >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
        "$ST" cli show system >/dev/null 2>&1 && return 0
        sleep 1
    done
    echo "WARN: Syncthing API가 응답하지 않습니다. 페어링 단계는 수동 확인 필요." >&2
    return 1
}

ensure_folder() {
    "$ST" cli config folders list 2>/dev/null | grep -qx agent-sync || \
        "$ST" cli config folders add --id agent-sync --label agent-sync --path "$SYNC"
    "$ST" cli config folders agent-sync versioning type set staggered 2>/dev/null || true
}

# 내부망 전용: 릴레이·글로벌 디스커버리·NAT 매핑을 끄고 LAN 디스커버리만 사용.
# 기기 간 연결은 같은 내부망(유선/무선/TB 브리지) 직결로만 성립하고, 파일이
# 외부 릴레이 서버를 경유하거나 공인 IP가 디스커버리 서버에 공개되지 않는다.
ensure_lan_only() {
    "$ST" cli config options relays-enabled set false 2>/dev/null || true
    "$ST" cli config options global-ann-enabled set false 2>/dev/null || true
    "$ST" cli config options natenabled set false 2>/dev/null || true
    "$ST" cli config options local-ann-enabled set true 2>/dev/null || true
}

# 등록 창: 지정한 시간 동안만 10초 간격으로 대기 기기를 자동 수락하고 스스로 종료
start_enroll() {
    local minutes="$1"
    if [ -f "$ENROLL_PID" ] && kill -0 "$(cat "$ENROLL_PID")" 2>/dev/null; then
        echo "등록 창이 이미 열려 있습니다 (pid $(cat "$ENROLL_PID"))."
        return 0
    fi
    nohup bash -c '
        minutes="$1"; pidfile="$2"
        ST="/Applications/Syncthing.app/Contents/Resources/syncthing/syncthing"
        CFG="$HOME/Library/Application Support/Syncthing/config.xml"
        KEY=$(sed -n "s/.*<apikey>\(.*\)<\/apikey>.*/\1/p" "$CFG" | head -1)
        end=$((SECONDS + minutes * 60))
        while [ $SECONDS -lt $end ]; do
            curl -s -m 5 -H "X-API-Key: $KEY" http://127.0.0.1:8384/rest/cluster/pending/devices 2>/dev/null |
            python3 -c "
import json, sys
try:
    devices = json.load(sys.stdin)
except Exception:
    devices = {}
for device_id in devices:
    print(device_id)" | while read -r dev; do
                [ -n "$dev" ] || continue
                "$ST" cli config devices add --device-id "$dev" --auto-accept-folders 2>/dev/null || true
                "$ST" cli config folders agent-sync devices add --device-id "$dev" 2>/dev/null || true
                echo "$(date "+%F %T") accepted: $dev"
            done
            sleep 10
        done
        echo "$(date "+%F %T") enrollment window closed (${minutes}m)"
        rm -f "$pidfile"
    ' _ "$minutes" "$ENROLL_PID" >> "$SYNC/setup/logs/enroll.log" 2>&1 &
    echo $! > "$ENROLL_PID"
    echo "신규 기기 등록 창 개방: ${minutes}분간 접속해오는 기기를 자동 수락 후 자동 종료됩니다."
    echo "  (조기 종료: ./setup-machine.sh --enroll-stop / 로그: setup/logs/enroll.log)"
}

mkdir -p "$SYNC/setup/logs" "$LAUNCH" "$HOME/.claude"

# --accept 단독 실행 (main에서 특정 기기 즉시 수락)
if [ -n "$ACCEPT_ID" ]; then
    ensure_syncthing && ensure_folder
    "$ST" cli config devices list 2>/dev/null | grep -qx "$ACCEPT_ID" || \
        "$ST" cli config devices add --device-id "$ACCEPT_ID" --auto-accept-folders
    "$ST" cli config folders agent-sync devices add --device-id "$ACCEPT_ID" 2>/dev/null || true
    echo "기기를 수락하고 agent-sync 폴더를 공유했습니다: $ACCEPT_ID"
    echo "연결 확인: syncthing cli show connections"
    exit 0
fi

# --enroll 단독 실행 (main에서 기기 추가 시)
if [ -n "$ENROLL_ONLY" ]; then
    ensure_syncthing && ensure_folder && start_enroll "$ENROLL_MIN"
    exit 0
fi

if [ "$ROLE" != "main" ] && [ "$ROLE" != "sub" ]; then
    echo "사용법: --role main | --role sub --main-id <ID> | --enroll [분] | --enroll-stop" >&2
    exit 1
fi
if [ "$ROLE" = "sub" ] && [ -z "$MAIN_ID" ]; then
    echo "ERROR: sub 역할은 --main-id <main의 장치 ID> 가 필요합니다 (main 셋업 출력 참고)." >&2
    exit 1
fi
if [ ! -d "$SYNC/claude" ]; then
    echo "ERROR: ~/agent-sync 가 없습니다. 먼저 git clone 하세요:" >&2
    echo "  git clone https://github.com/hierrr/agent-sync.git ~/agent-sync" >&2
    exit 1
fi

# 1. ~/.claude 의 agents/skills/commands 를 동기화 폴더로 심링크
#    (기존 내용은 동기화 폴더로 흡수한 뒤 .premerge.bak 으로 보존)
mkdir -p "$SYNC/claude/agents" "$SYNC/claude/skills" "$SYNC/claude/commands"
for d in agents skills commands; do
    target="$HOME/.claude/$d"
    if [ -L "$target" ]; then
        continue
    fi
    if [ -d "$target" ]; then
        cp -an "$target/." "$SYNC/claude/$d/" 2>/dev/null || true
        mv "$target" "$target.premerge.bak"
    fi
    ln -s "$SYNC/claude/$d" "$target"
    echo "linked ~/.claude/$d"
done

# 2. 전역 CLAUDE.md 심링크 (기존 내용은 동기화본에 병합 후 보존)
target="$HOME/.claude/CLAUDE.md"
if [ ! -L "$target" ]; then
    if [ -f "$target" ]; then
        cat "$target" >> "$SYNC/claude/CLAUDE.md"
        mv "$target" "$target.premerge.bak"
    fi
    ln -s "$SYNC/claude/CLAUDE.md" "$target"
    echo "linked ~/.claude/CLAUDE.md"
fi

# 3. Codex 전역 지침 심링크
if [ -d "$HOME/.codex" ] && [ ! -L "$HOME/.codex/AGENTS.md" ]; then
    [ -f "$HOME/.codex/AGENTS.md" ] && cat "$HOME/.codex/AGENTS.md" >> "$SYNC/codex/AGENTS.md" \
        && mv "$HOME/.codex/AGENTS.md" "$HOME/.codex/AGENTS.md.premerge.bak"
    ln -s "$SYNC/codex/AGENTS.md" "$HOME/.codex/AGENTS.md"
    echo "linked ~/.codex/AGENTS.md"
fi

# 4. 공유 base 설정을 이 머신의 ~/.claude/settings.json 에 병합
#    (SessionStart 훅 + autoDreamEnabled; permissions 등 머신 로컬 항목은 보존)
/usr/bin/python3 "$SYNC/setup/apply-settings.py"
chmod +x "$SYNC/claude/hooks/"*.sh

# 5. base 설정 변경 시 자동 재적용하는 감시 에이전트 설치
sed "s|__HOME__|$HOME|g" "$SYNC/setup/com.palusomni.agentsync.settings-watch.plist" \
    > "$LAUNCH/com.palusomni.agentsync.settings-watch.plist"
launchctl unload "$LAUNCH/com.palusomni.agentsync.settings-watch.plist" 2>/dev/null || true
launchctl load "$LAUNCH/com.palusomni.agentsync.settings-watch.plist"
echo "loaded settings-watch launch agent"

# 6. pull 브로드캐스트: 한 기기에서 pull하면 이 기기까지 git이 자동으로 맞춰진다.
#    post-merge 훅이 pull(merge) 성공 시 .last-pull에 epoch를 기록 → Syncthing이
#    그 파일을 전 기기에 전파 → 각 기기의 감시 에이전트가 변경을 감지해
#    git-align.sh로 origin/main에 정렬한다 (실제 내용 차이가 있으면 손대지 않음).
cat > "$SYNC/.git/hooks/post-merge" <<'HOOK'
#!/bin/bash
# agent-sync-managed -- setup-machine.sh overwrites this on every run.
# Pull(merge) succeeded: stamp a sentinel Syncthing can propagate so every
# other machine's git-align watcher knows to realign.
date +%s > "$(git rev-parse --show-toplevel 2>/dev/null || echo .)/.last-pull"
HOOK
chmod +x "$SYNC/.git/hooks/post-merge"
echo "installed post-merge git hook"

sed "s|__HOME__|$HOME|g" "$SYNC/setup/com.palusomni.agentsync.git-align.plist" \
    > "$LAUNCH/com.palusomni.agentsync.git-align.plist"
launchctl unload "$LAUNCH/com.palusomni.agentsync.git-align.plist" 2>/dev/null || true
launchctl load "$LAUNCH/com.palusomni.agentsync.git-align.plist"
echo "loaded git-align watch launch agent"

# 7. main 만: 새벽 4:30 메모리 유지보수 (git 정렬 → 동기화 충돌 병합 → dream 패스)
if [ "$ROLE" = "main" ]; then
    sed "s|__HOME__|$HOME|g" "$SYNC/setup/com.palusomni.agentsync.merge.plist" \
        > "$LAUNCH/com.palusomni.agentsync.merge.plist"
    launchctl unload "$LAUNCH/com.palusomni.agentsync.merge.plist" 2>/dev/null || true
    launchctl load "$LAUNCH/com.palusomni.agentsync.merge.plist"
    echo "loaded nightly merge launch agent (main role)"
fi

# 8. Syncthing 설치·기동·폴더 등록·내부망 전용·페어링
ensure_syncthing
ensure_folder
ensure_lan_only
DEVICE_ID=$("$ST" cli show system 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["myID"])' 2>/dev/null || echo "UNKNOWN")

if [ "$ROLE" = "sub" ]; then
    "$ST" cli config devices list 2>/dev/null | grep -qx "$MAIN_ID" || \
        "$ST" cli config devices add --device-id "$MAIN_ID" --name main --introducer --auto-accept-folders
    "$ST" cli config folders agent-sync devices add --device-id "$MAIN_ID" 2>/dev/null || true
fi

echo ""
echo "=== 셋업 완료 (role: $ROLE) ==="
echo "이 기기의 장치 ID: $DEVICE_ID"
if [ "$ROLE" = "main" ]; then
    start_enroll "$ENROLL_MIN"
    echo ""
    echo "다른 기기에서 실행할 명령 (등록 창이 열린 동안 실행하면 나머지는 전부 자동):"
    echo "  git clone https://github.com/hierrr/agent-sync.git ~/agent-sync 2>/dev/null || true"
    echo "  chmod +x ~/agent-sync/setup/setup-machine.sh"
    echo "  ~/agent-sync/setup/setup-machine.sh --role sub --main-id $DEVICE_ID"
    echo ""
    echo "등록 창이 닫힌 뒤 기기를 추가하려면 main에서: ./setup-machine.sh --enroll"
else
    echo "main의 등록 창이 열려 있으면 자동 수락됩니다 (최대 ~1분)."
    echo "확인: syncthing cli show connections"
    echo "연결이 안 되면 main에서 실행: ./setup-machine.sh --accept $DEVICE_ID"
fi
