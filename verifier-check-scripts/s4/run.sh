#!/usr/bin/env bash
# Stage-4 verifier run. Usage: run.sh <full-revision> <out-name> <phase>
# phases: start | p1 .. p15 | finish   (each list part ends with the universal assertions)
# Builds stage-4/ and the three earlier folders from a disposable clean clone, starts two stage-4 containers and one
# container of each accepted earlier stage under the stated limits on an internal (no outbound) network. Nothing is written into
# the repository.
set -u
REV="$1"; NAME="${2:-run}"; PHASE="${3:-start}"
ROOT=/home/ubuntu/nightshift-claude-run-5
REPO=$ROOT/band-work/result
HERE=$ROOT/band-work/verifier/s4
OUT=$ROOT/band-work/verifier/out4/$NAME
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=nsv-s4:$NAME; IMG1=nsv-s4-prev1:$NAME; IMG2=nsv-s4-prev2:$NAME; IMG3=nsv-s4-prev3:$NAME
NET=nsv-internal
STAGE1_ACCEPTED=43ecb3c9d24e89b47ea00c98828bf3999bb0a5cc
STAGE2_ACCEPTED=4a9c357bc8cc5c71df5634b15dd9527f145be2d5
STAGE3_ACCEPTED=532accd6430b55a8e3ebce7b02752bfbed4e641b
mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$OUT/run.log"; }
fail=0
check() { if [ "$1" = 0 ]; then log "PASS $2"; else log "FAIL $2"; fail=1; fi; }
wait_health() {
  local t0=$(date +%s.%N)
  for i in $(seq 1 $(( $2 * 5 ))); do
    if [ "$(curl -s -m 2 "$1/health" 2>/dev/null | tr -d ' \n')" = '{"status":"ok"}' ]; then
      python3 -c "print(round($(date +%s.%N) - $t0, 2))"; return 0; fi
    sleep 0.2
  done; echo "timeout"; return 1
}
ip_of() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
cleanup() { docker rm -f nsv4-a nsv4-b nsv4-prev nsv4-prev2 nsv4-prev3 nsv4-p1 nsv4-p2 >/dev/null 2>&1; }

if [ "$PHASE" = start ]; then
cleanup
log "L1 repository state"
cd "$REPO"
[ "$(git rev-parse HEAD)" = "$REV" ]; check $? "L1 HEAD is $REV"
[ -z "$(git status --porcelain)" ]; check $? "L1 working tree clean"
[ -f stage-4/Dockerfile ] && [ -f stage-4/RUN.md ]; check $? "M1 stage-4 Dockerfile and RUN.md present"
[ -z "$(find stage-4 stage-3 stage-2 stage-1 -name .git)" ]; check $? "L1 no nested .git"
[ -z "$(git diff --stat $STAGE1_ACCEPTED HEAD -- stage-1)" ]; check $? "L1 stage-1/ unchanged since the accepted revision"
[ -z "$(git diff --stat $STAGE2_ACCEPTED HEAD -- stage-2)" ]; check $? "L1 stage-2/ unchanged since the accepted revision"
[ -z "$(git diff --stat $STAGE3_ACCEPTED HEAD -- stage-3)" ]; check $? "M1 stage-3/ unchanged since the accepted revision"
git ls-files stage-4 | tee -a "$OUT/run.log"
CLONE=$(mktemp -d /tmp/nsv-s4-clone.XXXXXX)
git clone -q "$REPO" "$CLONE/result" && git -C "$CLONE/result" checkout -q "$REV"; check $? "L1 clone at revision"
( cd "$CLONE/result/stage-4" && docker build --no-cache -t "$IMG" . ) >"$OUT/build.log" 2>&1; check $? "M1 docker build --no-cache stage-4"
( cd "$CLONE/result/stage-3" && docker build -t "$IMG3" . ) >"$OUT/build-prev3.log" 2>&1; check $? "stage-3 image (upgrade source) built"
( cd "$CLONE/result/stage-1" && docker build -t "$IMG1" . ) >"$OUT/build-prev.log" 2>&1; check $? "stage-1 image (upgrade source) built"
( cd "$CLONE/result/stage-2" && docker build -t "$IMG2" . ) >"$OUT/build-prev2.log" 2>&1; check $? "stage-2 image (upgrade source) built"
tail -2 "$OUT/build.log" | tee -a "$OUT/run.log"
echo "$CLONE" > "$OUT/clone-path"
log "A2 PORT set / unset with a port mapping"
docker run -d --name nsv4-p1 --cpus 2 --memory 2g -e PORT=18990 -p 127.0.0.1:18990:18990 "$IMG" >/dev/null
t=$(wait_health http://127.0.0.1:18990 60); check $? "A2 PORT=18990 mapped, healthy after ${t}s"
docker run -d --name nsv4-p2 --cpus 2 --memory 2g -p 127.0.0.1:18991:8080 "$IMG" >/dev/null
t=$(wait_health http://127.0.0.1:18991 60); check $? "A2 PORT unset -> 8080, healthy after ${t}s"
docker rm -f nsv4-p1 nsv4-p2 >/dev/null
log "K3 containers on the internal network under the limits"
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
docker run -d --name nsv4-a --network $NET --cpus 2 --memory 2g -e PORT=8080 "$IMG" >/dev/null
A=http://$(ip_of nsv4-a):8080
t=$(wait_health "$A" 60); check $? "A4 first healthy response after ${t}s (limit 60)"
docker run -d --name nsv4-b --network $NET --cpus 2 --memory 2g -e PORT=9191 "$IMG" >/dev/null
B=http://$(ip_of nsv4-b):9191
t=$(wait_health "$B" 60); check $? "second stage-4 container healthy after ${t}s"
docker run -d --name nsv4-prev --network $NET --cpus 2 --memory 2g -e PORT=8080 "$IMG1" >/dev/null
P=http://$(ip_of nsv4-prev):8080
t=$(wait_health "$P" 60); check $? "stage-1 container healthy after ${t}s"
docker run -d --name nsv4-prev2 --network $NET --cpus 2 --memory 2g -e PORT=8080 "$IMG2" >/dev/null
P2=http://$(ip_of nsv4-prev2):8080
t=$(wait_health "$P2" 60); check $? "stage-2 container healthy after ${t}s"
docker run -d --name nsv4-prev3 --network $NET --cpus 2 --memory 2g -e PORT=8080 "$IMG3" >/dev/null
P3=http://$(ip_of nsv4-prev3):8080
t=$(wait_health "$P3" 60); check $? "stage-3 container healthy after ${t}s"
docker exec nsv4-a sh -c 'command -v python3 >/dev/null && python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(3)
try:
    s.connect((\"1.1.1.1\",80)); print(\"OUTBOUND REACHABLE\"); sys.exit(1)
except Exception as e: print(\"no outbound:\", e)
"' 2>&1 | tee -a "$OUT/run.log"
echo "$A" > "$OUT/base-a"; echo "$B" > "$OUT/base-b"; echo "$P" > "$OUT/base-prev"; echo "$P2" > "$OUT/base-prev2"; echo "$P3" > "$OUT/base-prev3"
fi
A=$(cat "$OUT/base-a" 2>/dev/null); B=$(cat "$OUT/base-b" 2>/dev/null); P=$(cat "$OUT/base-prev" 2>/dev/null); P2=$(cat "$OUT/base-prev2" 2>/dev/null); P3=$(cat "$OUT/base-prev3" 2>/dev/null)

for part in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
if [ "$PHASE" = "p$part" ]; then
cd "$HERE"
case $part in
 1) files="test_a_runtime.py test_b_invariants.py test_c_reset.py test_d_errors.py test_e_auth.py test_f_idem.py test_g_api.py test_h_split.py test_i_export.py test_j_settle.py test_zz_universal.py";;
 2) files="test_k_round1.py test_l_round2.py test_zz_universal.py";;
 3) files="test_m_round3.py test_zz_universal.py";;
 4) files="test_q_auth.py test_u_http.py test_zz_universal.py";;
 5) files="test_ui_auth.py test_ui_wallet.py test_ui_requests_split.py test_ui_authz.py test_zz_universal.py";;
 6) files="test_ui_quality.py test_ui_upgrade.py test_n_s2round1.py test_o_s2round2.py test_zz_universal.py";;
 7) files="test_r_time.py test_s_statement.py test_zz_universal.py";;
 8) files="test_t_corrections.py test_v_holds.py test_zz_universal.py";;
 9) files="test_w_model.py test_zz_universal.py";;
 10) files="test_x_upgrade3.py test_zz_universal.py";;
 11) files="test_y_robust.py test_zz_universal.py";;
 12) files="test_fa_refunds.py test_fb_batches.py test_zz_universal.py";;
 13) files="test_fc_model4.py test_zz_universal.py";;
 14) files="test_fd_upgrade4.py test_zz_universal.py";;
 15) files="test_fe_robust4.py test_ff_s4round1.py test_zz_universal.py";;
esac
mkdir -p "$OUT/p$part"; rm -f "$OUT/p$part"/*.jsonl; rm -rf "$OUT/p$part/shots"
log "own list part $part against $A, $B (stage 4), $P3 (stage 3), $P2 (stage 2) and $P (stage 1)"
BASE=$A BASE2=$B BASE1=$P BASEP2=$P2 BASEP3=$P3 VOUT=$OUT/p$part "$PY" -m pytest -p no:cacheprovider -q -rfEs --tb=short $files >"$OUT/pytest-$part.log" 2>&1
rc=$?; tail -3 "$OUT/pytest-$part.log" | tee -a "$OUT/run.log"; check $rc "own pytest list part $part"
fi
done

if [ "$PHASE" = finish ]; then
log "A5 container health after the list"
for c in nsv4-a nsv4-b nsv4-prev nsv4-prev2 nsv4-prev3; do
  docker inspect -f "$c running={{.State.Running}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}" $c | tee -a "$OUT/run.log"
  [ "$(docker inspect -f '{{.State.Running}}{{.State.OOMKilled}}{{.RestartCount}}' $c)" = "truefalse0" ]; check $? "A5 $c still running, not OOM-killed"
done
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}} cpu={{.CPUPerc}}' nsv4-a nsv4-b | tee -a "$OUT/run.log"
for c in nsv4-a nsv4-b nsv4-prev nsv4-prev2 nsv4-prev3; do docker logs $c >"$OUT/container-$c.log" 2>&1; grep -ciE 'traceback|internal error|unexpected' "$OUT/container-$c.log" | sed "s/^/log lines with traceback|internal error|unexpected in $c: /" | tee -a "$OUT/run.log"; done
log "A4 restart"
docker restart nsv4-a >/dev/null
A=http://$(ip_of nsv4-a):8080
t=$(wait_health "$A" 60); check $? "A4 healthy ${t}s after restart"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST -H 'Content-Type: application/json' \
  -d '{"currency":"EUR","minor_units":2,"users":[{"id":"u_a","email":"a@example.com","password":"correct horse","display_name":"A","handle":"a","balance":5}]}' "$A/_test/reset")
[ "$code" = 204 ]; check $? "A4 reset after restart -> $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -H 'Accept: text/html' "$A/")
[ "$code" = 200 ]; check $? "UI served after restart -> $code"
cleanup
fi
cd "$REPO"; [ -z "$(git status --porcelain)" ] && [ "$(git rev-parse HEAD)" = "$REV" ]; check $? "repository still clean at $REV"
log "run.sh $PHASE finished, fail=$fail"
exit $fail
