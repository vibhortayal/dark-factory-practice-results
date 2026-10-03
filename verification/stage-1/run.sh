#!/usr/bin/env bash
# Stage-1 verifier runner. Usage: run.sh <full-revision> <evidence-dir> [probe sections...]
# Builds stage-1/ of the given revision from a clean git export (no cache), starts two
# containers under the spec limits on an internal (no-outbound) network, runs probe.py.
set -u
REV="$1"; EV="$2"; shift 2
ROOT=/home/ubuntu/nightshift-claude-tk-full
REPO=$ROOT/band-work/result
HERE=$ROOT/band-work/verifier/stage-1
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=tk-verify-s1:${REV:0:12}
NET=tk-verify-internal
mkdir -p "$EV"
SRC=$(mktemp -d /tmp/tk-verify-s1-XXXXXX)
git -C "$REPO" archive "$REV" stage-1 | tar -x -C "$SRC"
echo "== export of $REV at $SRC/stage-1"; ls -a "$SRC/stage-1"
echo "== D1.3 nested .git: $(find "$SRC/stage-1" -name .git | wc -l)"

echo "== D1.1 docker build --no-cache"
if docker build --no-cache -t "$IMG" "$SRC/stage-1" >"$EV/build.log" 2>&1; then echo "BUILD OK"; else echo "BUILD FAILED"; tail -30 "$EV/build.log"; exit 2; fi

docker rm -f tkv-a tkv-b tkv-c >/dev/null 2>&1
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null

wait_health() { # url -> seconds until 200, fails after 60 s
  local t0=$(date +%s.%N)
  for i in $(seq 1 600); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1/health")" = "200" ]; then
      echo "healthy after $(echo "$(date +%s.%N) - $t0" | bc) s"; return 0; fi
    sleep 0.1
    if [ "$(echo "$(date +%s.%N) - $t0 > 60" | bc)" = "1" ]; then echo "NOT healthy within 60 s"; return 1; fi
  done
}

echo "== D2.2/D3.1 container A: internal network, --cpus 2 --memory 2g, PORT=9000"
docker run -d --name tkv-a --network $NET --cpus 2 --memory 2g -e PORT=9000 "$IMG" >/dev/null
IPA=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tkv-a)
wait_health "http://$IPA:9000" || { docker logs tkv-a | tail -20; }

echo "== C1.1 container B: no PORT given (default 8080), internal network"
docker run -d --name tkv-b --network $NET --cpus 2 --memory 2g "$IMG" >/dev/null
IPB=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tkv-b)
wait_health "http://$IPB:8080" || { docker logs tkv-b | tail -20; }

echo "== D2.1 container C: default bridge, -e PORT=9123 -p 127.0.0.1:19123:9123"
docker run -d --name tkv-c --cpus 2 --memory 2g -e PORT=9123 -p 127.0.0.1:19123:9123 "$IMG" >/dev/null
wait_health "http://127.0.0.1:19123" || { docker logs tkv-c | tail -20; }
curl -s -i --max-time 5 http://127.0.0.1:19123/health | tr -d '\r' | head -12
docker rm -f tkv-c >/dev/null

echo "== outbound from container A (expected to fail: no route)"
docker exec tkv-a sh -c 'command -v python3 >/dev/null && python3 -c "
import socket
try:
    socket.create_connection((\"1.1.1.1\", 443), timeout=3); print(\"OUTBOUND REACHABLE\")
except Exception as e: print(\"no outbound:\", e)"' 2>&1 | tail -1

echo "== probes"
BASE="http://$IPA:9000" BASE2="http://$IPB:8080" OUT="$EV/probe-results.json" "$PY" "$HERE/probe.py" "$@" >"$EV/probe.log" 2>&1
echo "probe exit code: $?"
tail -60 "$EV/probe.log" | sed -n '/^TOTAL/,$p'

echo "== D3.3 container state after probes"
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' tkv-a tkv-b
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}} cpu={{.CPUPerc}}' tkv-a tkv-b
docker logs tkv-a >"$EV/container-a.log" 2>&1; docker logs tkv-b >"$EV/container-b.log" 2>&1
echo "traceback lines in container logs: $(grep -ci traceback "$EV/container-a.log" "$EV/container-b.log" | tr '\n' ' ')"
if [ "${KEEP:-0}" != "1" ]; then docker rm -f tkv-a tkv-b >/dev/null; fi
rm -rf "$SRC"
