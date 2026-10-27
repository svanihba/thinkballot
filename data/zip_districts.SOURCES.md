# zip_districts.json: sources and method

Built by `scripts/build_zip_districts.py` (standard library only). Downloads are cached in
`build/zip_districts_cache/` (gitignored). Rebuild with:

    python3 scripts/build_zip_districts.py

## Which maps apply to the 3 Nov 2026 election

- **Congress:** the AB 604 map (Ch. 96, Stats. 2025), adopted by Proposition 50 at the
  4 Nov 2025 statewide special election. Prop 50 passed 64.4% to 35.6%; the Secretary of State
  certified the result on 12 Dec 2025
  (https://elections.cdn.sos.ca.gov/sov/2025-special/sov/complete-sov.pdf). A federal panel
  declined to block the map in Jan 2026, and the US Supreme Court denied the emergency
  application in Feb 2026. The 2021 Commission congressional map is **not** used.
- **State Senate and Assembly:** the 2021 Citizens Redistricting Commission final maps.

## Sources

| What | URL |
|---|---|
| Congressional, block to district (AB 604), Statewide Database | https://statewidedatabase.org/pub/data/d25/AB604.zip |
| Same plan, Senate Elections and Constitutional Amendments Committee (cross-check) | https://selc.senate.ca.gov/media/604 |
| State Senate, block to district (2021 CRC final) | https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-4.zip |
| Assembly, block to district (2021 CRC final) | https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-6.zip |
| Census 120th Congress BEF (cross-check) | https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/120-congressional-district-befs/cd120.zip |
| Census 2026 State Senate BEF (cross-check) | https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/2026-state-legislative-bef/sldu26.zip |
| Census 2026 Assembly BEF (cross-check) | https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/2026-state-legislative-bef/sldl26.zip |
| Census 2020 ZCTA to block relationship | https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_tabblock20_natl.txt |
| 2020 Census P.L. 94-171, California (block population P1_001N) | https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/California/ca2020.pl.zip |
| Census 2020 block assignment file (block to place) | https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST06_CA.zip |
| Census 2020 place names | https://www2.census.gov/geo/docs/reference/codes2020/place/st06_ca_place2020.txt |
| Census 2020 county names | https://www2.census.gov/geo/docs/reference/codes2020/cou/st06_ca_cou2020.txt |

The state files and the Census files agree on every one of California's 519,723 blocks for
all three district types; the build stops if they ever disagree.

## Method

1. Each 2020 census block gets a ZCTA, a congressional, Senate and Assembly district, a county
   (from its GEOID) and a Census place (incorporated city/town or CDP).
2. For each ZCTA, each value is the one holding the largest share of the ZCTA's 2020 population
   (land area for the few unpopulated ZCTAs; those rows carry `"weight": "land_area"`).
3. `shares` records that top share per district type; `split` is true when any of them is
   below 95%. `population` is the ZCTA's 2020 population within California.
4. `city` is the Census place with the most people, which can differ from the USPS city name;
   it is empty when most people live outside any Census place.
5. Six ZCTAs outside 90000-96999 that reach slightly into California (89010, 89019, 89060,
   89061, 89439, 97635; 471 people in total) are left out, because the geo service only
   reads 9xxxx ZIPs.

ZIP codes are not district boundaries. A split ZIP needs a full address to be certain.
ZCTAs approximate USPS ZIP delivery areas; PO-box-only ZIPs have no ZCTA and are not listed.
