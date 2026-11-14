# ⚖️ Unresolved Scientific & Engineering Decisions

**Project:** Harvard EPS 55 Final Project (in collaboration with Clara Yoon, USGS)  
**Destination Repository:** `MMI-Gram`  
**Date:** November 14, 2026  
**Status:** Open Decision Register for Review by User & Clara Yoon  

---

## 1. Scientific Seismological Decisions

### Decision S1: Handling Surface Fault Rupture vs. Pure Ground Shaking
- **The Issue:** In the 2025 Myanmar earthquake, several reconnaissance observations (e.g., GP Energy solar farm in `page-022.pdf`, street median shear in `page-026.pdf`) exhibit primary strike-slip surface fault displacement (~1 meter offset cutting directly through foundations).
- **The Conflict:** The Modified Mercalli Intensity (MMI) scale was historically conceived to measure ground shaking effects caused by seismic waves, rather than primary fault rupture displacement. If extreme surface fault offset is coded purely as MMI X, empirical Ground Motion Prediction Equations (GMPEs)—which predict wave ground motion as a function of $R_{rup}$—will overpredict ground motion away from the fault.
- **Proposed Solution:** The unified estimator should output two distinct tags:
  1. `mmi_estimation`: Intensity rating based on observable damage.
  2. `primary_damage_mechanism`: Categorized as `GROUND_SHAKING`, `SURFACE_FAULT_RUPTURE`, or `LIQUEFACTION_GROUND_FAILURE`.
  - For ShakeMap v4 export, observations flagged with `SURFACE_FAULT_RUPTURE` can either carry a higher standard deviation ($\sigma_{\text{MMI}}$) or be flagged in `intensity_flag` to alert ShakeMap operators.
- **Decision Needed from Clara / Seismologists:** Should ShakeMap `*_dat.json` include surface-rupture observations directly in the macroseismic stationlist, or should they be segregated into a geological rupture observation layer?

---

### Decision S2: Intensity Scale Upper Bound: MMI X vs. MMI XII
- **The Issue:** Historically, Wood & Neumann (1931) and Richter (1958) defined MMI from I to XII. However, USGS ShakeMap and the DYFI system conventionally cap macroseismic intensity grids at X (or collapse intensities X, XI, XII into X+ because structural damage saturates at complete collapse of ordinary structures).
- **The Current Limitation:** MMI-Gram's current reference database and QC engine historically enforced an upper bound of $10.0$ (`FLAG_MMI_OUT_OF_RANGE` if $> 10.0$). However, the standard Modified Mercalli scale extends to XII, and catastrophic ground failure, bridge destruction, or total destruction can exceed X.
- **Adopted Resolution & Action:**
  1. Document our current I–X reference definitions as a known versioned limitation (`mmi_scale_v1_usgs_10level`).
  2. For Stage 1, provide versioned definitions supporting both the 10-level USGS operational scale and the complete 12-level Wood & Neumann (1931) / Richter (1958) scale (`mmi_scale_v2_full_12level`).
  3. Prior to full-dataset validation, formulate a formal mapping and calibration rule for intensities XI and XII when exporting to USGS ShakeMap v4 non-instrumented macroseismic observation format (e.g. flagging extreme cataclysmic observations or bounding ShakeMap station intensity with explicit operator notes).

---

### Decision S3: Representation of Negative / Irrelevant Evidence (`NOT_ESTIMABLE`)
- **The Issue:** For briefing cover slides, index maps, administrative summaries, or pages without usable earthquake evidence (e.g., Clara's `page-8.pdf`), how should the output be evaluated and recorded?
- **Correction Incorporated:** The input relevance gate must assess whether there is **usable earthquake shaking or damage evidence, including credible textual eyewitness observations or structural reports**, rather than simply checking whether photographs exist. Non-damage or purely administrative/methodology slides lacking shaking or damage descriptions must be flagged before estimation.
- **Adopted Resolution:** Use `mmi_estimation: null` and assign `evaluation_status: "NOT_ESTIMABLE"` with `exclusion_reason: "NO_OBSERVABLE_SHAKING_OR_DAMAGE_EVIDENCE"`. These records are preserved in `excluded_inputs.json` for full scientific auditability and excluded from ShakeMap `*_dat.json` features. Numeric values like `0.0` or arbitrary defaults are strictly prohibited.

---

### Decision S4: Uncalibrated Model Confidence vs. ShakeMap Observation Uncertainty
- **The Issue:** LLMs generate self-reported confidence values that are not empirically calibrated probabilities or observational standard deviations.
- **Correction Incorporated:** Do not use uncalibrated Gemini confidence as a calibrated ShakeMap MMI observation uncertainty. Clara's formula ($\sigma_{\text{MMI}} = 0.35 + [1.0 - \text{conf}] \times 0.70$) is preserved strictly for paired benchmark comparison with her historical outputs, but is explicitly documented as **uncalibrated and not scientifically validated**. Formal observation weighting for USGS ShakeMap ingestion requires empirical variance calibration against DYFI and ground motion stations.

---

## 2. Engineering & Architectural Decisions

### Decision E1: Embedded Database Selection: DuckDB vs. SQLite vs. Flat Files
- **The Issue:** Clara's `quake_agent` uses DuckDB (`event.duckdb`) with a fallback to SQLite. MMI-Gram previously exported to flat JSON and CSV.
- **The Tradeoff:**
  - DuckDB is blazing fast for OLAP analytical queries, spatial queries, and columnar joins across thousands of reconnaissance points.
  - However, in certain sandboxed or resource-constrained environments, DuckDB binary wheels can occasionally encounter platform issues.
- **Proposed Solution:** Implement `LocalStorageRepository` supporting DuckDB with automatic, transparent fallback to standard library `sqlite3` when `duckdb` is not installed.
- **Decision Needed:** Confirm whether DuckDB should be an optional dependency or a pinned requirement in `pyproject.toml`.

---

### Decision E2: Geocoding API Dependency Management
- **The Issue:** Resolving shortened Google Maps URLs (`maps.app.goo.gl`) that do not embed coordinates in their URL string requires expanding the HTTP redirect and, in some cases, querying the Google Geocoding API.
- **The Tradeoff:**
  - Requiring a `GOOGLE_MAPS_API_KEY` introduces an external credential and billing dependency.
  - Relying solely on regex coordinate parsing causes documents with only mapping links (e.g. `page-062.pdf`) to fail geolocation extraction.
- **Proposed Solution:**
  1. Priority 1: Expand shortened URL via HTTP `HEAD` or unshortener; parse coordinates if present in the expanded redirect URL (zero API cost).
  2. Priority 2: If coordinates are not in the URL, query Google Geocoding API if `GOOGLE_MAPS_API_KEY` is provided in `.env`.
  3. Fallback: If no API key is provided, record location as `"Unknown"` and route to Human Review Queue.
- **Decision Needed:** Approve this 3-tier geocoding fallback architecture.

---

### Decision E3: Pacing, Rate Limits, and Quota Handling for Gemini 3.8 Flash
- **The Issue:** Gemini 3.8 Flash HIGH thinking uses significantly more internal thought tokens than standard models. When processing a batch of 50-100 StEER pages, researchers can quickly encounter RPM (requests per minute) or TPM (tokens per minute) quota limits on Google AI Studio.
- **The Conflict:** Clara's prototype addressed rate limits by silently failing over to `gemini-3.6-flash` and `gemini-3.5-flash-lite`. MMI-Gram's philosophy rejects silent model switching.
- **Proposed Solution:**
  - Add an explicit `--pace` flag (e.g., `--pace 4.0` seconds between pages).
  - Implement exponential backoff retry on HTTP 429 (`ResourceExhausted`).
  - If retries are exhausted, pause the batch and output an actionable notice to the user, rather than silently degrading to an inferior model.
- **Decision Needed:** Confirm that pausing or pacing is preferred over silent model switching.

---

### Decision E4: Distinguishing Offline Development from Live API Charges
- **The Issue:** Confusion can arise between offline mock/fixture development (which is 100% free and incurs zero external network requests) and live execution against Google AI Studio or Google Maps Geocoding.
- **Correction Incorporated:** 
  - **Offline Development & Unit Tests:** Incur **$0.00** charges, require no API keys, and run purely against local files, synthetic fixtures, and local versioned MMI scale resources.
  - **Live AI Studio Inference:** Billed according to Gemini 3.8 Flash token pricing (input tokens, cached prompt tokens, output candidate tokens, and internal thought tokens). Extended thinking (`HIGH`) increases token volume and therefore compute cost.
  - **Google Maps Geocoding API:** Incurs per-request charges according to Google Maps Platform pricing if requests exceed free tier credits. URL unshortening without Geocoding API remains zero-charge.
  - **Governance:** Live API calls are strictly gated behind explicit command-line opt-in (`--live` or `allow_live_api=True`) and explicit provider flags (`--provider ai_studio` or `--provider vertex_ai`). The system never executes live API calls by default.
