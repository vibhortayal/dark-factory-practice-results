#!/usr/bin/env bash
# Verifier stage-1 run. Usage: run_all.sh <full-revision> <out-dir (new, outside the repository)>
# Builds from a clean clone of the revision, starts containers under the §2 limits, runs every check.
set -u
REV="$1"; OUT="$2"
ROOT=/home/ubuntu/nightshift-claude-check-tk1
REPO=$ROOT/band-work/result
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG=tk-ver-stage1:${REV:0:12}
mkdir -p "$OUT" || exit 2
exec > >(tee "$OUT/run_all.log") 2>&1
echo "== revision $REV  $(date -u +%FT%TZ)"
docker rm -f tkver-a tkver-b tkver-c tkver-d >/dev/null 2>&1
docker network rm tkver-internal >/dev/null 2>&1

echo "== [A1] clean clone and build without cache"
CL="$OUT/clone"; git clone -q "$REPO" "$CL" && git -C "$CL" checkout -q "$REV" || { echo "CLONE FAILED"; exit 2; }
git -C "$CL" rev-parse HEAD
ls -la "$CL/stage-1"; find "$CL/stage-1" -name .git | sed 's/^/NESTED GIT: /'
T0=$(date +%s); docker build --no-cache -q -t "$IMG" "$CL/stage-1" || { echo "BUILD FAILED"; exit 2; }
echo "build seconds: $(( $(date +%s) - T0 ))"

wait_health() { # name url -> prints seconds to first 200 {"status":"ok"}
  local t0=$(date +%s.%N)
  for i in $(seq 1 600); do
    if [ "$(curl -s -m 2 "$2/health" 2>/dev/null | tr -d ' \n')" = '{"status":"ok"}' ]; then
      echo "$1 healthy after $(echo "$(date +%s.%N) - $t0" | bc) s"; return 0; fi
    sleep 0.1
  done; echo "$1 NOT HEALTHY within 60 s"; return 1
}

echo "== [A3 A5 A6 B1] container A: PORT=9321 with port mapping, 2 CPU / 2g"
docker run -d --rm --name tkver-a --cpus 2 --memory 2g -e PORT=9321 -p 127.0.0.1:18431:9321 "$IMG" >/dev/null
wait_health A http://127.0.0.1:18431 || exit 2
echo "== [B1] container B: no PORT variable -> default 8080"
docker run -d --rm --name tkver-b --cpus 2 --memory 2g -p 127.0.0.1:18432:8080 "$IMG" >/dev/null
wait_health B http://127.0.0.1:18432 || exit 2
echo "== [B1] 0.0.0.0: reachable on the container's own address, not only loopback"
IPA=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tkver-a)
curl -s -m 3 -o /dev/null -w "A via $IPA:9321 -> %{http_code}\n" "http://$IPA:9321/health"

echo "== full check list against A (port-mapped, limits), B as second container"
TK_BASE=http://127.0.0.1:18431 TK_BASE2=http://127.0.0.1:18432 TK_OUT="$OUT/run-mapped" $PY "$HERE/run_checks.py"; echo "exit: $?"
docker stats --no-stream --format '{{.Name}} mem {{.MemUsage}} cpu {{.CPUPerc}}' tkver-a tkver-b
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' tkver-a tkver-b

echo "== [A3 A4] container C on an internal network (no outbound route), limits; full check list again"
docker network create --internal tkver-internal >/dev/null
docker run -d --rm --name tkver-c --network tkver-internal --cpus 2 --memory 2g -e PORT=8080 "$IMG" >/dev/null
docker run -d --rm --name tkver-d --network tkver-internal --cpus 2 --memory 2g -e PORT=8080 "$IMG" >/dev/null
IPC=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tkver-c)
IPD=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tkver-d)
wait_health C "http://$IPC:8080" || exit 2
wait_health D "http://$IPD:8080" || exit 2
TK_BASE="http://$IPC:8080" TK_BASE2="http://$IPD:8080" TK_OUT="$OUT/run-internal" $PY "$HERE/run_checks.py"; echo "exit: $?"
docker stats --no-stream --format '{{.Name}} mem {{.MemUsage}} cpu {{.CPUPerc}}' tkver-c tkver-d
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' tkver-c tkver-d
for c in tkver-a tkver-b tkver-c tkver-d; do docker logs "$c" > "$OUT/$c.log" 2>&1; done
docker stop -t 2 tkver-a tkver-b tkver-c tkver-d >/dev/null 2>&1
docker network rm tkver-internal >/dev/null 2>&1
echo "== done $(date -u +%FT%TZ); containers left: $(docker ps -q --filter name=tkver- | wc -l)"
