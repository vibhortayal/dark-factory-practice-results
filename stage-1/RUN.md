# Pocketful stage 1: run instructions

The service is a single Python 3.12 file (`app.py`, standard library only) in a container.

Build and start (from this folder):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-1
```

- Listens on `0.0.0.0:$PORT` (default `8080` when `PORT` is unset).
- `GET /health` returns `200 {"status":"ok"}` within a second of start.
- State is in memory only; `POST /_test/reset`, `GET /_test/export` and `POST /_test/import`
  are enabled and unauthenticated.
- No outbound network is used at run time; the image has no dependencies beyond the Python base image.

Limits it was tested under: `docker run --cpus 2 --memory 2g`.

Own tests (need a running container; standard library only):

```sh
BASE_URL=http://127.0.0.1:8080 python3 tests/test_stage1.py
```
