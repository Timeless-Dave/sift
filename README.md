# Sift

Point your phone at food in a shop and check it in about 10 seconds, with nothing but the phone.
Sift uses light, sound and motion to fingerprint a food. It compares that fingerprint with
reference scans of genuine and adulterated samples, and says only what the evidence supports.

Built for the Meta Global AI Developer Hackathon 2026 (Indie track, theme: Push the Frontier).

## How a scan works

1. **What is it?** Point the camera at the barcode (looked up on Open Food Facts) or the food
   (identified by Muse vision), or pick it from a list.
2. **Measure, phone only.** Depending on the food, Sift runs some of these. Every one uses only the
   phone's own hardware:

   | Sensor | What it measures |
   | --- | --- |
   | Light sweep | The screen flashes 12 colours at the food; the front camera reads what comes back (a coarse visible spectrum) |
   | Torch | Colour and clarity with the flash off, then on |
   | Light through tissue | Camera and torch pressed on meat or fish: torch light that scatters a few millimetres in and back out, ring by ring (the vein-finder principle, in visible light) |
   | Bubble rise | Jar turned upside down, then upright: how fast the bubble climbs, which depends on viscosity and density |
   | Sound sweep | 200 Hz to 20 kHz through the package, into near-ultrasound most people can't hear |
   | Vibration | How the food damps the phone's vibration motor |

   Screen-side and camera-side sensors face opposite ways, so the app asks you to turn the phone
   over between them. Raw audio and video never leave the phone; only the measurements do.
3. **Compare.** The fingerprint is compared with genuine reference scans of that food from the same
   phone model. The answer is one of three:
   - **Matches genuine**
   - **Doesn't match genuine**: a reason to look closer, with the likely causes, never proof of fraud
   - **No verdict yet**: Sift doesn't have enough references, and says how many it needs
4. **Questions per food.** Each food lists what Sift is working on (seed oil in olive oil, syrup in
   honey, pork in beef, freshness, lab-grown vs conventional meat), with an honest status and
   sources. A question gets its own verdict only from a model with cross-validated accuracy of at
   least 80% on at least 20 labelled scans.

## What Sift checks

Milk, beef, chicken, fish, turmeric, chilli powder, honey, olive oil and sunflower oil. See the
app's "What it checks" page, `api/sift/domain/foods/` and `docs/foods-evidence.md`. Lab-grown vs
conventional meat is a **research** target: no validated method exists, on a phone or in a lab
(UK FSA review, 2026). Sift collects labelled scans and gives no verdicts.

Physics sets the limits. Phone cameras don't see infrared or UV, light reads only the surface and
the first few millimetres, and tinted or opaque packaging blocks it. Every food profile says how to
hold the phone, and the quality checks reject scans that can't see the food.
`docs/research.md` reviews the published evidence: what phone-only methods have shown, and why
lab spectroscopy results don't transfer to phones.

## The reference library

Sift's verdicts come from reference scans, not from borrowed accuracy figures. In Researcher mode,
any scan of a sample whose answer you know (genuine, adulterated, cultivated, conventional) can be
added to the library for that food and phone model. API keys get their own private library. Set
`SIFT_PROTECT_CALIBRATION=1` to require a key for reference scans.

## Lab tests

When a scan doesn't match, reagent tests can confirm it at home: iodine for starch in milk, a
rhodizonate swab for lead in turmeric, each read against the printed reference card. They live
under "Lab tests" in the app, with per-phone calibration and validation runs.

## Meta models

| Model | Job |
| --- | --- |
| Muse Spark (`muse-spark-1.3`) | Identifies the food from a camera frame, writes scan reports (guardrailed), and guides the lab tests |
| SAM 3.1 | Segments the sample in lab-test photos; falls back to Sift's own segmentation |
| Muse Voice Transcribe | Hands-free control in the lab tests |

Code measures and the model explains. Muse never produces a number or a verdict. Every report is
checked against the measurement and replaced by a template if it fails. Without `MODEL_API_KEY`
everything except voice keeps working, and each response says which path produced it.

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
  src/sensors/  phone sensing: torch, screen-light, contact, bubble, acoustic, vibration, motion, barcode
api/sift/
  http/       FastAPI app, middleware, request schemas, thin routers
  scan/       instant scans: wire schema, features, quality gates, reference matching, target models
  services/   lab-test runs, calibration and product lookup (no HTTP inside)
  agent/      Meta Model API client, Lab Agent, food identification, guardrails
  vision/     reference card, quality checks, colorimetric and screen-light analysis
  domain/     food profiles (domain/foods/) and lab-test assays (domain/assays/)
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
# SIFT_HOST is the address the phone will use: the host's LAN IP
# (macOS: ipconfig getifaddr en0; Linux: hostname -I | cut -d' ' -f1) or a local DNS name.
SIFT_HOST=<host-lan-ip> docker compose --profile https up --build -d
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

How the client IP reaches the rate limiter: browsers on `:8080` talk to nginx directly, and nginx
ignores any `X-Forwarded-For` they send. Caddy (`:8443`) connects to nginx's internal listener on 8081,
which is not published and is the only one that takes the client address from `X-Forwarded-For`. nginx
then passes the API a single address. The API (`SIFT_TRUST_PROXY=1`, set in compose) reads it only
when the request comes from the Docker network. Leave it `0` when running uvicorn directly. With Docker
Desktop or Colima on a Mac, port forwarding makes every `:8080` client appear as one address, so they
share one rate limit; on Linux, and through Caddy, each client is counted separately.

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
