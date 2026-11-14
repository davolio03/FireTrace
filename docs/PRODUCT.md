# FireTrace Explorer — product and evidence boundary

**Challenge:** NASA Space Apps Challenge 2026, *Dancing with the SARs*. The [proposal v1.1](propuesta.md) is the in-repo scope/scientific source. Its reported data checks are not new verification by this documentation.

**Primary user:** a post-fire impact analyst who needs to inspect radar change and its evidence before interpreting a map. The fixed implementation stack and executable interfaces are described in [ARCHITECTURE](ARCHITECTURE.md) and [CONTRACTS](CONTRACTS.md); they do not prove an application exists.

## P0: one case, one complete journey

Use **Plaskett Fire, Big Sur, California, 2026** only. NISAR is primary; no substitute satellite in the final scientific result. Target demonstration: **90–120 seconds**.

1. Open the case overview: location, fire start, observation dates and sources.
2. Compare aligned before/after HH and HV observations at the same map extent.
3. Toggle continuous **Observed radar changes** with its legend.
4. Independently toggle the **Official fire perimeter** and inspect discrepancies.
5. Select a pixel without requiring a threshold mask; inspect actual values, method, valid coverage, provenance and limitations.

The proposal also describes region inspection. The current executable API defines point inspection only; region aggregation needs a separately approved contract extension, not an invented endpoint.

A large radar change is **not confirmed fire, burned area or severity**. Moisture, terrain, acquisition geometry, vegetation and other disturbances may explain changes. No confidence percentage is valid without calibrated independent evaluation.

## Case evidence: reported, not reverified here

| Observation (UTC) | NASA CMR granule | Absolute orbit |
| --- | --- | --- |
| Before: 2026-08-16 02:56:39 | `G4284560161-ASF` | 5504 |
| After: 2026-10-03 02:56:38 | `G4340499432-ASF` | 6196 |

- **Radar:** provisional `NISAR_L2_GCOV_PROVISIONAL_V1`, frequency A, `HHHH`/`HVHV` power displayed as HH/HV; track 42, frame 70, descending. Harmony reportedly exported four full-scene GeoTIFFs, with the rectangular crop read locally, not requested as a Harmony spatial subset. The original HDF5 was not inspected.
- **Grid:** the proposal reports a common 10 m EPSG:32610 grid and **1,948,374 / 1,948,374** finite positive pixels in the crop. That is reported input availability, not burned area, terrain-quality assurance or a settled product coverage denominator.
- **Event/reference:** CAL FIRE reports a start date of 2026-08-26. WFIGS **58728**, a public/approved multipolygon in EPSG:4326 dated **2026-09-14 20:44 UTC**, reportedly lies within both footprints. It predates the after observation and is neither a verified final perimeter nor pixel-level ground truth.
- **Research:** Döweler, Leuzinger and Bader report AUC-ROC **0.984 in their evaluation, not FireTrace's**. Their granule IDs/full method were not reproduced by the team; our after observation postdates that preprint. RAVG publication is reported, but the individual product remains unverified.

Source links, acquisition details and research references are retained in [proposal §§5, 10 and 17](propuesta.md), not replaced by mock fixture values.

## Acceptance evidence to collect — none claimed passed

| ID | Observable outcome | Required evidence |
| --- | --- | --- |
| P0-01 | One case identifies products, dates, polarizations, geometry and reference source/date. | Compare displayed metadata/provenance with identified inputs. |
| P0-02 | Pan/zoom and before/after comparison align; SAR, change and perimeter toggle independently with legends. | Known-location alignment check and viewer rehearsal. |
| P0-03 | Continuous HH/HV change comes from a documented calculation, not a painted fire classification. | Recompute selected real values with agreed method/tolerance. |
| P0-04 | Coverage excludes invalid input and exposes domain, denominator and units. | Invalid-input tests and arithmetic against the approved AOI definition. |
| P0-05 | Point inspector shows before/after HH/HV dB, signed changes, method, location, reference relation and sources. No-data has no fabricated value/confidence. | Compare inside, outside, invalid and out-of-AOI selections with numerical products. |
| P0-06 | Provenance can regenerate a result; reference timing and physical confounds are visible. | Reproduce an artifact from recorded inputs/configuration/revision. |
| P0-07 | Complete journey uses precomputed artifacts without login, downloads or training. | Timed 90–120 second rehearsal and tested local fallback. |

Contracts/fixtures support parallel development only. Synthetic contract validation cannot satisfy real-data acceptance criteria. Named ownership is in [TEAM](TEAM.md); actual run evidence belongs in [DEMO](DEMO.md).

## P1 and excluded scope

Only after integrated P0: optional **Highlighted radar changes** with explicit threshold/smoothing, sensitivity analysis, flagged area and spatial agreement; baseline-versus-CV/DL experiments with honest evaluation; dedicated polarization comparison, extra dates for the same event, exports and independently verified optical/RAVG context.

Flagged area is not burned area; IoU against an operational perimeter is agreement, not classification accuracy. One case does not establish generalization. Avoid spatial leakage between neighboring training/test patches.

Excluded: Timber/parallel fire cases, global on-demand processing, arbitrary scene downloads, active-fire alerts, emergency operations, economic losses, future-fire prediction, multiyear recovery and operational severity estimation.

## Remaining human decisions

The stack and PNG/API interface shape are fixed; they are not all TBD. Real processing still needs an approved AOI/rasterization/coverage definition, robust normalization parameters and degenerate-case behavior, defensible color ranges/resampling, confound handling and comparison tolerances. Hosting/budget, named reviewers, attribution/licensing and official submission/AI-use rules also need confirmation. See [CONTRACTS](CONTRACTS.md).
