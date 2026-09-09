#!/usr/bin/env python3
"""Syncthing 자가 복구 감시.

사무실 내부망은 기기 자동 발견(브로드캐스트)이 막혀 있어 상대 기기 주소를
정적으로 등록해두는데, 그 주소가 DHCP라 바뀌면 연결이 조용히 끊기고 자동
복구가 안 된다. 이 스크립트는 launchd로 몇 분 간격 실행되어:
  1. 지금 끊긴 등록 기기가 있는지 확인하고, 없으면 아무 것도 안 하고 종료.
  2. 있으면 내부망을 22000 포트로 스캔해 열린 호스트를 찾고, 그 후보들을
     끊긴 기기의 접속 주소로 임시 등록한 뒤 실제 연결이 성립하는지로 신원을
     확인한다. Syncthing은 등록된 장치 ID와 인증서가 일치하는 상대하고만
     연결을 맺으므로, 연결 성립 여부 자체가 곧 검증이다 (틀린 후보는 그냥
     연결이 안 될 뿐 부작용이 없다).
     -- macOS 기본 /usr/bin/python3(LibreSSL)은 Syncthing이 쓰는 Ed25519
     인증서로 TLS 핸드셰이크 자체가 안 되어(TLSV1_ALERT_PROTOCOL_VERSION),
     여기서 TLS 인증서로 장치 ID를 직접 계산하는 방식은 launchd 환경에서
     쓸 수 없다. 그 계산 코드는 --scan 디버그 출력에만 "가능하면" 참고용으로
     남겨둔다.
표준 라이브러리만 사용 (macOS 기본 /usr/bin/python3, 3.9 호환).
"""
import base64
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_BASE = "http://127.0.0.1:8384"
CONFIG_XML = os.path.expanduser("~/Library/Application Support/Syncthing/config.xml")
SCAN_PORT = 22000
CONNECT_TIMEOUT = 1.0
TLS_TIMEOUT = 5.0
MAX_WORKERS = 128
TIME_BUDGET = 110.0  # 전체 실행 상한 ~120초 안에서 여유를 둠 (대기 루프 포함)
PROBE_WAIT_MAX = 45.0
PROBE_WAIT_STEP = 5.0

START = time.monotonic()


def time_left():
    return TIME_BUDGET - (time.monotonic() - START)


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --- 장치 ID 계산 (오늘 실 기기로 검증 완료 — 수정하지 말 것)
# --scan 디버그 전용. LibreSSL(/usr/bin/python3)에서는 Ed25519 인증서라
# TLS 핸드셰이크 자체가 실패해 항상 None을 반환한다 (Homebrew python처럼
# OpenSSL 3.x가 있는 환경에서만 성공) -- heal 경로는 이 함수에 의존하지 않는다.

ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def luhn32(s):
    factor, total, n = 1, 0, 32
    for ch in s:
        addend = factor * ALPH.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // n + addend % n
    return ALPH[(n - total % n) % n]


def device_id(der):
    b32 = base64.b32encode(hashlib.sha256(der).digest()).decode().rstrip("=")
    full = "".join(c + luhn32(c) for c in (b32[i:i + 13] for i in range(0, 52, 13)))
    return "-".join(full[i:i + 7] for i in range(0, 56, 7))


# --- Syncthing REST API ---------------------------------------------------

def read_api_key():
    if not os.path.exists(CONFIG_XML):
        return None
    with open(CONFIG_XML, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"<apikey>(.*?)</apikey>", content)
    return m.group(1) if m else None


def api_request(key, path, method="GET", body=None):
    url = API_BASE + path
    data = None
    headers = {"X-API-Key": key}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def get_state(key):
    """자기 ID, 등록 기기 목록, 연결 상태 맵을 한 번에 조회."""
    status = api_request(key, "/rest/system/status")
    my_id = status.get("myID")
    devices = api_request(key, "/rest/config/devices") or []
    connections = api_request(key, "/rest/system/connections") or {}
    conn_map = connections.get("connections", {})
    return my_id, devices, conn_map


def disconnected_from(my_id, devices, conn_map):
    """자기 자신 아님 + paused 아님 + connected 아님인 등록 기기 목록."""
    disconnected = []
    for dev in devices:
        dev_id = dev.get("deviceID")
        if not dev_id or dev_id == my_id:
            continue
        if dev.get("paused"):
            continue
        conn = conn_map.get(dev_id, {})
        if conn.get("connected"):
            continue
        disconnected.append(dev)
    return disconnected


def connected_ips(my_id, conn_map):
    """현재 연결되어 있는 다른 기기들의 접속 IP 집합 (후보에서 제외용)."""
    ips = set()
    for dev_id, info in conn_map.items():
        if dev_id == my_id or not info.get("connected"):
            continue
        addr = info.get("address", "")
        if not addr:
            continue
        ips.add(addr.rsplit(":", 1)[0])
    return ips


# --- 후보 IP 수집 ----------------------------------------------------------

def parse_arp_candidates(self_ips):
    """`arp -an` 출력을 파싱해 완전한 IPv4 후보만 추출.
    -n(숫자 전용)을 반드시 써야 한다 -- 심볼릭 이름 조회(-a 단독)는 DNS
    역조회 지연으로 10초 넘게 걸릴 수 있다."""
    candidates = set()
    try:
        out = subprocess.check_output(["arp", "-an"], stderr=subprocess.DEVNULL, timeout=10).decode(errors="ignore")
    except Exception:
        return candidates
    for line in out.splitlines():
        if "incomplete" in line:
            continue
        m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
        if not m:
            continue
        ip = m.group(1)
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_multicast or ip.startswith("255.") or ip in self_ips:
            continue
        candidates.add(ip)
    return candidates


def parse_ifconfig_subnets():
    """활성 IPv4 인터페이스의 (ip, netmask_hex) 목록."""
    subnets = []
    try:
        out = subprocess.check_output(["ifconfig"], stderr=subprocess.DEVNULL, timeout=10).decode(errors="ignore")
    except Exception:
        return subnets
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("inet "):
            continue
        m = re.match(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", line)
        if not m:
            continue
        ip, mask_hex = m.group(1), m.group(2)
        if ip.startswith("127."):
            continue
        subnets.append((ip, mask_hex))
    return subnets


def enumerate_lan_hosts(subnets):
    """/22 이상(호스트 <=1022)인 서브넷만 전 호스트 열거. 자기/네트워크/브로드캐스트 제외."""
    hosts = set()
    self_ips = set(ip for ip, _ in subnets)
    for ip, mask_hex in subnets:
        try:
            mask_int = int(mask_hex, 16)
            prefix = bin(mask_int).count("1")
            iface = ipaddress.IPv4Interface("%s/%d" % (ip, prefix))
            network = iface.network
        except (ValueError, OverflowError):
            continue
        if network.num_addresses > 1024:  # /22보다 큰 대역은 열거하지 않음
            continue
        for host in network.hosts():
            host_ip = str(host)
            if host_ip in self_ips:
                continue
            hosts.add(host_ip)
    return hosts, self_ips


def broadcast_addresses(subnets):
    result = set()
    for ip, mask_hex in subnets:
        try:
            mask_int = int(mask_hex, 16)
            prefix = bin(mask_int).count("1")
            iface = ipaddress.IPv4Interface("%s/%d" % (ip, prefix))
            result.add(str(iface.network.broadcast_address))
        except (ValueError, OverflowError):
            continue
    return result


def collect_candidate_ips():
    subnets = parse_ifconfig_subnets()
    self_ips = set(ip for ip, _ in subnets)
    broadcasts = broadcast_addresses(subnets)

    candidates = set()
    candidates |= parse_arp_candidates(self_ips)
    lan_hosts, _ = enumerate_lan_hosts(subnets)
    candidates |= lan_hosts
    candidates -= self_ips
    candidates -= broadcasts
    candidates.discard("255.255.255.255")
    return candidates


def is_port_open(ip, port=SCAN_PORT, timeout=CONNECT_TIMEOUT):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_open_hosts():
    """내부망 후보 중 22000 포트가 열려 있는 호스트 목록."""
    candidates = collect_candidate_ips()
    if not candidates:
        return []
    open_hosts = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(is_port_open, ip): ip for ip in candidates}
        for fut in futures:
            ip = futures[fut]
            try:
                if fut.result():
                    open_hosts.append(ip)
            except Exception:
                continue
    return open_hosts


def get_tls_device_id(ip, port=SCAN_PORT, timeout=TLS_TIMEOUT):
    """--scan 디버그 전용. LibreSSL 환경에서는 대개 None을 반환한다."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=ip) as tls:
                der = tls.getpeercert(binary_form=True)
        if not der:
            return None
        return device_id(der)
    except (OSError, ssl.SSLError):
        return None


# --- 메인 로직: 연결 성립 여부로 신원을 검증하는 프로브 방식 -------------

def heal(key, my_id, disconnected, conn_map):
    open_hosts = scan_open_hosts()
    in_use = connected_ips(my_id, conn_map)
    candidates = sorted(set(open_hosts) - in_use)

    if not candidates:
        names = [d.get("name") or d.get("deviceID", "")[:7] for d in disconnected]
        print("%s not found: %s" % (now(), ", ".join(names)))
        return

    candidate_set = set(candidates)
    originals = {}  # dev_id -> (name, 원래 addresses)

    for dev in disconnected:
        dev_id = dev.get("deviceID")
        name = dev.get("name") or dev_id[:7]
        old_addrs = dev.get("addresses") or ["dynamic"]
        originals[dev_id] = (name, old_addrs)

        # 기존 tcp:// 주소 중, 새 후보와 안 겹치면서 지금도 열려 있는 것만 유지
        kept = []
        for addr in old_addrs:
            if not addr.startswith("tcp://"):
                continue
            host = addr[len("tcp://"):].rsplit(":", 1)[0]
            if host in candidate_set:
                continue
            if is_port_open(host, timeout=1.0):
                kept.append(addr)

        probe_addrs = ["dynamic"] + ["tcp://%s:%d" % (ip, SCAN_PORT) for ip in candidates] + kept
        try:
            api_request(key, "/rest/config/devices/%s" % dev_id, method="PATCH", body={"addresses": probe_addrs})
        except Exception as e:
            print("%s error patching %s: %s" % (now(), name, e))
            continue
        print("%s probing %s with %d candidates" % (now(), name, len(candidates)))

    # 공용 대기 루프: 5초 간격, 최대 45초 (전체 시간 예산 안에서)
    pending_ids = set(originals.keys())
    healed_addr = {}
    deadline = max(0.0, min(PROBE_WAIT_MAX, time_left()))
    waited = 0.0
    while pending_ids and waited < deadline:
        time.sleep(PROBE_WAIT_STEP)
        waited += PROBE_WAIT_STEP
        try:
            connections = api_request(key, "/rest/system/connections") or {}
        except Exception:
            continue
        cmap = connections.get("connections", {})
        newly = set()
        for dev_id in pending_ids:
            info = cmap.get(dev_id, {})
            if not info.get("connected"):
                continue
            addr = info.get("address", "")
            host = addr.rsplit(":", 1)[0] if addr else None
            if host:
                healed_addr[dev_id] = host
                newly.add(dev_id)
        pending_ids -= newly

    for dev_id, host in healed_addr.items():
        name, _ = originals[dev_id]
        final_addrs = ["dynamic", "tcp://%s:%d" % (host, SCAN_PORT)]
        try:
            api_request(key, "/rest/config/devices/%s" % dev_id, method="PATCH", body={"addresses": final_addrs})
        except Exception as e:
            print("%s error finalizing %s: %s" % (now(), name, e))
            continue
        print("%s healed %s %s -> tcp://%s:%d" % (now(), name, dev_id[:7], host, SCAN_PORT))

    not_found_names = []
    for dev_id in pending_ids:
        name, old_addrs = originals[dev_id]
        try:
            api_request(key, "/rest/config/devices/%s" % dev_id, method="PATCH", body={"addresses": old_addrs})
        except Exception as e:
            print("%s error restoring %s: %s" % (now(), name, e))
        not_found_names.append(name)

    if not_found_names:
        print("%s not found: %s (restored addresses)" % (now(), ", ".join(not_found_names)))


def cmd_scan_debug(key):
    """--scan: 전체 스캔 강제, 발견 결과만 출력하고 아무것도 바꾸지 않음.
    TLS 장치 ID는 가능하면(OpenSSL 3.x 환경) 계산하고, 안 되면 현재 연결
    중인 기기의 접속 주소와 대조해 참고용으로만 표기한다."""
    devices = api_request(key, "/rest/config/devices") or []
    id_to_name = {d.get("deviceID"): (d.get("name") or "") for d in devices}

    connections = api_request(key, "/rest/system/connections") or {}
    conn_map = connections.get("connections", {})
    addr_to_id = {}
    for dev_id, info in conn_map.items():
        addr = info.get("address", "")
        if not addr:
            continue
        addr_to_id[addr.rsplit(":", 1)[0]] = dev_id

    open_hosts = scan_open_hosts()
    if not open_hosts:
        print("%s scan: no hosts found on port %d" % (now(), SCAN_PORT))
        return

    for ip in sorted(open_hosts):
        did = get_tls_device_id(ip)
        if did:
            name = id_to_name.get(did, "(등록되지 않은 기기)")
            print("%s scan: %s -> %s (%s)" % (now(), ip, did, name))
            continue
        matched_id = addr_to_id.get(ip)
        if matched_id:
            name = id_to_name.get(matched_id) or matched_id[:7]
            print("%s scan: %s -> (식별 불가 — 시스템 SSL 한계) (currently connected as %s)" % (now(), ip, name))
        else:
            print("%s scan: %s -> (식별 불가 — 시스템 SSL 한계)" % (now(), ip))


def _on_timeout(signum, frame):
    print("%s error: timed out after ~%ds, aborting" % (now(), int(TIME_BUDGET)))
    os._exit(0)


def main():
    force_scan = "--scan" in sys.argv[1:]

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _on_timeout)
        signal.alarm(int(TIME_BUDGET) + 5)  # 전체 실행 시간 상한(겹침 방지)

    key = read_api_key()
    if not key:
        return 0

    try:
        api_request(key, "/rest/system/status")
    except Exception:
        return 0  # API 미응답 -- 조용히 종료

    try:
        if force_scan:
            cmd_scan_debug(key)
            return 0

        my_id, devices, conn_map = get_state(key)
        disconnected = disconnected_from(my_id, devices, conn_map)
        if not disconnected:
            return 0

        if time_left() <= 0:
            return 0
        heal(key, my_id, disconnected, conn_map)
    except urllib.error.URLError:
        return 0
    except Exception as e:
        print("%s error: %s" % (now(), e))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
