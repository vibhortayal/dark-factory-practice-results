# Pocketful stage 1: run instructions

Single container, Python 3.12 standard library only (no packages are fetched at build or run time
other than the `python:3.12-slim` base image).

Build and start (one command, from this folder):

```sh
docker build -t pocketful-s1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
```

Check: `curl -s localhost:8080/health` returns `{"status":"ok"}`.
`PORT` defaults to 8080 when unset. State is in memory (reset with `POST /_test/reset`).

Own tests (stdlib only, against a running service):

```sh
BASE_URL=http://localhost:8080 python3 tests/test_stage1.py
```
