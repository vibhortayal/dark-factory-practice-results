# Pocketful stage 1: build and run

Standard-library Python 3.12 only; no dependencies are downloaded at build or run time
beyond the base image.

    docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1

The service listens on `0.0.0.0:$PORT` (default `8080`). Check it with
`curl localhost:8080/health`. State is in memory and is replaced by `POST /_test/reset`.

## Own tests

With the service running on port 8080 (stdlib `unittest`, no dependencies):

    BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests -v
