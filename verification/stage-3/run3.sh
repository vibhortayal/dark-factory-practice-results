#!/usr/bin/env bash
# Stage-3 verifier runner. Usage: run3.sh <full-revision> <evidence-dir>
# Clean build of stage-3/ from a git export; two stage-3 containers plus the accepted stage-1
# (a8301bb) and stage-2 (0d321ce) containers under the spec limits on an internal network; then
# stage-1 list, stage-2 API list, stage-3 list, browser list (incl. upgrade from stage 1 and 2).
set -u
REV="$1"; EV="$2"
ROOT=/home/ubuntu/nightshift-claude-tk-full
REPO=$ROOT/band-work/result
V=$ROOT/band-work/verifier
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=tk-verify-s3:${REV:0:12}
S1IMG=tk-verify-s1:a8301bb93799; S2IMG=tk-verify-s2:0d321ce2763b
NET=tk-verify-internal
mkdir -p "$EV/shots"
SRC=$(mktemp -d /tmp/tk-verify-s3-XXXXXX)
git -C "$REPO" archive "$REV" stage-3 | tar -x -C "$SRC"
echo "== export of $REV"; ls -a "$SRC/stage-3"
echo "== earlier folders unchanged: stage-1 vs a8301bb: $(git -C "$REPO" diff --stat a8301bb9379977851db1c64ff468cbddc30011ff "$REV" -- stage-1 | wc -l) lines; stage-2 vs 0d321ce: $(git -C "$REPO" diff --stat 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 "$REV" -- stage-2 | wc -l) lines"
echo "== nested .git/__pycache__: $(find "$SRC/stage-3" -name .git -o -name __pycache__ | wc -l)"
echo "== external URLs in shipped files:"; grep -rnoE "(https?:)?//[a-zA-Z0-9.-]+\.[a-z]{2,}[^\"' )]*" "$SRC/stage-3" --include='*.html' --include='*.css' --include='*.js' --include='*.py' --include='*.svg' | grep -v "w3.org" | head
echo "== stage-4 words in source:"; grep -rnoiE "replan|closure|reassigned|restaurant_revision|/amend" "$SRC/stage-3/app" | cut -c1-120 | head -12
echo "== docker build --no-cache"
if docker build --no-cache -t "$IMG" "$SRC/stage-3" >"$EV/build.log" 2>&1; then echo "BUILD OK"; else echo "BUILD FAILED"; tail -30 "$EV/build.log"; exit 2; fi
for pair in "$S1IMG a8301bb9379977851db1c64ff468cbddc30011ff stage-1" "$S2IMG 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 stage-2"; do set -- $pair
  docker image inspect $1 >/dev/null 2>&1 || { T=$(mktemp -d); git -C "$REPO" archive $2 $3 | tar -x -C "$T"; docker build -q -t $1 "$T/$3" >/dev/null; rm -rf "$T"; }; done
docker rm -f tkv3-a tkv3-b tkv3-s1 tkv3-s2 >/dev/null 2>&1
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
wait_health() { local t0=$(date +%s.%N); for i in $(seq 1 600); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1/health")" = "200" ]; then echo "healthy after $(echo "$(date +%s.%N) - $t0" | bc) s"; return 0; fi; sleep 0.1; done; echo "NOT healthy within 60 s"; return 1; }
ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
docker run -d --name tkv3-a --network $NET --cpus 2 --memory 2g -e PORT=9000 "$IMG" >/dev/null; A="http://$(ip tkv3-a):9000"; wait_health "$A" || docker logs tkv3-a | tail
docker run -d --name tkv3-b --network $NET --cpus 2 --memory 2g "$IMG" >/dev/null; B="http://$(ip tkv3-b):8080"; wait_health "$B" || docker logs tkv3-b | tail
docker run -d --name tkv3-s1 --network $NET --cpus 2 --memory 2g "$S1IMG" >/dev/null; S1="http://$(ip tkv3-s1):8080"; wait_health "$S1"
docker run -d --name tkv3-s2 --network $NET --cpus 2 --memory 2g "$S2IMG" >/dev/null; S2="http://$(ip tkv3-s2):8080"; wait_health "$S2"
docker exec tkv3-a sh -c 'python3 -c "
import socket
try:
    socket.create_connection((\"1.1.1.1\", 443), timeout=3); print(\"OUTBOUND REACHABLE\")
except Exception as e: print(\"no outbound:\", e)"' 2>&1 | tail -1
t() { sed -n '/^TOTAL/,$p' "$1" | cut -c1-420; }
export STRIP_KEYS=revision
echo "== S0a stage-1 list on the stage-3 image (revision ignored in equality checks)"
BASE="$A" BASE2="$B" OUT="$EV/probe1-results.json" $PY "$V/stage-3/gen_probe1.py"; BASE="$A" BASE2="$B" OUT="$EV/probe1-results.json" $PY "$V/stage-3/probe1_on_stage3.py" >"$EV/probe1.log" 2>&1; echo "probe1 exit: $?"; t "$EV/probe1.log"
echo "== S0b stage-2 API list on the stage-3 image (upgrade source: stage-1 container)"
BASE="$A" BASE2="$B" S1BASE="$S1" OUT="$EV/probe2-results.json" $PY "$V/stage-2/probe2.py" >"$EV/probe2.log" 2>&1; echo "probe2 exit: $?"; t "$EV/probe2.log"
unset STRIP_KEYS
echo "== P3 stage-3 list"
BASE="$A" BASE2="$B" S1BASE="$S1" S2BASE="$S2" OUT="$EV/probe3-results.json" $PY "$V/stage-3/probe3.py" >"$EV/probe3.log" 2>&1; echo "probe3 exit: $?"; t "$EV/probe3.log"
echo "== UI browser list (upgrade source: stage-1 container)"
BASE="$A" S1BASE="$S1" SHOTS="$EV/shots" OUT="$EV/ui-results.json" $PY "$V/stage-2/ui_probe.py" >"$EV/ui.log" 2>&1; echo "ui exit: $?"; t "$EV/ui.log"
echo "== UI upgrade section again with the stage-2 container as the source"
BASE="$A" S1BASE="$S2" SHOTS="$EV/shots" $PY "$V/stage-2/ui_probe.py" u_upgrade >"$EV/ui-upgrade-from-s2.log" 2>&1; echo "ui upgrade s2 exit: $?"; t "$EV/ui-upgrade-from-s2.log"
echo "== container state"
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}}' tkv3-a tkv3-b
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}}' tkv3-a tkv3-b
docker logs tkv3-a >"$EV/container-a.log" 2>&1; echo "stderr lines container A: $(wc -l < "$EV/container-a.log")"
if [ "${KEEP:-0}" != "1" ]; then docker rm -f tkv3-a tkv3-b tkv3-s1 tkv3-s2 >/dev/null; fi
rm -rf "$SRC"
