# References and licences

Every data set, service, software package and document used to build FireTrace, with its licence or terms. FireTrace's own code and documentation are licensed under [Apache 2.0](../LICENSE). Data are not distributed in this repository; the derived products in the GitHub data releases keep the licences and attribution of their sources.

## NASA data

| Data | Use | Citation | Licence |
| --- | --- | --- | --- |
| NISAR Provisional Geocoded Polarimetric Covariance Product, Version 1 (`NISAR_L2_GCOV_PROVISIONAL_V1`), NASA/ISRO, distributed by the Alaska Satellite Facility DAAC | Primary observation: granules `G4284560161-ASF` (2026-08-16) and `G4340499432-ASF` (2026-10-03), frequency A HHHH and HVHV, and the after scene's radar-geometry cubes | [doi:10.5067/NIL2GCOV-P1](https://doi.org/10.5067/NIL2GCOV-P1); granules via [CMR](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4284560161-ASF) | NASA data from a NASA-led mission: openly shared, licensed CC0 unless marked otherwise ([NASA data use guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance)) |
| GPM IMERG Late Precipitation L3 1 day 0.1° × 0.1° V07 (`GPM_3IMERGDL`), NASA GES DISC | Daily precipitation context, 2026-08-16 to 2026-10-03 | Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., Tan, J. (2023). [doi:10.5067/GPM/IMERGDL/DAY/07](https://doi.org/10.5067/GPM/IMERGDL/DAY/07) | Openly shared without restriction under the EOSDIS data use and citation guidance |
| NASA Earthdata Harmony and CMR | Exporting the GCOV layers as GeoTIFF; granule metadata | [Harmony for NISAR](https://hyp3-docs.asf.alaska.edu/nisar-docs/harmony/) | NASA services |
| NASA NISAR mission overview | Mission facts in the guided story (orbit altitude, L-band wavelength) | [science.nasa.gov](https://science.nasa.gov/mission/nisar/mission-overview/) | NASA web content, cited as a reference |

## Space agency partner data (ESA)

| Data | Use | Attribution | Licence |
| --- | --- | --- | --- |
| Copernicus DEM GLO-30, tile `Copernicus_DSM_COG_10_N35_00_W122_00_DEM` | Elevation, slope, hillshade, layover/shadow flags and the story's terrain tiles | "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved" ([doi:10.5270/ESA-c5d3d65](https://doi.org/10.5270/ESA-c5d3d65)) | GLO-30 is freely accessible to the general public under the ESA user licence for the Copernicus DEM, with the attribution above |
| Copernicus Sentinel-2 L2A, scenes `S2A_10SFE_20260830_0_L2A` and `S2B_10SFE_20261015_0_L2A`, via Earth Search (Element 84) on the [AWS Registry of Open Data](https://registry.opendata.aws/sentinel-2-l2a-cogs/) | Optical context (smoke on 2026-08-30, clear sky on 2026-10-15) | "Contains modified Copernicus Sentinel data 2026" | Free, full and open access under the [Sentinel data legal notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) |

## Other data and services

| Source | Use | Attribution | Licence or terms |
| --- | --- | --- | --- |
| NIFC WFIGS Interagency Perimeters YearToDate, OBJECTID 58728 (2026-09-14 20:44 UTC) | Dated reference perimeter for contrast | National Interagency Fire Center ([feature query](https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0/query?where=OBJECTID%3D58728&outFields=*&returnGeometry=true&outSR=4326&f=geojson)) | Public US government open data published by NIFC; no copyright text on the layer |
| OpenStreetMap standard tiles | Basemap in the web map | "© OpenStreetMap contributors", shown on the map | Data under the [Open Database License](https://www.openstreetmap.org/copyright); tile use under the [OSMF tile usage policy](https://operations.osmfoundation.org/policies/tiles/) (light, attributed use; a deployment with heavy traffic needs another tile provider) |
| CAL FIRE incident page | Fire start date (2026-08-26) and location | [fire.ca.gov](https://www.fire.ca.gov/incidents/2026/8/26/plaskett-fire) | Facts cited as a reference |

## Scientific references

- Döweler, Leuzinger and Bader (2026-10-02), preprint on NISAR GCOV HH/HV change for the Timber and Plaskett fires, [SSRN 7553393](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7553393). Methodological reference for the absolute HH/HV log-ratio idea; its AUC-ROC of 0.984 is the authors' result, not FireTrace's.
- Horn, B. K. P. (1981). Hill shading and the reflectance map. *Proceedings of the IEEE*, 69(1), 14-47. Slope and aspect method.
- The robust z-score (median and 1.4826 × MAD) is a standard robust-statistics convention ([change index](methods/change-index.md)).

## Software

Versions are those installed from `uv.lock` and `web/package-lock.json` on 2026-11-15; licences are read from each package's own metadata.

| Package | Version | Licence | Use |
| --- | --- | --- | --- |
| numpy | 2.4.6 | BSD-3-Clause (with 0BSD, MIT, Zlib, CC0-1.0 parts) | Array computation |
| rasterio (with bundled GDAL and PROJ) | 1.4.4 | BSD-3-Clause | Raster I/O and reprojection |
| rio-cogeo | 7.0.4 | BSD-3-Clause | Cloud-optimized GeoTIFFs |
| xarray | 2026.9.0 | Apache-2.0 | Labelled arrays |
| geopandas | 1.2.0 | BSD-3-Clause | Vector data |
| shapely | 2.2.0 | BSD-3-Clause | Geometry |
| scikit-image | 0.26.0 | BSD-3-Clause | Connected regions |
| h5netcdf, h5py | 1.8.3, 3.16.0 | BSD-3-Clause | Reading HDF5/NetCDF (GCOV `.h5`, IMERG) |
| FastAPI | 0.162.7 | MIT | API |
| pydantic | 2.14.3 | MIT | API models |
| jsonschema | 4.26.0 | MIT | Contract validation |
| pytest, ruff | 9.2.0, 0.17.5 | MIT | Tests and lint |
| uv | — | Apache-2.0 or MIT | Python environment |
| React, React DOM | 19.3.1 | MIT | Web UI |
| MapLibre GL JS | 6.18.0 | BSD-3-Clause | Web map |
| TanStack Query | 5.107.1 | MIT | Data fetching |
| Zustand | 5.1.0 | MIT | Shared state |
| Recharts | 3.10.1 | MIT | Charts |
| Tailwind CSS (and `@tailwindcss/vite`) | 4.3.5 | MIT | Styling |
| class-variance-authority | 0.7.1 | Apache-2.0 | Component variants |
| clsx, tailwind-merge | 2.1.1, 3.7.0 | MIT | Class names |
| lucide-react | 1.73.0 | ISC | Icons |
| Vite, `@vitejs/plugin-react` | 8.3.8, 6.3.0 | MIT | Web build |
| TypeScript | 5.9.3 | Apache-2.0 | Types |
| openapi-typescript | 7.13.0 | MIT | Types generated from the OpenAPI contract |
| MSW | 3.0.5 | MIT | MOCK mode |
| Vitest, Testing Library, jsdom | 5.1.0, 16.3.3, 31.0.1 | MIT | Web tests |
| ESLint, typescript-eslint, Prettier | 10.15.0, 8.72.2, 3.10.1 | MIT | Web lint and format |

Transitive dependencies keep their own licences, recorded in the lock files. `web/components.json` configures [shadcn/ui](https://ui.shadcn.com) (MIT) for component generation; no generated shadcn/ui components are in `web/src` as of this commit.

## Tools used to build it

Claude Code (Anthropic), Codex (OpenAI), OpenCode, T3 Code, Engram and the Kanvas board, as declared in [AI_USE](AI_USE.md). They are development tools, not part of the product.
