#!/usr/bin/env bash
# Upgrade proof with two REAL containers and no network: state is exported from the accepted stage-1 or
# stage-2 or stage-3 image and imported into this stage-4 image.
# Usage (from stage-4/): bash test/docker-upgrade.sh [1|2|3]     (default: all three)
set -euo pipefail
NEW=pocketful-stage-4:upgrade
A=pf4-up-old; B=pf4-up-new
cleanup() { docker rm -f "$A" "$B" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker build -q -t "$NEW" . >/dev/null
call() { # container port method path [json-body] [token] [key]
  local c=$1 p=$2 m=$3 path=$4 body=${5:-} tok=${6:-} key=${7:-}
  docker exec "$c" node -e '
    const [port,method,path,body,tok,key]=process.argv.slice(1);
    const h={"content-type":"application/json"}; if(tok)h.authorization="Bearer "+tok; if(key)h["idempotency-key"]=key;
    fetch(`http://127.0.0.1:${port}${path}`,{method,headers:h,body:method==="GET"?undefined:(body||undefined)})
      .then(async r=>{const t=await r.text();console.log(r.status+" "+t)});' "$p" "$m" "$path" "$body" "$tok" "$key"
}
jf() { node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s.replace(/^\d+ /,""))[process.argv[1]]))' "$1"; }
one() {
  local stage=$1 old=pocketful-stage-$1:upgrade-src
  cleanup
  docker build -q -t "$old" "../stage-$stage" >/dev/null
  docker run -d --name "$A" --network none -e PORT=9001 "$old" >/dev/null
  docker run -d --name "$B" --network none -e PORT=9002 "$NEW" >/dev/null
  for i in $(seq 1 50); do call "$A" 9001 GET /health 2>/dev/null | grep -q '^200' && call "$B" 9002 GET /health 2>/dev/null | grep -q '^200' && break; sleep 0.2; done
  local FX='{"currency":"EUR","minor_units":2,"settlement_operator_ids":["u2"],"users":[{"id":"u1","email":"a@x.io","password":"correct horse","display_name":"A","handle":"a","balance":10000},{"id":"u2","email":"b@x.io","password":"correct horse","display_name":"B","handle":"b","balance":0}]}'
  call "$A" 9001 POST /_test/reset "$FX" | grep -q '^204'
  local TOK OP R1 R2 PID EXPORT
  TOK=$(call "$A" 9001 POST /auth/login '{"email":"a@x.io","password":"correct horse"}' | jf token)
  OP=$(call "$A" 9001 POST /auth/login '{"email":"b@x.io","password":"correct horse"}' | jf token)
  R1=$(call "$A" 9001 POST /payments '{"to_handle":"b","amount":250}' "$TOK" up-key-1); echo "stage-$stage payment: $R1"; echo "$R1" | grep -q '^201'
  PID=$(echo "$R1" | jf payment_id)
  if [ "$stage" = 2 ]; then call "$A" 9001 POST /authorizations '{"to_handle":"b","amount":100}' "$TOK" up-key-h | grep -q '^201'; fi
  EXPORT=$(call "$A" 9001 GET /_test/export | sed 's/^200 //')
  echo "$EXPORT" | grep -q "\"schema_version\":$stage"
  call "$B" 9002 POST /_test/import "$EXPORT" | grep -q '^204'
  R2=$(call "$B" 9002 POST /payments '{"to_handle":"b","amount":250}' "$TOK" up-key-1); echo "stage-3 replay: $R2"
  echo "$R2" | grep -q '^200'; [ "${R1#201 }" = "${R2#200 }" ]
  local ME; ME=$(call "$B" 9002 GET /me '' "$TOK"); echo "stage-3 /me: $ME"; echo "$ME" | grep -q '"balance":9750'
  local OPENING; OPENING=$(call "$B" 9002 GET '/me?as_of=2000-01-01T00:00:00Z' '' "$TOK"); echo "stage-3 opening: $OPENING"; echo "$OPENING" | grep -q '"balance":10000'
  call "$B" 9002 GET /statement '' "$TOK" | grep -q '"closing_balance":9750'
  local C; C=$(call "$B" 9002 POST "/payments/$PID/corrections" '{"expected_revision":1,"amount":200,"effective_at":"2026-01-01T00:00:00Z","reason":"upgrade"}' "$TOK" up-key-c); echo "correction: $C"; echo "$C" | grep -q '^201'
  call "$B" 9002 GET /me '' "$TOK" | grep -q '"balance":9800'
  local RF; RF=$(call "$B" 9002 POST "/payments/$PID/refunds" '{"amount":100}' "$OP" up-key-r); echo "refund: $RF"; echo "$RF" | grep -q '^201.*"refund_of":"'"$PID"'"'
  echo "docker upgrade from stage $stage OK"
}
if [ "${1:-}" ]; then one "$1"; else one 1; one 2; one 3; fi
