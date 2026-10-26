#!/usr/bin/env bash
#
# Verifies the Network Partitioning Invariant empirically.
#
# The invariant is not "we wrote internal: true in a YAML file". It is:
#
#   1. Every service holding raw C_user is on privdeep-internal and cannot
#      reach the internet, by any protocol, including raw IP (so a DNS failure
#      is never mistaken for isolation).
#   2. The reference monitor can reach the internet, or the system is simply
#      broken rather than secure.
#   3. Exactly ONE service is attached to both networks.
#
# Check 3 is the one that rots silently: adding a service to both networks is a
# one-line change that voids the whole architecture and breaks no test unless a
# test looks for it. This script is that test.
#
# Exit 0 only if all three hold. Intended for CI and for the paper's artifact
# appendix, where a referee can re-run it.

set -uo pipefail

INTERNAL_NET="privdeep-internal"
EXTERNAL_NET="privdeep-external"
CONFINED=("privdeep-core" "privdeep-local-slm")
MONITOR="privdeep-reference-monitor"
# Raw IPs on purpose: a container with no DNS but a working route is NOT
# isolated, and a hostname-based probe would call that a pass.
PROBE_IPS=("1.1.1.1" "8.8.8.8" "93.184.216.34")

pass=0; fail=0
ok()   { echo "  PASS  $*"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $*"; fail=$((fail+1)); }
info() { echo "        $*"; }

need_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "docker not installed. See README, section 'Host prerequisites'." >&2; exit 2; }
  docker info >/dev/null 2>&1 || {
    echo "docker daemon unreachable (is your user in the 'docker' group? re-login after usermod)." >&2; exit 2; }
}

running() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

# Portable TCP reachability probe.
#
# /dev/tcp is a bash builtin and these containers ship dash as /bin/sh, so the
# obvious one-liner silently fails everywhere and reports perfect isolation.
# A probe that cannot succeed is worse than no probe: it turns a broken test
# into a green invariant. Try the methods in order and fail loudly if a
# container supports none of them.
probe() {  # probe <container> <ip> -> 0 if reachable
  local c="$1" ip="$2"
  if docker exec "$c" sh -c 'command -v curl' >/dev/null 2>&1; then
    # Capture curl's status before any other command overwrites $?.
    # 7 = could not connect, 28 = timeout. Anything else (including 60, a TLS
    # cert complaint about an IP-addressed host) means the TCP route exists,
    # which is exactly what "not isolated" means.
    docker exec "$c" curl -s -o /dev/null --connect-timeout 3 "https://$ip" 2>/dev/null
    rc=$?
    if [ "$rc" -eq 7 ] || [ "$rc" -eq 28 ]; then return 1; else return 0; fi
  elif docker exec "$c" sh -c 'command -v python3' >/dev/null 2>&1; then
    docker exec "$c" python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(3)
sys.exit(0 if s.connect_ex(('$ip',443))==0 else 1)" 2>/dev/null
  elif docker exec "$c" sh -c 'command -v bash' >/dev/null 2>&1; then
    docker exec "$c" bash -c "timeout 3 cat < /dev/null > /dev/tcp/$ip/443" 2>/dev/null
  else
    echo "PROBE-UNAVAILABLE" >&2
    return 2
  fi
}

probe_capability() {  # fail loudly rather than reporting a false pass
  local c="$1"
  docker exec "$c" sh -c 'command -v curl || command -v python3 || command -v bash' >/dev/null 2>&1
}

echo "== 1. Confined services cannot reach the internet =="
for svc in "${CONFINED[@]}"; do
  if ! running "$svc"; then bad "$svc is not running"; continue; fi
  if ! probe_capability "$svc"; then
    bad "$svc has no usable probe tool (curl/python3/bash); cannot verify isolation"
    continue
  fi
  reached=""
  for ip in "${PROBE_IPS[@]}"; do
    if probe "$svc" "$ip"; then reached="$reached $ip"; fi
  done
  if [ -n "$reached" ]; then
    bad "$svc reached the internet at:$reached  -- PARTITION VIOLATED"
  else
    ok "$svc cannot reach any of ${PROBE_IPS[*]} on :443"
  fi
done

echo
echo "== 2. Reference monitor CAN reach the internet =="
if ! running "$MONITOR"; then
  bad "$MONITOR is not running"
else
  if ! probe_capability "$MONITOR"; then
    bad "$MONITOR has no usable probe tool; cannot verify egress"
  fi
  reached=""
  for ip in "${PROBE_IPS[@]}"; do
    if probe "$MONITOR" "$ip"; then reached="$reached $ip"; fi
  done
  if [ -n "$reached" ]; then ok "$MONITOR has egress via:$reached"
  else bad "$MONITOR has NO egress; the system cannot function"; fi
fi

echo
echo "== 3. Exactly one service is dual-homed =="
int_members=$(docker network inspect "$INTERNAL_NET" -f '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null)
ext_members=$(docker network inspect "$EXTERNAL_NET" -f '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null)
if [ -z "$int_members" ] && [ -z "$ext_members" ]; then
  bad "neither network exists; run 'docker compose up -d' first"
else
  info "internal: ${int_members:-<none>}"
  info "external: ${ext_members:-<none>}"
  dual=""
  for c in $int_members; do
    case " $ext_members " in *" $c "*) dual="$dual $c";; esac
  done
  dual=$(echo "$dual" | xargs || true)
  if [ "$dual" = "$MONITOR" ]; then
    ok "only $MONITOR is on both networks"
  elif [ -z "$dual" ]; then
    bad "no service bridges the networks; egress is impossible"
  else
    bad "MORE THAN THE MONITOR IS DUAL-HOMED: $dual  -- ARCHITECTURE VOID"
  fi
fi

echo
echo "== 4. internal network is declared internal =="
if [ "$(docker network inspect "$INTERNAL_NET" -f '{{.Internal}}' 2>/dev/null)" = "true" ]; then
  ok "$INTERNAL_NET has Internal=true"
else
  bad "$INTERNAL_NET is NOT marked internal"
fi

echo
echo "-------- $pass passed, $fail failed --------"
[ "$fail" -eq 0 ] || exit 1
echo "Network Partitioning Invariant holds."
