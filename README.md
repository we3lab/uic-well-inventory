# uic-well-inventory
This repository contains the source code used for development of a CONUS-wide inventory of UIC injection wells.

## Generating the Inventory
1. **Install dependencies.** The dependencies for this repository are listed in [`environment.yml`](environment.yml).
```
conda env create -f environment.yml
conda activate uic
```
2. **Download shapefiles**. Execution of this code is reliant on several shapefiles that are too large for GitHub file storage, and thus must be downloaded directly:
- US County Boundaries: Download from [US Census Bureau TIGER/Line Shapefiles](https://www2.census.gov/geo/tiger/TIGER2026/COUNTY/tl_2026_us_county.zip) and save to [`shapefiles/`](data/shapefiles/).
- US State Boundaries: Download from [US Census Bureau TIGER/Line Shapefiles](https://www2.census.gov/geo/tiger/TIGER2026/COUNTY/tl_2026_us_state.zip) and save to [`shapefiles/`](data/shapefiles/).
- PLSS Boundaries: Download from [Bureau of Land Management](https://gbp-blm-egis.hub.arcgis.com/datasets/283939812bc34c11bad695a1c8152faf/about), rename to `blm_plss.gdb` and save to [`shapefiles/`](data/shapefiles/).

Execution of this code is reliant on a shapefile downloaded from Bureau of Land Management for PLSS Polygons. This file is too large for GitHub storage, so you must download it directly from BLM at [this link]. The associated folder should be labeled `blm_plss.gdb` and stored in the  directory.
3. **Run `etl`***. Run the following command(s) from the repository root.
```
# to build complete inventory
python -m etl.run

# to process specific files
python -m etl.run al_ii al_iii-v # list out stems for all files you'd like to process (see data/raw_data for available files)
```






