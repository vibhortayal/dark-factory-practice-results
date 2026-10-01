# Pocketful stage 1 — run instructions

Build and start (no manual setup, no network needed at run time):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Run from this folder (`stage-1/`). `PORT` defaults to 8080 when unset. Health check:
`curl http://localhost:8080/health` → `{"status":"ok"}`.

The service is pure Python 3.12 standard library (no third-party packages), keeps all state in
memory and listens on `0.0.0.0:$PORT`. Passwords are hashed with scrypt.

## Own tests

`tests/test_stage1.py` is a stdlib-only script that runs against a running container:

```sh
BASE_URL=http://localhost:8080 python3 tests/test_stage1.py
```
