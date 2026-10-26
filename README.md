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

Planned tests (honey origin by pollen, pork in minced beef, urea in milk, milk pH) are in the
registry with their source papers and are not runnable yet.

Sift will not:

- tell lab-grown meat from conventional meat (no published phone method does this reliably),
- give a verdict for a food no assay covers,
- return a result from a capture that fails its quality checks.

## Three tiers, one API

- **Shopper**: guided steps, a plain-language result and how sure Sift is.
- **Researcher**: practice runs, raw features, per-phone calibration, validation runs that
  measure accuracy, CSV and JSON export.
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
| Muse Spark (`muse-spark-1.3`) | Lab Agent: guides each protocol step with tool calls (`go_to_step`, `open_camera`, `start_timer`), reviews the rectified card image (`capture_review`), writes the report |
| Muse Voice Transcribe | Hands-free control while your hands are wet or gloved |
| SAM 3.1 | Segments the sample inside the ring; falls back to Sift's own segmentation if unavailable |

Without `MODEL_API_KEY` the app still works: guidance follows the written protocol and reports
come from a template. Every response says which one produced it.

The SAM 3.1 request path is configurable (`SIFT_SAM_PATH`); check it against the Model API docs.

## Accuracy

Sift reports accuracy only from validation runs with known answers, per test and per phone.
No accuracy figure in this repo is borrowed from the papers it cites. The unit tests run on
synthetic card images and check the arithmetic, not real-world accuracy.

## Run it

```bash
# API
cd api
pip install -r requirements-dev.txt
cp .env.example .env            # add MODEL_API_KEY
python -m pytest
uvicorn sift.main:app --reload --port 8000

# App
cd web
npm install
npm run dev                      # proxies /api to localhost:8000
```

Phone cameras need HTTPS outside `localhost`. For testing on a phone, deploy the API and the
built app (`npm run build`, set `VITE_API_URL`) behind HTTPS.

Print `docs/sift-reference-card.svg` at 100% on plain white paper.

## Layout

```
api/sift/assays/        one YAML file per test: protocol, analysis, bands, sources, limits
api/sift/card.py        reference card: printing, detection, colour correction
api/sift/analysis/      quality checks, colorimetric and screen-light analysis
api/sift/agent.py       Lab Agent (Muse Spark)
api/sift/main.py        REST API
web/                    PWA (Vite, TypeScript)
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
