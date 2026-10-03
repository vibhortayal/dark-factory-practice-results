#!/usr/bin/env bash
# Stage-4 verifier runner. Usage: run4.sh <full-revision> <evidence-dir>
# Clean build of stage-4/ from a git export; two stage-4 containers plus the accepted stage-1
# (a8301bb) and stage-2 (0d321ce) containers under the spec limits on an internal network; then
# stage-1 list, stage-2 API list, stage-4 list, browser list (incl. upgrade from stage 1 and 2).
set -u
REV="$1"; EV="$2"
ROOT=/home/ubuntu/nightshift-claude-tk-full
REPO=$ROOT/band-work/result
V=$ROOT/band-work/verifier
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=tk-verify-s4:${REV:0:12}
S1IMG=tk-verify-s1:a8301bb93799; S2IMG=tk-verify-s2:0d321ce2763b; S3IMG=tk-verify-s3:fcdb0a2b3d42
NET=tk-verify-internal
mkdir -p "$EV/shots"
SRC=$(mktemp -d /tmp/tk-verify-s4-XXXXXX)
git -C "$REPO" archive "$REV" stage-4 | tar -x -C "$SRC"
echo "== export of $REV"; ls -a "$SRC/stage-4"
echo "== earlier folders unchanged: stage-1 vs a8301bb: $(git -C "$REPO" diff --stat a8301bb9379977851db1c64ff468cbddc30011ff "$REV" -- stage-1 | wc -l) lines; stage-2 vs 0d321ce: $(git -C "$REPO" diff --stat 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 "$REV" -- stage-2 | wc -l) lines; stage-3 vs fcdb0a2: $(git -C "$REPO" diff --stat fcdb0a2b3d4257c041607cdad6e77c91e2187e76 "$REV" -- stage-3 | wc -l) lines"
echo "== nested .git/__pycache__: $(find "$SRC/stage-4" -name .git -o -name __pycache__ | wc -l)"
echo "== external URLs in shipped files:"; grep -rnoE "(https?:)?//[a-zA-Z0-9.-]+\.[a-z]{2,}[^\"' )]*" "$SRC/stage-4" --include='*.html' --include='*.css' --include='*.js' --include='*.py' --include='*.svg' | grep -v "w3.org" | head
echo "== docker build --no-cache"
if docker build --no-cache -t "$IMG" "$SRC/stage-4" >"$EV/build.log" 2>&1; then echo "BUILD OK"; else echo "BUILD FAILED"; tail -30 "$EV/build.log"; exit 2; fi
for pair in "$S1IMG a8301bb9379977851db1c64ff468cbddc30011ff stage-1" "$S2IMG 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 stage-2" "$S3IMG fcdb0a2b3d4257c041607cdad6e77c91e2187e76 stage-3"; do set -- $pair
  docker image inspect $1 >/dev/null 2>&1 || { T=$(mktemp -d); git -C "$REPO" archive $2 $3 | tar -x -C "$T"; docker build -q -t $1 "$T/$3" >/dev/null; rm -rf "$T"; }; done
docker rm -f tkv4-a tkv4-b tkv4-s1 tkv4-s2 tkv4-s3 >/dev/null 2>&1
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
wait_health() { local t0=$(date +%s.%N); for i in $(seq 1 600); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1/health")" = "200" ]; then echo "healthy after $(echo "$(date +%s.%N) - $t0" | bc) s"; return 0; fi; sleep 0.1; done; echo "NOT healthy within 60 s"; return 1; }
ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
docker run -d --name tkv4-a --network $NET --cpus 2 --memory 2g -e PORT=9000 "$IMG" >/dev/null; A="http://$(ip tkv4-a):9000"; wait_health "$A" || docker logs tkv4-a | tail
docker run -d --name tkv4-b --network $NET --cpus 2 --memory 2g "$IMG" >/dev/null; B="http://$(ip tkv4-b):8080"; wait_health "$B" || docker logs tkv4-b | tail
docker run -d --name tkv4-s1 --network $NET --cpus 2 --memory 2g "$S1IMG" >/dev/null; S1="http://$(ip tkv4-s1):8080"; wait_health "$S1"
docker run -d --name tkv4-s2 --network $NET --cpus 2 --memory 2g "$S2IMG" >/dev/null; S2="http://$(ip tkv4-s2):8080"; wait_health "$S2"
docker run -d --name tkv4-s3 --network $NET --cpus 2 --memory 2g "$S3IMG" >/dev/null; S3="http://$(ip tkv4-s3):8080"; wait_health "$S3"
docker exec tkv4-a sh -c 'python3 -c "
import socket
try:
    socket.create_connection((\"1.1.1.1\", 443), timeout=3); print(\"OUTBOUND REACHABLE\")
except Exception as e: print(\"no outbound:\", e)"' 2>&1 | tail -1
t() { sed -n '/^TOTAL/,$p' "$1" | cut -c1-420; }
export STRIP_KEYS=revision
echo "== S0a stage-1 list on the stage-4 image (revision ignored in equality checks)"
BASE="$A" BASE2="$B" OUT="$EV/probe1-results.json" $PY "$V/stage-3/gen_probe1.py"; BASE="$A" BASE2="$B" OUT="$EV/probe1-results.json" $PY "$V/stage-3/probe1_on_stage3.py" >"$EV/probe1.log" 2>&1; echo "probe1 exit: $?"; t "$EV/probe1.log"
echo "== S0b stage-2 API list on the stage-4 image (upgrade source: stage-1 container)"
BASE="$A" BASE2="$B" S1BASE="$S1" OUT="$EV/probe2-results.json" $PY "$V/stage-2/probe2.py" >"$EV/probe2.log" 2>&1; echo "probe2 exit: $?"; t "$EV/probe2.log"
unset STRIP_KEYS
echo "== S0c stage-3 list on the stage-4 image"
STAGE4=1 BASE="$A" BASE2="$B" S1BASE="$S1" S2BASE="$S2" OUT="$EV/probe3-results.json" $PY "$V/stage-3/probe3.py" >"$EV/probe3.log" 2>&1; echo "probe3 exit: $?"; t "$EV/probe3.log"
echo "== P4 stage-4 list (oracle, apply, amend, upgrades, load)"
BASE="$A" BASE2="$B" S1BASE="$S1" S2BASE="$S2" S3BASE="$S3" OUT="$EV/probe4-results.json" $PY "$V/stage-4/probe4.py" >"$EV/probe4.log" 2>&1; echo "probe4 exit: $?"; t "$EV/probe4.log"
echo "== UI4 browser: screens reflect an applied plan"
BASE="$A" SHOTS="$EV/shots" $PY "$V/stage-4/ui4.py" >"$EV/ui4.log" 2>&1; echo "ui4 exit: $?"; t "$EV/ui4.log"
echo "== UI browser list (upgrade source: stage-1 container)"
BASE="$A" S1BASE="$S1" SHOTS="$EV/shots" OUT="$EV/ui-results.json" $PY "$V/stage-2/ui_probe.py" >"$EV/ui.log" 2>&1; echo "ui exit: $?"; t "$EV/ui.log"
for n in 2 3; do eval SRCU=\$S$n; echo "== UI upgrade section again with the stage-$n container as the source"
BASE="$A" S1BASE="$SRCU" SHOTS="$EV/shots" $PY "$V/stage-2/ui_probe.py" u_upgrade >"$EV/ui-upgrade-from-s$n.log" 2>&1; echo "ui upgrade s$n exit: $?"; t "$EV/ui-upgrade-from-s$n.log"; done
echo "== container state"
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}}' tkv4-a tkv4-b
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}}' tkv4-a tkv4-b
docker logs tkv4-a >"$EV/container-a.log" 2>&1; echo "stderr lines container A: $(wc -l < "$EV/container-a.log")"
if [ "${KEEP:-0}" != "1" ]; then docker rm -f tkv4-a tkv4-b tkv4-s1 tkv4-s2 tkv4-s3 >/dev/null; fi
rm -rf "$SRC"
