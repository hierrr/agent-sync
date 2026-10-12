#!/usr/bin/env python3
"""~/.codex/config.toml 의 [sandbox_workspace_write].writable_roots 에
~/agent-sync/memory 절대 경로를 보장한다 (idempotent).

왜 필요한가: Codex 의 기본 샌드박스(workspace-write)는 작업 폴더 밖 쓰기를
차단한다. 그래서 전역 AGENTS.md 의 "기억을 ~/agent-sync/memory/<저장소명>/ 에
저장하라" 지시가 샌드박스에 막혀 실패한다. 이 경로를 writable_roots 에 넣어야
지시가 실제로 동작한다. 이 설정은 기기별 파일(~/.codex/config.toml)이라 동기화되지
않으므로 기기마다 셋업이 적용한다.

텍스트 기반 편집기다 — 시스템 /usr/bin/python3 는 3.9 라 tomllib 이 없고 외부
패키지도 쓰지 않는다. 확신할 수 없는 형태(여러 줄 배열 등)는 파일을 건드리지 않고
수동 추가 안내만 출력한다. 내용을 바꿀 때만 최초 1회 config.toml.pre-agent-sync.bak
을 만들고(이미 있으면 보존), 임시 파일 + os.replace 로 원자적으로 쓴다 — Codex 가
실행 중 이 파일을 자체 갱신하기 때문이다.

출력(한 줄): created / added / already ok / manual needed
"""
import io
import os
import re
import shutil
import sys
import tempfile

TABLE = "sandbox_workspace_write"
KEY = "writable_roots"

HEADER_RE = re.compile(r"^\s*\[" + TABLE + r"\]\s*(#.*)?$")
# 따옴표 헤더·인라인 테이블·점 표기 등 변형 — 새 테이블을 추가하면 중복 정의가 되므로 수동 처리
VARIANT_RE = re.compile(
    r"^\s*(\[\s*[\"']" + TABLE + r"[\"']\s*\]|" + TABLE + r"\s*[.=]|\[\[\s*" + TABLE + r")"
)
ANY_TABLE_RE = re.compile(r"^\s*\[")
KEY_RE = re.compile(r"^(\s*)" + KEY + r"\s*=\s*(.*?)(\r?\n)?$", re.S)


def quote(path):
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_one_line_array(value):
    """'[ ... ]' 한 줄 배열을 파싱한다.
    반환: (원소 문자열 리스트, 닫는 ']' 의 value 내 인덱스) / 형태를 확신 못 하면 None."""
    if not value.startswith("["):
        return None
    i, n = 1, len(value)
    items = []
    expect_value = True  # 다음에 원소가 와야 하는 위치(쉼표 직후·시작)
    while i < n:
        c = value[i]
        if c in " \t":
            i += 1
        elif c == "]":
            rest = value[i + 1:].strip()
            if rest and not rest.startswith("#"):
                return None
            return items, i
        elif c == ",":
            if expect_value:
                return None
            expect_value = True
            i += 1
        elif c in "\"'":
            if not expect_value:
                return None
            j = i + 1
            buf = []
            while j < n and value[j] != c:
                if c == '"' and value[j] == "\\":
                    if j + 1 >= n:
                        return None
                    nxt = value[j + 1]
                    if nxt not in '\\"':
                        return None  # 이스케이프 변형은 확신 불가
                    buf.append(nxt)
                    j += 2
                else:
                    buf.append(value[j])
                    j += 1
            if j >= n:
                return None  # 닫는 따옴표 없음 (여러 줄 문자열 등)
            items.append("".join(buf))
            expect_value = False
            i = j + 1
        else:
            return None  # 문자열 외 토큰·개행(여러 줄 배열) 등
    return None  # ']' 가 같은 줄에 없음 — 여러 줄 배열


def atomic_write(real, text, mode):
    d = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(prefix=".config.toml.", suffix=".tmp", dir=d)
    try:
        with io.open(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def compute(text, path):
    """반환: (상태, 새 텍스트) — 상태: created/added/ok/manual."""
    q = quote(path)
    eol = "\r\n" if "\r\n" in text else "\n"
    key_line = "%s = [%s]%s" % (KEY, q, eol)

    lines = text.splitlines(keepends=True)
    if any(VARIANT_RE.match(l) for l in lines):
        return "manual", text
    hdr = next((i for i, l in enumerate(lines) if HEADER_RE.match(l)), None)

    if hdr is None:
        if text and not text.endswith("\n"):
            text += eol
        if text.strip():
            text += eol
        return "added", text + "[%s]%s%s" % (TABLE, eol, key_line)

    end = len(lines)
    for i in range(hdr + 1, len(lines)):
        if ANY_TABLE_RE.match(lines[i]):
            end = i
            break

    for i in range(hdr + 1, end):
        m = KEY_RE.match(lines[i])
        if not m:
            continue
        parsed = parse_one_line_array(m.group(2))
        if parsed is None:
            return "manual", text
        items, close = parsed
        if any(os.path.normpath(it) == path for it in items):
            return "ok", text
        value = m.group(2)
        before = value[:close]
        stripped = before.rstrip()
        trailing_ws = before[len(stripped):]
        if not items:
            new_value = "[" + q + value[close:]  # 빈 배열: ["<경로>"]
        else:
            sep = " " if stripped.endswith(",") else ", "
            new_value = stripped + sep + q + trailing_ws + value[close:]
        eol_part = m.group(3) or ""
        lines[i] = m.group(1) + KEY + " = " + new_value + eol_part
        return "added", "".join(lines)

    # 테이블은 있으나 키가 없음 — 헤더 바로 다음 줄에 삽입
    if not lines[hdr].endswith("\n"):
        lines[hdr] += eol
    lines.insert(hdr + 1, key_line)
    return "added", "".join(lines)


def main():
    home = os.path.expanduser("~")
    codex_dir = os.path.join(home, ".codex")
    if not os.path.isdir(codex_dir):
        return 0
    path = os.path.expanduser("~/agent-sync/memory")
    cfg = os.path.join(codex_dir, "config.toml")
    real = os.path.realpath(cfg)

    try:
        exists = os.path.exists(real)
        if exists:
            with io.open(real, "r", encoding="utf-8", newline="") as f:
                text = f.read()
            mode = os.stat(real).st_mode & 0o777
        else:
            text, mode = "", 0o600
        status, new_text = compute(text, path)

        if status == "manual":
            print("codex config: manual needed — 수동으로 추가 필요: %s "
                  "(%s 의 [%s] %s 배열)" % (path, cfg, TABLE, KEY))
            return 0
        if status == "ok":
            print("codex config: already ok")
            return 0

        if exists:
            bak = real + ".pre-agent-sync.bak"
            if not os.path.exists(bak):
                shutil.copy2(real, bak)
        atomic_write(real, new_text, mode)
        print("codex config: %s" % ("added" if exists else "created"))
        return 0
    except (OSError, UnicodeDecodeError) as e:
        # 셋업 전체를 중단시키지 않는다 — 수동 안내만 남김
        print("codex config: manual needed — 수동으로 추가 필요: %s (%s)" % (path, e))
        return 0


if __name__ == "__main__":
    sys.exit(main())
