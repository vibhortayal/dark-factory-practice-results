#!/bin/sh
# Builds the image, starts two containers (A on 18080, B on 18081, 2 CPU / 2 GiB each),
# runs the own test-suite against them and removes the containers.
set -e
cd "$(dirname "$0")/.."
docker build -t pocketful-s1 .
docker rm -f pocketful-s1-a pocketful-s1-b >/dev/null 2>&1 || true
docker run -d --name pocketful-s1-a --cpus 2 --memory 2g -e PORT=8080 -p 127.0.0.1:18080:8080 pocketful-s1 >/dev/null
docker run -d --name pocketful-s1-b --cpus 2 --memory 2g -e PORT=8080 -p 127.0.0.1:18081:8080 pocketful-s1 >/dev/null
trap 'docker rm -f pocketful-s1-a pocketful-s1-b >/dev/null 2>&1' EXIT
for i in $(seq 1 60); do curl -fs http://127.0.0.1:18080/health >/dev/null 2>&1 && curl -fs http://127.0.0.1:18081/health >/dev/null 2>&1 && break; sleep 1; done
BASE_URL=http://127.0.0.1:18080 BASE_URL_B=http://127.0.0.1:18081 python3 -m unittest discover -s tests -v "$@"
