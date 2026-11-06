# uic-well-inventory
This repository contains the source code used for development of a CONUS-wide inventory of UIC injection wells.


## Generating the Inventory
1. **Install dependencies.** The dependencies for this repository are listed in [`environment.yml`](environment.yml).
```
conda env create -f environment.yml
conda activate uic
```
2. **Download PLSS shapefile**. Execution of this code is reliant on a shapefile downloaded from Bureau of Land Management for PLSS Polygons. This file is too large for GitHub storage, so you must download it directly from BLM at [this link](https://gbp-blm-egis.hub.arcgis.com/datasets/283939812bc34c11bad695a1c8152faf/about). The associated folder should be labeled `blm_plss.gdb` and stored in the [`shapefiles/`](data/shapefiles/) directory.
3. **Run `etl`***. Run the following command(s) from the repository root.
```
# to build complete inventory
python -m etl.run

# to process specific files
python -m etl.run al_ii al_iii-v # list out stems for all files you'd like to process (see data/raw_data for available files)
```

----

# PROCESSING NOTES AND TODO

well_subtypes.xlsx - provided in epa4-epa8_all.xlsx and used to code all well subtypes. Added 0X to classify non-injection wells.

# Hierarchies in Data Sourcing

**well_id**
1. API Number
2. WACS ID
3. Permit Number
4. Well ID
5. Well Name
6. Site ID
7. Site Name

**well_depth_ft**
General Rule: Prioritize column with the most non-null values
1. LTD
2. DTD
3. MD
4. TVD
5. TIZ
6. UK


Legend:
- DTD = Driller's Total Depth
- LTD = Logger's Total Depth
- TVD = Total Vertical Depth
- MD = Measured Depth (Total Depth)
- TIZ = Top of Injection Zone
- UK = Unknown Depth Measurement Type


**operator**
1. Company
2. Permittee
3. Lease Name
4. Site Name

**date**
1. Status Date
2. Spud Date
3. Permit Date (approved)
4. Permit Expiration Date
5. Application Date
6. Completion Date
7. First Production Date

# Processing Notes
- (NO ACTION NECESSARY UNLESS ERROR) crosswalk - if value is not in crosswalk keys, return null (check if this is default)

# Field Post Processing to Implement


# Sheet Post Processing Notes


# Steps for Spec Automation
1. Read excel file to understand each sheet in the workbook and what each sheet contains.
2. Set up a template spec file (.yaml) based on spec_template.yaml.
3. Determine the appropriate mode to use to extract the information for each field. See mode_reference.yaml for details on what each mode does and how to set up the field spec dictionaries.

# Location Flags
- UKCRS - Unknown CRS, assumed NAD83
- OOB - reported or calculated coordinates are out of US bounds, assumed invalid or erroneous data entry
- OOSB - reported or calculated coordinates are out of state bounds (but still onshore), assumed invalid or erroneous data
- CCTR - coordinates unavailable or invalid; estimated as county centroid.
- SCTR - coordinates unavailable; estimated as centroid of PLSS Section
- RCTR - coordinates unavailable; estimated as centroid of PLSS Range
- ADDR - coordinates unavailable; geocoded from address
- NOMTCH - no geocode match available

###### TODO
- Add remaining yamls
- Figure out unique ID schema (state alpha, geoid, well class, ?)
- Update README




