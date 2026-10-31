# uic-well-inventory
Source code for development of a CONUS-wide database of UIC injection wells

Generate by running `python -m etl.run` from root directory


Code is reliant on shapefile downloaded from Bureau of Land Management for PLSS Polygons:
https://gbp-blm-egis.hub.arcgis.com/datasets/283939812bc34c11bad695a1c8152faf/about
Too large for GitHub - download to shapefiles/ directory


well_subtypes.xlsx - provided in epa4-epa8_all.xlsx and used to code all well subtypes. Added 0X to classify non-injection wells.

# Hierarchies in Data Sourcing

**well_id**
1. API Number

**well_depth_ft**
General Rule: Prioritize column with the most non-null values
1. LTD
2. DTD
3. MD
4. TVD


Legend:
- DTD = Driller's Total Depth
- LTD = Logger's Total Depth
- TVD = Total Vertical Depth
- MD = Measured Depth


**operator**
1. Company
2. 

**date**
1. Spud Date
2. Permit Date
3. First Production Date
4. Status Date

# Processing Notes
- crosswalk - if value is not in crosswalk keys, return null (check if this is default)
- lookup - make sure values are all same type (probs string)

# Post Processing Notes
- coordinates
    - cast to float
    - Make sure longitude is negative
- epa_region
    - cast to single type
- county_name
    - match to us_counties somehow (check for identical match among counties in state and otherwise look for similar and have user verify)
- geoid
    - zfill to 5 digits and cast to string
- well_subtype & well_subtype_desc
    - 
- well_class
    - Convert Class 0 to None
    - Convert numbers to numerals
- date
    - process to string or date object but make sure uniform format



# Steps for Spec Automation
1. Read excel file to understand each sheet in the workbook and what each sheet contains.
2. Set up a template spec file (.yaml) based on spec_template.yaml.
3. Determine the appropriate mode to use to extract the information for each field. See mode_reference.yaml for details on what each mode does and how to set up the field spec dictionaries.

###### YOU ARE HERE
- Implement processing notes
- Add a few more yamls
- Implement post-processing
- Add remaining yamls