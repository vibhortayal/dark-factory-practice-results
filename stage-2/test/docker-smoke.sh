#!/usr/bin/env bash
# Builds the image, runs two containers with NO network, and moves state from A to B
# through export/import. Usage: bash test/docker-smoke.sh   (run from stage-1/)
set -euo pipefail
IMG=pocketful-stage-1:smoke
A=pf-smoke-a; B=pf-smoke-b
cleanup() { docker rm -f "$A" "$B" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker build -t "$IMG" .
# --network none: no published ports are possible, so talk to the containers by their bridge-less
# loopback through "docker exec" (wget is in alpine).
docker run -d --name "$A" --network none -e PORT=9001 "$IMG" >/dev/null
docker run -d --name "$B" --network none -e PORT=9002 "$IMG" >/dev/null
call() { # container port method path [json-body] [token] [key]
  local c=$1 p=$2 m=$3 path=$4 body=${5:-} tok=${6:-} key=${7:-}
  docker exec "$c" node -e '
    const [port,method,path,body,tok,key]=process.argv.slice(1);
    const h={"content-type":"application/json"}; if(tok)h.authorization="Bearer "+tok; if(key)h["idempotency-key"]=key;
    fetch(`http://127.0.0.1:${port}${path}`,{method,headers:h,body:method==="GET"?undefined:(body||undefined)})
      .then(async r=>{const t=await r.text();console.log(r.status+" "+t)});' "$p" "$m" "$path" "$body" "$tok" "$key"
}
for i in $(seq 1 50); do call "$A" 9001 GET /health 2>/dev/null | grep -q '^200' && break; sleep 0.2; done
call "$A" 9001 POST /_test/reset '{"currency":"EUR","minor_units":2,"users":[{"id":"u1","email":"a@x.io","password":"correct horse","display_name":"A","handle":"a","balance":1000},{"id":"u2","email":"b@x.io","password":"correct horse","display_name":"B","handle":"b","balance":0}]}' | grep -q '^204'
TOK=$(call "$A" 9001 POST /auth/login '{"email":"a@x.io","password":"correct horse"}' | sed 's/^200 //' | node -e 'process.stdin.on("data",d=>console.log(JSON.parse(d).token))')
R1=$(call "$A" 9001 POST /payments '{"to_handle":"b","amount":250}' "$TOK" smoke-key-1)
echo "A payment: $R1"; echo "$R1" | grep -q '^201'
EXPORT=$(call "$A" 9001 GET /_test/export | sed 's/^200 //')
echo "$EXPORT" | grep -q '"track":"pocketful"'
# state travels as a string argument through the test harness, not through a volume or the network
call "$B" 9002 POST /_test/import "$EXPORT" | grep -q '^204'
R2=$(call "$B" 9002 POST /payments '{"to_handle":"b","amount":250}' "$TOK" smoke-key-1)
echo "B replay: $R2"; echo "$R2" | grep -q '^200'
[ "${R1#201 }" = "${R2#200 }" ]
ME=$(call "$B" 9002 GET /me '' "$TOK"); echo "B /me: $ME"; echo "$ME" | grep -q '"balance":750'
echo "docker smoke OK"
