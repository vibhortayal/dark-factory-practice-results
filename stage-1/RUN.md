# Pocketful stage 1: run instructions

Single Node.js 20 process (no npm dependencies), all state in memory.

Build and start (needs only Docker; no manual setup):

    docker build -t pocketful-s1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1

Check: `curl http://localhost:8080/health` returns `{"status":"ok"}`.
Seed a fixture with `POST /_test/reset`. The service needs no outbound network at run time.

Run under the stated limits: `docker run -d --rm --cpus 2 --memory 2g -e PORT=8080 -p 18080:8080 pocketful-s1`.

Tests (from this folder, using the same image, no host Node needed):

    docker run --rm -v "$PWD":/app -w /app node:20-alpine node --test test/
