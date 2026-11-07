# Evidence review: phone-only food authentication

Reviewed 2026-11-07, from the sources the product owner collected and our own searches. For each
source: what it shows, how a phone-only scanner can use it, and whether we read the full text.
Numbers are quoted from the source. "Not read" means we could not get past a paywall, a block or
a 404, so we haven't verified its claims.

## Bottom line

1. **Lab methods are strong, but phones can't run them.** NIR, mid-IR/FTIR, Raman, hyperspectral
   imaging, LIBS, NMR, THz and photoacoustics authenticate meat, dairy, honey and oil well. Every one
   of them needs wavelengths or hardware a stock phone lacks. Their numbers do not transfer to Sift.
2. **There is published phone-only work, and it is closer to Sift than the lab reviews:**
   screen-light video for olive oil and minced beef (Song et al.), bubble rise in sealed bottles
   (LiquidHash), speaker and microphone liquid identification (Akte-Liquid, HearLiquid), and the
   vibration motor plus accelerometer for viscosity (Vi-Liquid, VibMilk). This is Sift's evidence base.
3. **What works is screening, not quantification.** Visible-band sensors separated pure from
   adulterated well but struggled to estimate *how much*. Fengou 2021, fresh pork/chicken: 3-class
   93.33% vs 5-class 56.67%. So Sift's question is "does this match genuine?".
4. **Every result depends on the sensor, and the reference data is the bottleneck.** Results don't
   carry across instruments. Calibration transfer is "non-trivial", and many studies "lack external
   validation with independent data". The consumer scanners that failed (SCiO, Tellspec) moved to
   B2B. Tellspec's own FAQ says adding a new food "is a special project". Sift therefore builds
   reference libraries per food and per phone model, and says "no verdict yet" until they exist.
5. **Cultivated vs conventional meat:** no validated method exists, phone or lab. The UK FSA review
   (2026) says "no single analytical approach is currently sufficient to characterise or
   authenticate CCPs", and that methods "may struggle to differentiate CCP from conventional meat".
   Spectroscopy was proposed for this, but nobody has evaluated it. Sift keeps this as a research
   target: it collects labelled scans and gives no verdicts.

## New modalities this review adds

| Modality | Physics | Evidence | Web feasibility |
|---|---|---|---|
| **contact** (torch diffuse reflectance) | Camera and torch pressed against meat or fish. Light enters the tissue, scatters, and comes back carrying absorption by myoglobin and haemoglobin, which changes with oxygenation and freshness (500–700 nm). This is the principle behind camera heart-rate apps and, at NIR, vein finders. It reads below the surface. | Visible-band freshness and substitution work in the reviews below. We found no phone study of meat in contact mode yet, so this is `research`. | Torch on Android Chrome; the camera can't focus at contact, so read diffuse intensity and its radial falloff, not an image. |
| **bubble** (inverted-bottle bubble rise) | Turn the sealed bottle over and film the air bubble rising. Terminal velocity depends on viscosity and density (Stokes' law). | LiquidHash: 93.9% olive oil, 95.0% honey, 86.0% vodka through sealed bottles. Honey worked at **30 fps**; oil and vodka needed 120–240 fps. | 30 fps is fine in a browser. Most browsers can't reach 120–240 fps, so on the web this is a honey and syrup method only. |

## Sources

### Phone-only sensing (most relevant)

- **Sun B. et al., "Detecting Counterfeit Liquid Food Products in a Sealed Bottle Using a Smartphone
  Camera" (LiquidHash), MobiSys 2022.** https://doi.org/10.1145/3498361.3539776 — *Read (full PDF).*
  Turn the sealed bottle over and record the bubbles; bubble kinematics reflect density and
  viscosity. Accuracy: olive oil 93.9%, honey 95.0%, vodka 86.0%, over 500+ minutes of video. It beat
  unaided participants, who could use a flashlight and online images. It needs 120–240 fps for oil
  and vodka; honey works at 30 fps. Dark or opaque contents need extra light.
- **Huang Y., "Smartphone-Based Identification of Unknown Liquids via Active Vibration Sensing"
  (Vi-Liquid), arXiv 2603.28787, 2026.** https://arxiv.org/html/2603.28787v1 — *Read (about half
  verbatim).* An iPhone vibration motor (resonates near 167 Hz) and the accelerometer (100 Hz) are
  pressed to the container wall. Across 30 liquids: 2.9% mean relative viscosity error and 95.47%
  identification. Honey had the highest error (6.16%). Needs per-phone, per-container calibration;
  iPhone only. The web Vibration API exposes neither frequency nor burst control, so Sift's
  `vibration` stays a coarse damping measure, labelled `research`.
- **Song W. et al., "Use of smartphone videos and pattern recognition for food authentication",
  Sensors and Actuators B, 2020.** https://www.sciencedirect.com/science/article/abs/pii/S0925400519314467
  — *Not read (paywalled).* The search summary reports reagent-free screen-light video, with test
  accuracies on olive oil adulteration and milk fat content. This is the basis of Sift's `screenlight`.
- **Song W. et al., "Smartphone detection of minced beef adulteration", Microchemical Journal 2021.**
  https://www.researchgate.net/publication/349385580_Smartphone_detection_of_minced_beef_adulteration
  — *Not read (403).* Already cited in the beef profile.
- **Akte-Liquid: Acoustic-based Liquid Identification with Smartphones, ACM 2022.**
  https://dl.acm.org/doi/10.1145/3551640 — *Not read (403).* The search summary says the speaker and
  microphone tell whole milk from 2% milk, among other liquid pairs, with positioning constraints.
  This is the closest published basis for Sift's `acoustic` sweep.
- **HearLiquid: Non-intrusive Liquid Fraud Detection Using Commodity Acoustic Devices.**
  https://www.researchgate.net/publication/357943730 — *Not read (403).* Speaker and microphone on
  opposite sides of a bottle, read through frequency analysis of the transmitted signal.
- **VibMilk: Nonintrusive Milk Spoilage Detection via Smartphone Vibration.**
  https://www.researchgate.net/publication/377992521 — *Not read (403).*
- **Chan J. et al., "Testing a Drop of Liquid Using Smartphone LiDAR", 2022.** https://arxiv.org/abs/2203.07567
  — *Read (PDF text extracted).* Needs LiDAR, which browsers can't access, so it's out of scope for
  the web app.

### Phone-adjacent: low-cost NIR on a mobile device

- **Juric S., Žalik B., "An innovative approach to near-infrared spectroscopy using a standard mobile
  device and its clinical application in the real-time visualization of peripheral veins", BMC Med
  Inform Decis Mak 2014.** https://doi.org/10.1186/s12911-014-0100-z (open access, PMC4251692) —
  *Read (full text).* The prototype was "35.2% more successful in visualizing and locating veins
  (n = 500 attempts) than the nursing students", with 1.6 (SD 1.3) more veins found per patient in a
  64-patient trial. **It was not phone-only:** it used an external USB camera with its
  infrared-blocking filter (which blocks above 720 nm) removed, plus four 740 nm LEDs in a phone case.
  The phone did the processing (difference of Gaussians, Laplacian) at about 12 fps. Lessons for
  Sift: phone cameras see to about 720 nm, so the red-band tissue absorption is reachable with the
  torch in contact. And a cheap NIR add-on is proven, if "phone only" is ever relaxed.

### Lab spectroscopy reviews (context; their numbers don't transfer)

- **Chaudhary V. et al., "Spectroscopic techniques for authentication of animal origin foods",
  Front Nutr 2022.** https://pmc.ncbi.nlm.nih.gov/articles/PMC9531581/ — *Read.* Covers THz, LIBS,
  HSI, NIR (780–2500 nm), MIR, FTIR, Raman, UV-Vis, fluorescence and NMR. Visible-band highlights,
  mostly paired with NIR: multispectral imaging (18 bands, 405–970 nm) for minced beef with
  horsemeat, 95.31% on independent batches; beef with pork, 98.48%, with a 10% limit of detection.
  It names barriers: "High investment costs", mostly "laboratory-scale" work, and the need for
  calibration. No smartphone study, no cultured-meat study.
- **Fengou L.-C. et al., "Detection of Meat Adulteration Using Spectroscopy-Based Sensors", Foods
  2021.** https://pmc.ncbi.nlm.nih.gov/articles/PMC8071343/ — *Read.* A visible point spectrometer
  (340–850 nm) vs multispectral imaging (405–970 nm) vs fluorescence, on 120 samples per scenario with
  external validation. Visible spectrometer: pure vs adulterated 93.33% (pork/chicken) and 96.67%
  (beef/offal), but 56.67% and 76.67% when estimating the level. Multispectral imaging: 87–100%.
  Results "appear to be sensor-specific". This is the strongest support for Sift's screening framing.
- **Hu Y. et al., "Detection and quantification of offal content in ground beef meat using
  vibrational spectroscopic-based chemometric analysis", Sci Rep 2017.**
  https://pmc.ncbi.nlm.nih.gov/articles/PMC5680338/ — *Read.* FT-IR ATR (mid-IR, 1000–1800 cm⁻¹).
  94% prediction accuracy (the >99% in the abstract is calibration). Limit of detection below 10%
  w/w. Not phone-reproducible. Useful as a model of validation design: independent prediction sets,
  samples from different days and stores, and a warning about overfitting.
- **Prieto N. et al., "A Review of the Principles and Applications of Near-Infrared Spectroscopy to
  Characterize Meat, Fat, and Meat Products", Applied Spectroscopy 71(7), 2017.**
  https://journals.sagepub.com/doi/full/10.1177/0003702817709299 — *Abstract only (full text 403).*
  NIR principles, preprocessing and portable NIR spectrometers in the meat industry. It discusses
  discrepancies between studies. Not phone-reproducible.
- **Nasution A.M.T., Suyanto H., "Infrared Spectroscopy for Detecting Adulterants in Food and
  Traditional Indonesian Herbal Medicine", IntechOpen 2022.** https://www.intechopen.com/chapters/84580
  — *Read (partial).* IR background, 700 nm–30 µm. No phone-relevant data.
- **Sun X. et al., "Research Progress of Electronic Nose and Near-Infrared Spectroscopy in Meat
  Adulteration Detection", Chemosensors 12(3):35, 2024.** https://www.mdpi.com/2227-9040/12/3/35 —
  *Not read (403).* The abstract notes limits in detecting specific meats and demanding NIR modelling.
- **He W., Zeng Q., "Non-Invasive Food Authentication Using Vibrational Spectroscopy Techniques for
  Low-Resolution Food Fingerprinting", Appl Sci 15(11):5948, 2025.** https://www.mdpi.com/2076-3417/15/11/5948
  — *Not read (403).* Summarised by Spectroscopy Online
  (https://www.spectroscopyonline.com/view/the-remaining-challenges-in-using-vibrational-spectroscopy-for-food-authentication):
  handheld devices have "lower resolution and reproducibility", "calibration transfer ... remains
  non-trivial", and many studies lack "external validation".
- **Photoacoustics.** CORDIS project IC15961003 (https://cordis.europa.eu/project/id/IC15961003):
  laser photoacoustic assessment of honey, dairy, oil and juice, 1997–1999, with no results
  published on the page. Lab lasers only, so not phone-reproducible. The Hernández-Aguilar review
  page returned 404.
- Not found or not read: the Pirhadi infrared review (jbcpm.com), the AZoM 2017 article (it most
  likely covered Hu et al. 2017 above), the Spectroscopy Online article "A look at spectroscopy and
  food adulteration" (404), and UT Dallas READ (a chemical biosensor on a strip, not optical).

### Cultivated meat

- **Nixon G., O'Hara L., Burns M., "Review of analytical methods for cell-cultivated products", UK
  FSA 2026.** https://science.food.gov.uk/article/167297-review-of-analytical-methods-for-cell-cultivated-products
  — *Read (about a third verbatim, the rest summarised).* No validated method. A weight-of-evidence
  approach is recommended. Spectroscopy was proposed but not evaluated. Microscopy (cell uniformity)
  and DSC are possible signals. Adulteration "is highly likely" in both directions. No published
  case studies.
- Search for spectroscopy that distinguishes cultivated from conventional meat: we found none. The
  only results were production monitoring with process Raman, and conventional species
  discrimination.

### Consumer scanners (why they didn't reach shoppers)

- **SCiO / Consumer Physics** (https://scionir.com/): pocket NIR, now sold to businesses only
  (grain, feed, dairy).
- **Tellspec** (https://tellspec.com/): NIR at 900–1700 nm, which "needs to touch the sample"; glass
  "will typically be too thick". Now B2B. FAQ: "we don't have the ability to analyse just any food.
  Adding new ones is a special project."
- **Bia Analytical** (https://bia-analytical.com/): NIR/FTIR authenticity for herbs and spices,
  sold to retailers, manufacturers and authorities. We couldn't confirm the reported trinamiX
  partnership on either company's pages.
- Lesson: each one ended up with a business buyer that has a repeat, costed need, and reference
  data was the work that never ended. Sift's library has to be cheap to grow: every Researcher-mode
  scan of a known sample adds to it.
