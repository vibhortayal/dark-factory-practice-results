# Pocketful stage 1 — run

One command builds and starts the service on http://localhost:8080 (run from this folder):

```
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Any port works: `-e PORT=9000 -p 9000:9000`. The image has no dependencies beyond
Python 3.12 (standard library only) and needs no network at run time.
State is in memory; seed it with `POST /_test/reset`.

Tests (stdlib `unittest`, against a running service):

```
BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests -v
```
