#!/usr/bin/env bash
# Compare the apps built by Run 2, Run 3 and Run 5 on the demo VM.
# Run on the VM as user ubuntu:   bash compare.sh <hostname> [checks|sites|all]
# Example hostname: 64-181-239-158.sslip.io
#
#   checks  Run 5's stage-1 check list (API only, no browser) against each run's stage-1 app.
#           One run at a time, sealed network, results in ~/compare/results/.
#   sites   Put each run's stage-4 app at its own address: run2-<hostname>, run3-<hostname>,
#           run5-<hostname>. The existing <hostname> site is left as it is.
#   all     checks, then sites (default).
#
# Needs: Docker, and read access to the private archive repository through deploy key B at
# ~/.ssh/nightshift-archive-read. No app code is modified. No timing is compared: this VM has
# one processor, the specification assumes two per app.
set -euo pipefail

SITE="${1:?usage: compare.sh <hostname> [checks|sites|all]}"
PHASE="${2:-all}"
WORK="$HOME/compare"
REPO="git@github.com:vibhortayal/dark-factory-practice-results.git"
KEY="${KEY:-$HOME/.ssh/nightshift-archive-read}"
NET=demo-internal
CHECKS_BRANCH=nightshift-run-5-verifier-checks
# Override to compare other runs, e.g. RUNS="run6:nightshift-run-6-2026-10-02" bash compare.sh <hostname> checks
RUNS="${RUNS:-run2:nightshift-run-2-2026-09-30 run3:nightshift-run-3-2026-09-30 run5:nightshift-run-5-2026-10-02}"

export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

fetch() { # name branch
  rm -rf "$WORK/src/$1"
  git clone -q --depth 1 --branch "$2" "$REPO" "$WORK/src/$1"
  echo "  $1: $(git -C "$WORK/src/$1" rev-parse --short HEAD) from $2"
}

wait_health() { # host port -> 0 when /health answers 200 within 60 s
  docker run --rm --network "$NET" python:3.12-slim python -c "
import sys, time, urllib.request
url = 'http://%s:%s/health' % (sys.argv[1], sys.argv[2])
for _ in range(120):
    try:
        if urllib.request.urlopen(url, timeout=2).status == 200:
            sys.exit(0)
    except Exception:
        pass
    time.sleep(0.5)
sys.exit(1)
" "$1" "$2"
}

# write a file in place, so a container that has it mounted sees the change
write_in_place() { cat "$1" > "$2"; rm -f "$1"; }

mkdir -p "$WORK/src" "$WORK/results"
test -f "$KEY" || { echo "deploy key B not found at $KEY"; exit 1; }
docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET" >/dev/null

if [ "$PHASE" != undo ]; then
  echo "== fetch the three runs and the check scripts"
  docker pull -q python:3.12-slim >/dev/null
  for r in $RUNS; do fetch "${r%%:*}" "${r##*:}"; done
  fetch checks "$CHECKS_BRANCH"
fi

if [ "$PHASE" = checks ] || [ "$PHASE" = all ]; then
  echo "== build the check runner (python, pytest, httpx; no browser)"
  cat > "$WORK/Dockerfile.checker" <<'EOF'
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1 httpx==0.28.1
WORKDIR /checks
COPY s1/ /checks/
EOF
  docker build -q -t cmp-checker -f "$WORK/Dockerfile.checker" "$WORK/src/checks" >/dev/null

  for r in $RUNS; do
    name="${r%%:*}"
    echo "== $name: stage-1 app against Run 5's stage-1 check list"
    out="$WORK/results/$name"; rm -rf "$out"; mkdir -p "$out"
    docker rm -f cmp-a cmp-b >/dev/null 2>&1 || true
    if ! docker build -q -t "cmp-$name-s1" "$WORK/src/$name/stage-1" >"$out/build.log" 2>&1; then
      echo "  build failed, see $out/build.log"; continue
    fi
    docker run -d --name cmp-a --network "$NET" --memory 1g --pids-limit 256 --cap-drop ALL \
      --security-opt no-new-privileges -e PORT=8080 "cmp-$name-s1" >/dev/null
    docker run -d --name cmp-b --network "$NET" --memory 1g --pids-limit 256 --cap-drop ALL \
      --security-opt no-new-privileges -e PORT=9191 "cmp-$name-s1" >/dev/null
    if ! wait_health cmp-a 8080 || ! wait_health cmp-b 9191; then
      echo "  app did not become healthy"; docker logs cmp-a >"$out/app-a.log" 2>&1 || true
      docker rm -f cmp-a cmp-b >/dev/null 2>&1 || true; continue
    fi
    # The runner sits on the same sealed network. --timeout guards one stuck request; the
    # whole list is cut off after 40 minutes so one bad app cannot hold up the others.
    timeout 2400 docker run --rm --name cmp-run --network "$NET" --memory 1g \
      -e BASE=http://cmp-a:8080 -e BASE2=http://cmp-b:9191 -e VOUT=/out -v "$out:/out" \
      cmp-checker python -m pytest -p no:cacheprovider -q -rfEs --tb=line \
      --junitxml=/out/junit.xml . >"$out/pytest.log" 2>&1 || true
    docker logs cmp-a >"$out/app-a.log" 2>&1 || true
    docker rm -f cmp-a cmp-b cmp-run >/dev/null 2>&1 || true
    echo "  $(tail -1 "$out/pytest.log")"
  done

  echo "== summary"
  for r in $RUNS; do
    name="${r%%:*}"; f="$WORK/results/$name/pytest.log"
    printf '%-6s %s\n' "$name" "$( [ -f "$f" ] && tail -1 "$f" || echo 'no result' )"
  done | tee "$WORK/results/summary.txt"
  tar czf "$WORK/results.tar.gz" -C "$WORK" results
  echo "results: $WORK/results/ and $WORK/results.tar.gz"
fi

if [ "$PHASE" = sites ] || [ "$PHASE" = all ]; then
  echo "== one address per run (stage-4 app, sealed, test-only addresses blocked)"
  CADDY="$HOME/demo/Caddyfile"
  test -f "$CADDY" || { echo "no existing Caddyfile at $CADDY; run deploy.sh first"; exit 1; }
  cp "$CADDY" "$CADDY.before-compare"
  # keep everything that is already there, drop any earlier compare block, then add ours
  NEW="$WORK/Caddyfile.new"
  sed '/^# compare:begin$/,/^# compare:end$/d' "$CADDY" > "$NEW"
  echo "# compare:begin" >> "$NEW"
  for r in $RUNS; do
    name="${r%%:*}"
    docker build -q -t "cmp-$name-s4" "$WORK/src/$name/stage-4" >/dev/null
    docker rm -f "cmp-$name" >/dev/null 2>&1 || true
    docker run -d --name "cmp-$name" --network "$NET" --restart unless-stopped --memory 512m \
      --pids-limit 256 --cap-drop ALL --security-opt no-new-privileges -e PORT=8080 "cmp-$name-s4" >/dev/null
    if ! wait_health "cmp-$name" 8080; then echo "  $name: stage-4 app did not become healthy"; fi
    cat >> "$NEW" <<EOF
$name-$SITE {
	@testonly path /_test/*
	respond @testonly 404
	reverse_proxy cmp-$name:8080
}
EOF
    echo "  https://$name-$SITE/"
  done
  echo "# compare:end" >> "$NEW"
  write_in_place "$NEW" "$CADDY"
  docker exec caddy-demo caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || docker restart caddy-demo >/dev/null
  sleep 5
  docker ps --format '{{.Names}}  {{.Status}}' | grep -E 'cmp-|caddy|pocketful' || true
  echo "certificates can take a minute. To undo: bash compare.sh $SITE undo"
fi

if [ "$PHASE" = undo ]; then
  for r in $RUNS; do docker rm -f "cmp-${r%%:*}" >/dev/null 2>&1 || true; done
  sed '/^# compare:begin$/,/^# compare:end$/d' "$HOME/demo/Caddyfile" > "$WORK/Caddyfile.new"
  write_in_place "$WORK/Caddyfile.new" "$HOME/demo/Caddyfile"
  docker exec caddy-demo caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 || docker restart caddy-demo >/dev/null
  echo "compare sites removed; the original site is unchanged"
fi
