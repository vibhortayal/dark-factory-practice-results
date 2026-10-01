# Pocketful stage 1 — run

Node.js 20, no third-party dependencies, all state in process memory.

Build and start (from this folder, `stage-1/`):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Then `curl http://localhost:8080/health` returns `{"status":"ok"}`.
`PORT` defaults to 8080. No outbound network is needed at run time.

Own tests (optional, not needed at run time; needs Node 18+ locally):

```sh
node --test test/
```
