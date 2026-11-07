# Sift Lab

A food-testing lab on your phone. Sift runs individually validated screening tests for
common food fraud, each based on published research, through one app and one API.

Built for the Meta Global AI Developer Hackathon 2026 (Indie track, theme: Push the Frontier).
Everything in this repository was written during the hackathon, Oct 26 to Nov 4, 2026.

## What it does

| Test | Method | What you need |
| --- | --- | --- |
| Starch in milk | Iodine colour reaction, read against the reference card | Tincture of iodine, printed card |
| Lead in turmeric | Rhodizonate lead swab, read against the reference card | Consumer lead swab, printed card |
| Olive oil purity | Screen-light scan: the screen flashes colours, the front camera records the reflections | A box or hood that blocks room light |

Planned tests (honey origin by pollen, pork in minced beef, urea in milk, milk acidity) are in the
registry with their source papers and are not runnable yet.

Sift will not:

- tell lab-grown meat from conventional meat (no published phone method does this reliably),
- give a verdict for a food no assay covers,
- return a result from a capture that fails its quality checks.

## Three tiers, one API

- **Shopper**: guided steps, a plain-language result and how sure Sift is.
- **Researcher**: practice runs in the app (walk the protocol, nothing is sent or saved), raw features,
  per-phone calibration, validation runs that measure accuracy, CSV and JSON export. Operators can set
  SIFT_PROTECT_CALIBRATION=1 so calibration writes and validation truth need an API key.
- **Developers and organisations**: the same REST API with API keys. See `/docs` on a running server.

## How a result is produced

1. **Capture.** Colour tests photograph the printed reference card (four ArUco corner markers,
   eight colour swatches, a sample ring). Screen-light tests record the mean camera colour
   under each screen colour.
2. **Quality checks, in code.** Blur, exposure, glare, ambient light, movement and card colour fit.
   A failed check returns the fix instead of a result.
3. **Measurement, in code.** Perspective correction from the markers, a colour correction fitted
   to the swatches, sample segmentation, then CIELAB features. Screen-light vectors go through
   a partial least squares model.
4. **Result.** A trained calibration curve or PLS model gives a value. Without one, colour tests
   fall back to the assay's qualitative rule (present or absent), and screen-light tests ask for
   calibration.
5. **Agent.** The Lab Agent explains the result in plain words. It never changes the numbers.

## Meta models

| Model | Job |
| --- | --- |
| Muse Spark (`muse-spark-1.3`) | Lab Agent: guides each protocol step with tool calls (`go_to_step`, `open_camera`, `start_timer`), reviews the rectified card image on passing captures (`capture_review`), writes the report |
| Muse Voice Transcribe | Hands-free control while your hands are wet or gloved |
| SAM 3.1 | Segments the sample inside the ring; falls back to Sift's own segmentation if unavailable |

Without `MODEL_API_KEY` the app still works: guidance follows the written protocol and reports
come from a template. Every response says which one produced it. The exception is voice
transcription, which has no offline mode: without the key `POST /v1/transcribe` answers
`503`, so type your message instead.

SAM 3.1 segments over the Responses API (`POST /responses`; see the [SAM overview](https://dev.meta.ai/docs/sam/overview)).
The path stays configurable (`SIFT_SAM_PATH`) in case the API moves.

## Accuracy

Sift reports accuracy only from validation runs with known answers, per test and per phone
(`accuracy.by_device`). No accuracy figure in this repo is borrowed from the papers it cites.

A run can be a calibration sample or a validation run, never both, so a model is never scored
on the samples it was trained on. The unit tests run on
synthetic card images and check the arithmetic, not real-world accuracy.

## Architecture

One API service and one web service, run together with Docker Compose. Inside the API, each
layer only depends on the layers below it, so any of them can be split into its own service
later without rewriting it.

```
web/  PWA (Vite, TypeScript) served by nginx; nginx proxies /api to the API
api/sift/
  http/       FastAPI app, middleware, request schemas, thin routers
  services/   run and calibration orchestration (no HTTP inside)
  agent/      Meta Model API client, Lab Agent, guardrails
  vision/     reference card, quality checks, colorimetric and screen-light analysis
  domain/     assay registry; one YAML entry per test in domain/assays/
  data/       SQLite store (WAL)
  core/       config, errors, logging, security
```

## Guardrails

**On the model.** Code measures and Muse Spark explains. Every report the model writes is checked
before it reaches a user. A report that fails any check is replaced by the deterministic template,
and the response records why (`report.fallback`, `report.guardrail`). A report fails if it:

- introduces a number the measurement didn't produce,
- contradicts the measured verdict (says "not detected" when the result is flagged, or the reverse),
- claims food is safe, pure or certified, or contains links.

The agent's tool calls are allow-listed and their arguments checked (real step ids, bounded timers).
User text is normalised, stripped of hidden control characters and capped before it reaches the
model. Meta calls retry on rate limits and server errors, and a circuit breaker stops calling for
a minute after repeated failures, so an outage degrades to offline guidance instead of timeouts.

**On requests.**
- Uploads are checked by file signature, size and pixel count (decompression-bomb cap).
- Screen-light frames are checked for colour names, frame counts and value ranges.
- Ids and device labels are pattern-checked.
- API keys are stored as SHA-256 hashes and can be revoked. Runs made with a key are visible only to that key.
- Calibration samples, trained models and accuracy figures belong to the key that made them. A key's model
  never reads public runs, and public calibration never reaches a key's runs.
- Set SIFT_PROTECT_CALIBRATION=1 to require an API key for calibration writes and validation truth; reads stay open.
- The enterprise tier requires a key.
- Admin calls use a constant-time token check.
- Rate limits apply per IP or key, with a stricter limit on agent and voice calls.
- Errors return a code, a message and a request id, never a stack trace.
- Logs are JSON with request ids and never include images, audio or message text.
- Production settings refuse a wildcard CORS origin.

**In deployment.** The API container runs as a non-root user on a read-only filesystem. nginx sends a
strict Content-Security-Policy and permits the camera and microphone only for the app itself.

Rate limiting is in-process by default, so keep one API worker per instance; set `SIFT_REDIS_URL`
to share a Redis-backed limiter across workers. If Redis is unreachable the API fails open to the
in-process limiter.

## Run it

```bash
# API
cd api
pip install -r requirements-dev.txt
cp .env.example .env            # add MODEL_API_KEY
ruff check . && python -m pytest
uvicorn sift.main:app --reload --port 8000

# App
cd web
npm install
npm run dev                      # proxies /api to localhost:8000

# Both, as in production (localhost only: plain HTTP, bearer tokens in cleartext off localhost)
cp api/.env.example api/.env     # fill it in; missing file is fine, the defaults run offline
docker compose up --build        # app on http://localhost:8080
```

Phone cameras need HTTPS outside `localhost`. For a phone on the same LAN, run the HTTPS profile:

```bash
# Find the host LAN IP first (macOS: ipconfig getifaddr en0; Linux: hostname -I | cut -d' ' -f1)
SIFT_CORS=http://localhost:8080,https://<host-lan-ip>:8443 docker compose --profile https up --build
# App on https://<host-lan-ip>:8443 (:8080 still serves plain HTTP for localhost)
```

The cert comes from Caddy's local CA (`tls internal`). On the phone, either accept the browser warning
(Advanced / Show Details, visit anyway) or install the root cert for a green lock:

```bash
docker compose --profile https cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

Send `caddy-root.crt` to the phone, then:

- iOS: open the file, install the profile, then Settings > General > About > Certificate Trust Settings
  and enable full trust for the Caddy authority.
- Android: Settings > Security > Encryption & credentials > Install a certificate > CA certificate,
  then select the file (exact steps vary by vendor).

Topology is browser -> (caddy) -> nginx (web) -> api. `SIFT_TRUST_PROXY=1` (set in compose) means the
API trusts `X-Forwarded-For` only from its Docker-network proxy and rate-limits off the last entry (the
address nginx saw); leading entries and any `X-Forwarded-For` from a direct client are ignored. Leave
it `0` when running uvicorn directly, and never set it `1` when the API is reachable from the internet.

Print `docs/sift-reference-card.svg` at 100% on plain white paper.

### Dependencies

Builds are pinned: the API installs `api/requirements.lock` with `--require-hashes`, the web app uses
`web/package-lock.json`, base images are pinned by digest, and CI actions by commit SHA. Dependabot
opens the update PRs. To change an API dependency, edit the range in `requirements.txt` (or
`requirements-dev.txt`), then regenerate both locks inside the image the API runs on:

```bash
docker run --rm -v "$PWD/api":/w -w /w python:3.12-slim sh -c "pip install -q pip-tools && \
  pip-compile -q --generate-hashes --strip-extras --allow-unsafe -o requirements.lock requirements.txt && \
  pip-compile -q --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.lock requirements-dev.txt"
```

## Sources

- Song et al., [Quantification of extra virgin olive oil adulteration using smartphone videos](https://pure.ulster.ac.uk/en/publications/07a2fdf5-cbb8-49c2-8d5a-921f26f0711b), Ulster University
- Song et al., [Smartphone detection of minced beef adulteration](https://pure.ulster.ac.uk/en/publications/smartphone-detection-of-minced-beef-adulteration/), Microchemical Journal 2021
- Costa et al., [Quantification of milk adulterants using colorimetric assays and smartphone image analysis](https://clok.uclan.ac.uk/33253), Microchemical Journal 2020
- FSSAI, [Detect Adulteration with Rapid Test (DART)](https://www.fssai.gov.in/book-details.php?bkid=201)
- Stanford, [Lead chromate found in turmeric](https://news.stanford.edu/2019/09/24/lead-found-turmeric/)
- UK FSA, [Review of analytical methods for cell-cultivated products](https://science.food.gov.uk/article/167297-review-of-analytical-methods-for-cell-cultivated-products)

## Licence

MIT
