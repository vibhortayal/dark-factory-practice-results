#!/usr/bin/env bash
# Stage-2 verifier runner. Usage: run2.sh <full-revision> <evidence-dir>
# Builds stage-2/ of the revision from a clean git export, starts two stage-2 containers and one
# accepted stage-1 container (image tk-verify-s1:a8301bb93799, built from a8301bb) under the spec
# limits on an internal network, then runs: stage-1 list on stage 2, probe2.py, ui_probe.py.
set -u
REV="$1"; EV="$2"
ROOT=/home/ubuntu/nightshift-claude-tk-full
REPO=$ROOT/band-work/result
HERE=$ROOT/band-work/verifier/stage-2
PY=$ROOT/dark-factory-wearedevs/.venv/bin/python
IMG=tk-verify-s2:${REV:0:12}
S1IMG=tk-verify-s1:a8301bb93799
NET=tk-verify-internal
mkdir -p "$EV/shots"
SRC=$(mktemp -d /tmp/tk-verify-s2-XXXXXX)
git -C "$REPO" archive "$REV" stage-2 | tar -x -C "$SRC"
echo "== export of $REV"; ls -a "$SRC/stage-2"
echo "== D.4 stage-1 unchanged since a8301bb: $(git -C "$REPO" diff --stat a8301bb9379977851db1c64ff468cbddc30011ff "$REV" -- stage-1 | wc -l) changed lines of stat"
echo "== nested .git/__pycache__: $(find "$SRC/stage-2" -name .git -o -name __pycache__ | wc -l)"
echo "== D.3 external URLs in shipped files:"; grep -rnoE "(https?:)?//[a-zA-Z0-9.-]+\.[a-z]{2,}[^\"' )]*" "$SRC/stage-2" --include='*.html' --include='*.css' --include='*.js' --include='*.py' --include='*.svg' | grep -v "w3.org" | head -20
echo "== D.1 docker build --no-cache"
if docker build --no-cache -t "$IMG" "$SRC/stage-2" >"$EV/build.log" 2>&1; then echo "BUILD OK"; else echo "BUILD FAILED"; tail -30 "$EV/build.log"; exit 2; fi
docker image inspect $S1IMG >/dev/null 2>&1 || { S1SRC=$(mktemp -d); git -C "$REPO" archive a8301bb9379977851db1c64ff468cbddc30011ff stage-1 | tar -x -C "$S1SRC"; docker build -q -t $S1IMG "$S1SRC/stage-1" >/dev/null; rm -rf "$S1SRC"; }

docker rm -f tkv2-a tkv2-b tkv2-s1 >/dev/null 2>&1
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
wait_health() {
  local t0=$(date +%s.%N)
  for i in $(seq 1 600); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1/health")" = "200" ]; then echo "healthy after $(echo "$(date +%s.%N) - $t0" | bc) s"; return 0; fi
    sleep 0.1
  done; echo "NOT healthy within 60 s"; return 1
}
ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"; }
echo "== D.2 stage-2 container A (PORT=9000) and B (default port), stage-1 container"
docker run -d --name tkv2-a --network $NET --cpus 2 --memory 2g -e PORT=9000 "$IMG" >/dev/null; A="http://$(ip tkv2-a):9000"; wait_health "$A" || docker logs tkv2-a | tail
docker run -d --name tkv2-b --network $NET --cpus 2 --memory 2g "$IMG" >/dev/null; B="http://$(ip tkv2-b):8080"; wait_health "$B" || docker logs tkv2-b | tail
docker run -d --name tkv2-s1 --network $NET --cpus 2 --memory 2g "$S1IMG" >/dev/null; S1="http://$(ip tkv2-s1):8080"; wait_health "$S1"
docker exec tkv2-a sh -c 'python3 -c "
import socket
try:
    socket.create_connection((\"1.1.1.1\", 443), timeout=3); print(\"OUTBOUND REACHABLE\")
except Exception as e: print(\"no outbound:\", e)"' 2>&1 | tail -1

echo "== S0 stage-1 check list against the stage-2 image"
$PY - <<EOF
s = open("$ROOT/band-work/verifier/stage-1/probe.py").read()
helper = '''

def wt(d, tid):
    """Expected body after a table change: stage 2 adds table_ids next to table_id."""
    d2 = dict(d, table_id=tid)
    if isinstance(d, dict) and "table_ids" in d:
        d2["table_ids"] = [tid]
    return d2

'''
a = "# ---------------------------------------------------------------- sections"
assert a in s; s = s.replace(a, helper + a, 1)
for old, new in [('j == dict(r0, party_size=2, table_id="t_1")', 'j == wt(dict(r0, party_size=2), "t_1")'),
                 ('js[0] == dict(J(A), table_id="t_2") and js[1] == dict(J(B), table_id="t_1")', 'js[0] == wt(J(A), "t_2") and js[1] == wt(J(B), "t_1")')]:
    assert old in s, old; s = s.replace(old, new, 1)
open("$HERE/probe1_on_stage2.py", "w").write(s)
EOF
BASE="$A" BASE2="$B" OUT="$EV/probe1-results.json" $PY "$HERE/probe1_on_stage2.py" >"$EV/probe1.log" 2>&1; echo "probe1 exit: $?"; sed -n '/^TOTAL/,$p' "$EV/probe1.log" | cut -c1-400
echo "== P2 stage-2 API probes"
BASE="$A" BASE2="$B" S1BASE="$S1" OUT="$EV/probe2-results.json" $PY "$HERE/probe2.py" >"$EV/probe2.log" 2>&1; echo "probe2 exit: $?"; sed -n '/^TOTAL/,$p' "$EV/probe2.log" | cut -c1-400
echo "== UI browser probes"
BASE="$A" S1BASE="$S1" SHOTS="$EV/shots" OUT="$EV/ui-results.json" $PY "$HERE/ui_probe.py" >"$EV/ui.log" 2>&1; echo "ui exit: $?"; sed -n '/^TOTAL/,$p' "$EV/ui.log" | cut -c1-500
echo "== container state"
docker inspect -f '{{.Name}} running={{.State.Running}} oom={{.State.OOMKilled}}' tkv2-a tkv2-b
docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}}' tkv2-a tkv2-b
docker logs tkv2-a >"$EV/container-a.log" 2>&1; echo "stderr lines container A: $(wc -l < "$EV/container-a.log")"
if [ "${KEEP:-0}" != "1" ]; then docker rm -f tkv2-a tkv2-b tkv2-s1 >/dev/null; fi
rm -rf "$SRC"
