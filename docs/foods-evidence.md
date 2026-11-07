# Foods evidence: what the scanner can lean on, and what it still needs

One row per food profile target. Status follows `docs/scanner.md`: `experimental` means a
published phone-camera, phone-screen, phone-audio or phone-vibration method (or a
reagent-free smartphone optical method) exists for that question; `research` means it does
not. Nothing here is `validated`: that needs Sift's own validation runs with known answers.

Every reference below was opened during research; titles, venues and numbers are quoted
from the source as read. `openalex.org/works/…` links are the readable record pages for
papers whose publisher pages block automated readers.

| Food | Target | Status | Best evidence | What Sift still needs (reference scans) |
| --- | --- | --- | --- | --- |
| Olive oil | Seed-oil dilution | experimental | Song et al., Talanta 2020: screen-light video + PLS quantified 5–50% vegetable oil in EVOO (R² 0.98, RMSE 0.02), matching NIR/UV-vis | Genuine EVOO scans per cultivar/region, same phone model; refined vs extra-virgin pairs |
| Cow milk | Water dilution | research | No phone-only method found. Nearest: lactometer is the standard rapid test (cow milk 1.028–1.032); Costa et al., Microchem. J. 2020 reads milk adulterants by phone only via reagent reactions | Genuine whole/toned/skimmed scans per brand; lab-mixed 5–30% water series to test whether torch/acoustic see anything at all |
| Beef / minced beef | Pork substitution | experimental | Song et al., Microchem. J. 2021: screen light + front-camera video predicted 10–100% pork in minced beef (R² 0.73–0.98, RMSE 0.04–0.16) across 7 phone/condition sets | Genuine minced-beef scans per fat ratio; lab-mixed 10–50% pork series through pack film |
| Beef | Freshness / spoilage | experimental | MeatScan v4, Ind. J. Comp. Sci. Tech. 2026: ConvNeXt on 10,517 smartphone images incl. beef cuts reports 100% fresh-vs-spoiled — a single-market claim needing replication | Fresh-to-spoiled time series per cut and pack type (vacuum vs air), with storage-temperature notes |
| Beef | Cultured vs conventional | research | UK FSA review 2026: no single lab method reliably authenticates cultivated meat, no validated methods exist, no phone method covered | Cultured-beef samples are not yet on retail sale; collect conventional-beef references so the library is ready |
| Chicken | Freshness | experimental | Calvin et al., IEEE 3ICT 2020: Ayam6Net CNN on smartphone photos of broiler breasts, 92.9% fresh-vs-rotten. Caveat: Asmara et al., IEEE ICIEV 2018 reached only 58.33% (3-class, 150 images) on uncontrolled-light phone photos | Fresh-to-spoiled time series per cut, fixed vs shop lighting; freezer-burn negatives |
| Chicken | Cultured vs conventional | research | UK FSA review 2026 (as for beef) | Same as beef: conventional-chicken references first |
| Fish fillet | Species substitution | experimental | Sensors 2025 (salmon vs rainbow trout): smartphone RGB photos of steak/fillet/sashimi cuts, DenseNet121 at 84.58% | Label-verified fillets per species sold locally; dyed-trout negatives |
| Fish fillet | Freshness | experimental | Same study: 3-level freshness grading at 73.75%; robust to blur/tilt, not to varied lighting or packaging | Day-by-day freshness series per species, through pack film |
| Turmeric | Lead chromate / metanil yellow | research | No phone-only method for these dyes. Nearest: handheld NIR + PCA-SIMCA for 0–30% metanil yellow (J. Food Prot. 2020, lab instrument); phone colorimetry for curcumin needs reagents + lightbox (Anal. Sci. 2024) | Genuine turmeric per variety/grind; lab-spiked dye series to test whether screenlight sees anything |
| Chilli powder | Sudan dyes, brick powder | research | Sudan I–IV in chilli needs extraction + UFLC-UV (Heliyon 2020, lab); brick dust needs acid-insoluble ash (lab). Nearest optical: digital-image Sudan I in ketchup, R² 0.96 (Food Chem. 2020) — a different matrix | Genuine chilli per variety/roast; lab-spiked Sudan and brick-powder series |
| Honey | Sugar-syrup dilution | experimental | Teye et al., Smart Agric. Tech. 2024: phone photos + random forest at 100% (authentic vs spiked); Dziubaniuk et al., Appl. Sci. 2026: RGB histograms estimated 0–50% syrup in one lab series (R² 0.98, RMSE 2.22pp) | Genuine honey per floral source (liquid + crystallised); lab-mixed syrup series per syrup type, through the jar |
| Sunflower / cooking oil | Used-oil re-sale or mixing | research | No phone method for used oil. Nearest: lab computer vision predicts frying-oil FFA/polar materials (J. Food Qual. 2019, R² > 0.91); screen-light video quantifies fresh-oil mixing (Talanta 2020) | Fresh oils per brand/blend; used-oil and fresh/used mix series |

## Not profiled: mustard oil (argemone oil)

No published phone-sensing basis was found. Argemone oil is screened by the nitric-acid
paper spot test and confirmed by HPLC of sanguinarine (Auriga Research adulteration panel;
FSSAI DART booklet) — both reagent/lab methods with no optical or acoustic phone analogue
in the literature. Revisit if a reagent-free phone study appears.
