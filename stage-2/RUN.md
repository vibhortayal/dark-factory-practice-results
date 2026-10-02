# Pocketful stage 2: run instructions

The service is a single Python 3.12 file (`app.py`, standard library only) plus the browser UI in `ui/` (HTML, CSS, JavaScript, no external assets), in one container. Open `http://localhost:8080/` for the wallet UI.

Build and start (from this folder):

```sh
docker build -t pocketful-stage-2 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-2
```

- Listens on `0.0.0.0:$PORT` (default `8080` when `PORT` is unset).
- `GET /health` returns `200 {"status":"ok"}` within a second of start.
- State is in memory only; `POST /_test/reset`, `GET /_test/export` and `POST /_test/import`
  are enabled and unauthenticated.
- No outbound network is used at run time; the image has no dependencies beyond the Python base image.

Limits it was tested under: `docker run --cpus 2 --memory 2g`.

Own tests (need running containers; Python 3, standard library only, except the browser tests):

```sh
# API: stage-2 container on 8080, optional second stage-2 container on 8082, optional stage-1 container on 8081
BASE_URL=http://127.0.0.1:8080 BASE_URL2=http://127.0.0.1:8082 BASE_URL_PREV=http://127.0.0.1:8081 python3 tests/test_stage1.py
BASE_URL=http://127.0.0.1:8080 BASE_URL2=http://127.0.0.1:8082 BASE_URL_PREV=http://127.0.0.1:8081 python3 tests/test_stage2_api.py
# Browser (needs Python with Playwright and Chromium):
BASE_URL=http://127.0.0.1:8080 BASE_URL_PREV=http://127.0.0.1:8081 SHOTS=/tmp/shots python tests/test_stage2_ui.py
```
