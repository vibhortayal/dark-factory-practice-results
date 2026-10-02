# Pocketful stage 1 — run

One command (from this folder) builds the image and starts the service on port 8080:

    docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1

Check it: `curl http://localhost:8080/health` returns `{"status":"ok"}`.

- The service uses only the Python standard library; the image needs no network at run time.
- State is in memory only. `POST /_test/reset` seeds it; `GET /_test/export` and `POST /_test/import` move it between containers.
- Tests (need Python 3.9+, no packages): start the service, then
  `BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests -v`
