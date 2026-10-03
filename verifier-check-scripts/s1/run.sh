#!/usr/bin/env bash
# Stage-1 verifier run. Usage: run.sh <full-revision> <out-name>
# Builds stage-1/ from a disposable clean clone, starts two containers under the stated limits on an
# internal (no outbound) network, runs the delivery checks and the whole pytest list. Nothing is written
# into the repository under review.
set -u
REV="$1"; NAME="${2:-run}"; PHASE="${3:-all}"
ROOT=/home/ubuntu/nightshift-claude-run-5
REPO=$ROOT/band-work/result
HERE=$ROOT/band-work/verifier/s1
OUT=$ROOT/band-work/verifier/out/$NAME
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=nsv-s1:$NAME
NET=nsv-internal
mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$OUT/run.log"; }
fail=0
check() { if [ "$1" = 0 ]; then log "PASS $2"; else log "FAIL $2"; fail=1; fi; }
wait_health() { # url, seconds -> prints seconds to first 200 {"status":"ok"}
  local t0=$(date +%s.%N)
  for i in $(seq 1 $(( $2 * 5 ))); do
    if [ "$(curl -s -m 2 "$1/health" 2>/dev/null | tr -d ' \n')" = '{"status":"ok"}' ]; then
      python3 -c "print(round($(date +%s.%N) - $t0, 2))"; return 0; fi
    sleep 0.2
  done; echo "timeout"; return 1
}
ip_of() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
cleanup() { docker rm -f nsv-a nsv-b nsv-p1 nsv-p2 nsv-runmd >/dev/null 2>&1; }
if [ "$PHASE" = start ] || [ "$PHASE" = all ]; then
cleanup
rm -f "$OUT"/violations.jsonl "$OUT"/notes.jsonl

log "A1.1 repository state"
cd "$REPO"
[ "$(git rev-parse HEAD)" = "$REV" ]; check $? "A1.1 HEAD is $REV"
[ -z "$(git status --porcelain)" ]; check $? "A1.1 working tree clean"
[ -f stage-1/Dockerfile ] && [ -f stage-1/RUN.md ]; check $? "A1.1 Dockerfile and RUN.md present"
[ -z "$(find stage-1 -name .git)" ]; check $? "A1.1 no nested .git"
git ls-files stage-1 | tee -a "$OUT/run.log"

log "A1.2 clean clone and build without cache"
CLONE=$(mktemp -d /tmp/nsv-s1-clone.XXXXXX)
git clone -q "$REPO" "$CLONE/result" && git -C "$CLONE/result" checkout -q "$REV"; check $? "A1.2 clone at revision"
( cd "$CLONE/result/stage-1" && docker build --no-cache -t "$IMG" . ) >"$OUT/build.log" 2>&1; check $? "A1.2 docker build --no-cache"
tail -3 "$OUT/build.log" | tee -a "$OUT/run.log"
echo "$CLONE" > "$OUT/clone-path"

log "A2 PORT set / unset with a port mapping"
docker run -d --name nsv-p1 --cpus 2 --memory 2g -e PORT=18990 -p 127.0.0.1:18990:18990 "$IMG" >/dev/null
t=$(wait_health http://127.0.0.1:18990 60); check $? "A2.1 PORT=18990 mapped, healthy after ${t}s"
docker run -d --name nsv-p2 --cpus 2 --memory 2g -p 127.0.0.1:18991:8080 "$IMG" >/dev/null
t=$(wait_health http://127.0.0.1:18991 60); check $? "A2.2 PORT unset -> 8080, healthy after ${t}s"
docker rm -f nsv-p1 nsv-p2 >/dev/null

log "A3/A4 two containers on the internal network under the limits"
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
docker run -d --name nsv-a --network $NET --cpus 2 --memory 2g -e PORT=8080 "$IMG" >/dev/null
A=http://$(ip_of nsv-a):8080
t=$(wait_health "$A" 60); check $? "A4.1 first healthy response after ${t}s (limit 60)"
docker run -d --name nsv-b --network $NET --cpus 2 --memory 2g -e PORT=9191 "$IMG" >/dev/null
B=http://$(ip_of nsv-b):9191
t=$(wait_health "$B" 60); check $? "second container healthy after ${t}s"
docker exec nsv-a sh -c 'command -v python3 >/dev/null && python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(3)
try:
    s.connect((\"1.1.1.1\",80)); print(\"OUTBOUND REACHABLE\"); sys.exit(1)
except Exception as e: print(\"no outbound:\", e)
"' 2>&1 | tee -a "$OUT/run.log"

echo "$A" > "$OUT/base-a"; echo "$B" > "$OUT/base-b"
fi
A=$(cat "$OUT/base-a"); B=$(cat "$OUT/base-b")

if [ "$PHASE" = pytest ] || [ "$PHASE" = all ]; then
log "own list (pytest) against $A and $B"
cd "$HERE"
BASE=$A BASE2=$B VOUT=$OUT "$PY" -m pytest -p no:cacheprovider -q -rfEs --tb=short . >"$OUT/pytest.log" 2>&1
rc=$?; tail -5 "$OUT/pytest.log" | tee -a "$OUT/run.log"; check $rc "own pytest list"

fi
# the list in two halves (each ends with the universal assertions), for runs longer than one command may take
for part in 1 2; do
if [ "$PHASE" = "pytest$part" ]; then
cd "$HERE"
if [ $part = 1 ]; then files="test_a_runtime.py test_b_invariants.py test_c_reset.py test_d_errors.py test_e_auth.py test_f_idem.py test_g_api.py test_h_split.py test_i_export.py test_j_settle.py test_zz_universal.py"
else files="test_k_round1.py test_l_round2.py test_m_round3.py test_zz_universal.py"; fi
mkdir -p "$OUT/p$part"; rm -f "$OUT/p$part"/*.jsonl
log "own list part $part against $A and $B"
BASE=$A BASE2=$B VOUT=$OUT/p$part "$PY" -m pytest -p no:cacheprovider -q -rfEs --tb=short $files >"$OUT/pytest-$part.log" 2>&1
rc=$?; tail -3 "$OUT/pytest-$part.log" | tee -a "$OUT/run.log"; check $rc "own pytest list part $part"
fi
done

if [ "$PHASE" = finish ] || [ "$PHASE" = all ]; then
log "A5.1 container health after the list"
for c in nsv-a nsv-b; do
  docker inspect -f "$c running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}" $c | tee -a "$OUT/run.log"
  [ "$(docker inspect -f '{{.State.Running}}{{.State.OOMKilled}}{{.RestartCount}}' $c)" = "truefalse0" ]; check $? "A5.1 $c still running, not OOM-killed"
done
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}} cpu={{.CPUPerc}}' nsv-a nsv-b | tee -a "$OUT/run.log"
docker logs nsv-a 2>&1 | grep -ciE 'traceback|internal error|exception' | sed 's/^/log lines with traceback|internal error|exception in nsv-a: /' | tee -a "$OUT/run.log"

log "A4.2 restart"
docker restart nsv-a >/dev/null
A=http://$(ip_of nsv-a):8080
t=$(wait_health "$A" 60); check $? "A4.2 healthy ${t}s after restart"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST -H 'Content-Type: application/json' \
  -d '{"currency":"EUR","minor_units":2,"users":[{"id":"u_a","email":"a@example.com","password":"correct horse","display_name":"A","handle":"a","balance":5}]}' "$A/_test/reset")
[ "$code" = 204 ]; check $? "A4.2 reset after restart -> $code"

cleanup
fi
cd "$REPO"; [ -z "$(git status --porcelain)" ] && [ "$(git rev-parse HEAD)" = "$REV" ]; check $? "repository still clean at $REV"
log "run.sh finished, fail=$fail"
exit $fail
