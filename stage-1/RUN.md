# Pocketful stage 1 — run instructions

Build and start (from this folder, `stage-1/`):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and is healthy within a second:
`curl http://localhost:8080/health` → `{"status":"ok"}`.

No dependencies are installed (Node.js standard library only), and nothing is fetched at run time.
State is in memory. `POST /_test/reset`, `GET /_test/export` and `POST /_test/import` are enabled.

## Own tests

Start the container, then (Node 18+ on the host):

```sh
BASE_URL=http://localhost:8080 node --test test/
```
