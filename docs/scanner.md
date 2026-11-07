# Sift scanner: design contract

Sift is a shop-aisle food check. The user points the phone at a food (or presses it against the
package), Sift runs a capture of about 6–8 seconds using only the phone's own hardware, and
answers. There are no reagents and no step-by-step protocols. The older reagent tests stay as
optional "lab tests" for confirmation and are no longer the front door.

Every part of the scanner (web sensors, backend, food profiles, identification) is built against
this contract.

## What a phone can sense (phone only, no add-ons)

| Modality id   | Hardware                              | What it measures                                               | Browser support            |
|---------------|---------------------------------------|----------------------------------------------------------------|----------------------------|
| `torch`       | Rear camera + flash (torch)           | Colour and brightness with the torch off, then on. Ambient-subtracted reflectance, glare, and light through thin liquids | Torch: Android Chrome only |
| `screenlight` | Front camera + screen as light source | Reflectance under 12 screen colours: a coarse spectrum         | All                        |
| `acoustic`    | Speaker + mic, 200 Hz–20 kHz sweep    | How the container and contents pass and damp sound, including near-ultrasound above 17 kHz most people can't hear | All (48 kHz audio)         |
| `vibration`   | Vibration motor + accelerometer       | How a pressed-on solid (meat, fruit, a jar) damps vibration    | Vibrate: Android only      |
| `motion`      | Gyroscope + accelerometer             | Whether the phone was held still (quality gate only)           | All, after a permission tap on iOS |
| identify      | Camera frame + Muse vision; barcode   | Which food or product this is                                  | BarcodeDetector: Android   |

Not available from a stock phone: infrared (cameras filter it out, and the Face ID IR hardware is
closed to apps), UV, and true ultrasound. Sift never claims them.

## Where Sift sits

Lab methods for food authentication use NIR, mid-IR and FTIR, Raman, hyperspectral imaging,
ultrasound and photoacoustics, paired with chemometric models (review: Chaudhary et al. 2022,
[Spectroscopic techniques for authentication of animal origin foods](https://pmc.ncbi.nlm.nih.gov/articles/PMC9531581/)).
Consumer handheld scanners (SCiO, Tellspec) moved to B2B. Two reasons stand out: what a pocket
sensor can see is limited, and a classifier needs a large reference database of authentic and
adulterated samples that nobody built for shoppers. Smartphone-sized NIR modules exist for
spice-fraud checks but don't ship in phones.

So Sift's bet has two parts:

1. **The phone you already have.** Visible-light "spectra" from the screen and torch, plus
   audible and near-ultrasound acoustics. Built to accept an NIR source when phones carry one.
2. **The reference library is the product.** Genuine and adulterated scans per food and phone
   model, built in the open, with "no verdict yet" until the library supports one.

Physical limits that every food profile must respect: light reads only the surface and the first
few millimetres, and opaque or tinted packaging blocks it. Each profile says where to hold the
phone, and the quality gates reject scans that can't see the food. Published optical and
ultrasound work on cultivated meat monitors *production*, such as cells on scaffolds and
bioreactor density. It doesn't tell cultured from conventional at the shelf, which is why that
target stays `research`.

## Honesty rules

1. **No verdict without evidence.** A verdict comes only from (a) comparison with at least
   `MIN_GENUINE` (5) genuine reference scans of the same food on the same device class, or
   (b) a trained model whose cross-validated accuracy is reported alongside the verdict.
   Otherwise the answer is `no_reference`: "Sift has no reference scans for this yet."
2. **"Differs from genuine" is not "adulterated".** The wording says the scan didn't match genuine
   references and names the likely causes the food profile lists.
3. **Lab-grown (cultured) vs conventional** is a `research` target. No published phone method
   does it, so Sift collects reference scans and never gives a verdict until a model passes validation.
4. Every target has a `status` (`research` | `experimental` | `validated`) and cites its sources.
   `validated` requires a validation set with known answers, measured by Sift.
5. **Code measures and the model explains.** Muse identifies the food and writes the explanation;
   it never produces the numbers. The existing guardrails apply.

## Data flow

```
identify:  camera frame -> POST /v1/identify -> {food, candidates}     (Muse vision; offline -> user picks)
           barcode      -> GET /v1/products/{barcode} -> {name, food}   (Open Food Facts lookup)
scan:      sensors (web/src/sensors) -> features computed on the phone
           -> POST /v1/scans {food, mode, capture{...}}
           -> quality gates -> fingerprint vs reference library -> trained target models
           -> response {match, findings, quality, report}
reference: same capture with mode "reference" + label -> stored in the library (Researcher tier)
```

Features are computed on the phone; raw audio and video never leave it.

## Request: `POST /v1/scans`

Pydantic source of truth: `api/sift/scan/schemas.py`. TypeScript mirror: `web/src/sensors/types.ts`.

```jsonc
{
  "food": "olive-oil",                      // food profile id (api/sift/domain/foods/*.yaml)
  "product": {"barcode": "8410660034017"},  // optional
  "device": "Pixel 8",                      // device label, as elsewhere
  "mode": "check",                          // "check" | "reference"
  "reference": {                            // required when mode == "reference"
    "label": "genuine",                     // genuine | adulterated | cultured | conventional
    "target": "seed-oil-dilution",          // optional: which target this sample speaks to
    "value": 20,                            // optional: e.g. percent adulterant
    "note": "20% sunflower, lab-mixed"
  },
  "capture": {                              // any subset; the food profile says which it uses
    "torch":       {"off": RGBStats, "on": RGBStats, "torch_available": true},
    "screenlight": {"frames": {"white": [[r,g,b], ...], "black": [...], "red": [...], ...}},
    "acoustic":    {"sample_rate": 48000, "bins_hz": [...], "response_db": [...], "noise_db": [...]},
    "vibration":   {"rate_hz": 60, "rms_on": 0.8, "rms_off": 0.05, "spectrum": [...], "vibrate_available": true},
    "motion":      {"max_rotation_dps": 4.2, "accel_jitter": 0.03}
  }
}
// RGBStats = {"mean": [r,g,b], "std": [r,g,b], "clipped": 0.01}  (sRGB 0..1, centre region)
```

Limits: `bins_hz` and `response_db` have the same length, at most 128 entries, increasing,
within 100–24000 Hz. `spectrum` has at most 64 entries. All numbers are finite.

## Response

```jsonc
{
  "scan_id": "3f9c1a2b7d4e",
  "food": "olive-oil",
  "mode": "check",
  "status": "ok",                 // ok | rejected (quality failed) | stored (reference mode)
  "quality": {"ok": true, "problems": [{"modality": "torch", "code": "...", "severity": "reject|warn", "message": "...", "fix": "..."}]},
  "match": {                      // fingerprint comparison with genuine references
    "status": "no_reference",     // no_reference | matches | differs
    "distance": null, "threshold": null, "n_genuine": 0, "modalities": ["torch", "screenlight"]
  },
  "findings": [                   // one per target in the food profile
    {"target": "seed-oil-dilution", "kind": "adulteration", "status": "no_model",   // no_model | model | research
     "label": "Not measured yet", "confidence": null, "model": null}
  ],
  "report": {"agent": "offline", "text": "..."}
}
```

## Food profile: `api/sift/domain/foods/<id>.yaml`

The loader and validation live in `api/sift/domain/foods.py`; `olive-oil.yaml` is the worked example.
