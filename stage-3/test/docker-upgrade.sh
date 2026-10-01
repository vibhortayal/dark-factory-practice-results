#!/usr/bin/env bash
# Upgrade proof with two REAL containers and no network: state is exported from the accepted
# stage-1 image and imported into this stage-2 image. Usage (from stage-2/): bash test/docker-upgrade.sh
set -euo pipefail
S1=pocketful-stage-1:upgrade-src; S2=pocketful-stage-2:upgrade
A=pf2-up-old; B=pf2-up-new
cleanup() { docker rm -f "$A" "$B" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker build -q -t "$S1" ../stage-1 >/dev/null
docker build -q -t "$S2" . >/dev/null
docker run -d --name "$A" --network none -e PORT=9001 "$S1" >/dev/null
docker run -d --name "$B" --network none -e PORT=9002 "$S2" >/dev/null
call() { # container port method path [json-body] [token] [key]
  local c=$1 p=$2 m=$3 path=$4 body=${5:-} tok=${6:-} key=${7:-}
  docker exec "$c" node -e '
    const [port,method,path,body,tok,key]=process.argv.slice(1);
    const h={"content-type":"application/json"}; if(tok)h.authorization="Bearer "+tok; if(key)h["idempotency-key"]=key;
    fetch(`http://127.0.0.1:${port}${path}`,{method,headers:h,body:method==="GET"?undefined:(body||undefined)})
      .then(async r=>{const t=await r.text();console.log(r.status+" "+t)});' "$p" "$m" "$path" "$body" "$tok" "$key"
}
for i in $(seq 1 50); do call "$A" 9001 GET /health 2>/dev/null | grep -q '^200' && call "$B" 9002 GET /health 2>/dev/null | grep -q '^200' && break; sleep 0.2; done
FX='{"currency":"EUR","minor_units":2,"settlement_operator_ids":["u2"],"users":[{"id":"u1","email":"a@x.io","password":"correct horse","display_name":"A","handle":"a","balance":10000},{"id":"u2","email":"b@x.io","password":"correct horse","display_name":"B","handle":"b","balance":0}]}'
call "$A" 9001 POST /_test/reset "$FX" | grep -q '^204'
jf() { node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s.replace(/^\d+ /,""))[process.argv[1]]))' "$1"; }
TOK=$(call "$A" 9001 POST /auth/login '{"email":"a@x.io","password":"correct horse"}' | jf token)
OP=$(call "$A" 9001 POST /auth/login '{"email":"b@x.io","password":"correct horse"}' | jf token)
R1=$(call "$A" 9001 POST /payments '{"to_handle":"b","amount":250}' "$TOK" up-key-1); echo "stage-1 payment: $R1"; echo "$R1" | grep -q '^201'
RQ=$(call "$A" 9001 POST /requests '{"payer_handle":"a","amount":100}' "$OP" up-key-2); echo "$RQ" | grep -q '^201'
RQID=$(echo "$RQ" | jf request_id)
EXPORT=$(call "$A" 9001 GET /_test/export | sed 's/^200 //')
echo "$EXPORT" | grep -q '"schema_version":1'
call "$B" 9002 POST /_test/import "$EXPORT" | grep -q '^204'
R2=$(call "$B" 9002 POST /payments '{"to_handle":"b","amount":250}' "$TOK" up-key-1); echo "stage-2 replay: $R2"
echo "$R2" | grep -q '^200'; [ "${R1#201 }" = "${R2#200 }" ]
ME=$(call "$B" 9002 GET /me '' "$TOK"); echo "stage-2 /me: $ME"
echo "$ME" | grep -q '"balance":9750,"total":9750,"available":9750,"held":0'
call "$B" 9002 POST "/requests/$RQID/pay" '{}' "$TOK" up-key-3 | grep -q '^201'
A1=$(call "$B" 9002 POST /authorizations '{"to_handle":"b","amount":100}' "$TOK" up-key-4); echo "$A1" | grep -q '^201'
echo "docker upgrade OK"
