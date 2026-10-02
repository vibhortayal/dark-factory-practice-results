# Pocketful stage 4: run instructions

The service is a single Python 3.12 file (`app.py`, standard library only) plus the browser UI in `ui/` (the stage-2 screens, unchanged in behaviour) (HTML, CSS, JavaScript, no external assets), in one container. Open `http://localhost:8080/` for the wallet UI.

Build and start (from this folder):

```sh
docker build -t pocketful-stage-4 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-4
```

- Listens on `0.0.0.0:$PORT` (default `8080` when `PORT` is unset).
- `GET /health` returns `200 {"status":"ok"}` within a second of start.
- State is in memory only; `POST /_test/reset`, `GET /_test/export` and `POST /_test/import`
  are enabled and unauthenticated.
- No outbound network is used at run time; the image has no dependencies beyond the Python base image.

Limits it was tested under: `docker run --cpus 2 --memory 2g`.

Stage-4 additions in `app.py`: refunds (`POST /payments/{id}/refunds`, ordinary ledger payments with `refund_of`), batch corrections
(`POST /correction-batches`, one validation-and-apply routine shared with single corrections), `refund_of` on every payment object and
`correction_batch_id` on every revision object. Earlier stages: one service clock (microseconds), payment revisions and corrections,
`GET /me?as_of=&known_at=`, `GET /statement` with snapshot tokens, historical holds. Exports of the stage-1, stage-2 and stage-3
services can be imported (stage-3 snapshot tokens keep paging their frozen entries).

Own tests (need running containers; Python 3, standard library only, except the browser tests):

```sh
# stage-4 container on 8080, optional second one on 8082, optional accepted stage-1/2/3 containers on 8083/8084/8085
export BASE_URL=http://127.0.0.1:8080 BASE_URL2=http://127.0.0.1:8082 BASE_URL_PREV=http://127.0.0.1:8083 \
       BASE_URL_PREV1=http://127.0.0.1:8083 BASE_URL_PREV2=http://127.0.0.1:8084 BASE_URL_PREV3=http://127.0.0.1:8085
cd tests
python3 test_stage1.py; python3 test_stage2_api.py                      # earlier lists (carried forward)
python3 test_stage3_api.py; python3 test_stage3_model.py; python3 test_stage3_upgrade.py; python3 test_stage3_load.py; python3 test_stage3_fuzz.py
python3 test_stage4_api.py       # refunds, batches, check orders, races
python3 test_stage4_model.py     # randomised histories with refunds and batches against the independent model (model3.py)
python3 test_stage4_upgrade.py   # stage-1 / 2 / 3 / own exports
python3 test_stage4_fuzz.py      # body/number/instant fuzz, mutation sweep over refund and batch state
# Browser (needs Python with Playwright and Chromium):
SHOTS=/tmp/shots python test_stage2_ui.py
```
