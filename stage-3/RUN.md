# Pocketful stage 3: run instructions

The service is a single Python 3.12 file (`app.py`, standard library only) plus the browser UI in `ui/` (the stage-2 screens, unchanged in behaviour) (HTML, CSS, JavaScript, no external assets), in one container. Open `http://localhost:8080/` for the wallet UI.

Build and start (from this folder):

```sh
docker build -t pocketful-stage-3 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-3
```

- Listens on `0.0.0.0:$PORT` (default `8080` when `PORT` is unset).
- `GET /health` returns `200 {"status":"ok"}` within a second of start.
- State is in memory only; `POST /_test/reset`, `GET /_test/export` and `POST /_test/import`
  are enabled and unauthenticated.
- No outbound network is used at run time; the image has no dependencies beyond the Python base image.

Limits it was tested under: `docker run --cpus 2 --memory 2g`.

Stage-3 additions in `app.py`: one service clock (microseconds, strictly increasing), payment revisions and corrections,
`GET /me?as_of=&known_at=`, `GET /statement` with snapshot tokens, `GET /payments/{id}/revisions`, historical holds.
Exports of the stage-1 and stage-2 services can be imported.

Own tests (need running containers; Python 3, standard library only, except the browser tests):

```sh
# stage-3 container on 8080, optional second one on 8082, optional accepted stage-1 / stage-2 containers on 8083 / 8084
export BASE_URL=http://127.0.0.1:8080 BASE_URL2=http://127.0.0.1:8082 BASE_URL_PREV=http://127.0.0.1:8083 \
       BASE_URL_PREV1=http://127.0.0.1:8083 BASE_URL_PREV2=http://127.0.0.1:8084
cd tests
python3 test_stage1.py           # stage-1 list (carried forward)
python3 test_stage2_api.py       # stage-2 list
python3 test_stage3_api.py       # timestamps, as_of/known_at, statements, snapshots, corrections, holds
python3 test_stage3_model.py     # randomised histories against the independent model (model3.py)
python3 test_stage3_upgrade.py   # stage-1 / stage-2 / own exports
python3 test_stage3_load.py      # 5,000 payments, 50-in-flight bursts
python3 test_stage3_fuzz.py      # instant/number fuzz, mutation sweeps
# Browser (needs Python with Playwright and Chromium):
SHOTS=/tmp/shots python test_stage2_ui.py
```
