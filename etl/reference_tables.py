#######################################################################################

# FILE NAME: reference_tables.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

# This script loads and caches reference tables used during field processing

# Available Reference Tables:
#   - us_states       (conus_state_boundaries.geojson) — used for spatial state_alpha
#                     lookups. Loaded as a GeoDataFrame for point-in-polygon queries.
#   - us_counties     (conus_county_boundaries.geojson) — used for spatial and tabular
#                     county/geoid lookups. Loaded as a GeoDataFrame so it can serve
#                     both point-in-polygon spatial queries and key-based tabular joins.
#                     state_alpha is joined in from us_states (via statefp) at load time
#                     so that county name lookups can be disambiguated by state.
#   - blm_plss        (blm_plss.gdb) — used for geocoding PLSS township/range/section 
#                     descriptions to coordinates. Loaded as a GeoDataFrame.
#   - uic_authority   (uic_authority.xlsx) — maps (state_alpha, well_class) pairs to
#                     primacy agency. Used for composite-key tabular lookups.
#   - well_subtypes   (well_subtypes.xlsx) — maps epa_well_subtype codes to well_class
#                     and descriptive labels. Used for tabular lookups and subtype
#                     validation.


# All tables are loaded once at startup and held in module-level variables so that
# repeated calls across sheets and files do not re-read from disk.

# Expected file locations (relative to the project data/ directory):
#   data/shapefiles/conus_state_boundaries.geojson
#   data/shapefiles/conus_county_boundaries.geojson
#   data/shapefiles/blm_plss.gdb
#   data/supporting_data/uic_authority.xlsx
#   data/supporting_data/well_subtypes.xlsx

#######################################################################################

from pathlib import Path

import pandas as pd
import geopandas as gpd

import os
os.environ["OGR_ORGANIZE_POLYGONS"] = "SKIP" # improve load time for blm_plss.gdb by skipping interior rings of polygons

from .utils import *

# container for all loaded reference tables
class Refs:
    def __init__(self, us_states, us_counties, blm_plss, uic_authority, well_subtypes):
        self.us_states = us_states
        self.us_counties = us_counties
        self.blm_plss = blm_plss
        self.uic_authority = uic_authority
        self.well_subtypes = well_subtypes

    def __contains__(self, key):
        return hasattr(self, key)

    def __getitem__(self, key):
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

cached_refs: Refs | None = None

# load all reference tables and return a Refs instance
def load():
    # check if already loaded
    global cached_refs
    if cached_refs is not None:
        return cached_refs
    
    # directories for reference tables
    shapefiles_dir = Path(PROJECT_ROOT / "data" / "shapefiles")
    supporting_data_dir = Path(PROJECT_ROOT / "data" / "supporting_data")

    # load reference tables
    us_states = gpd.read_file(shapefiles_dir / "conus_state_boundaries.geojson")[["state_alpha", "state_name", "statefp", "geometry"]].to_crs(TARGET_CRS)
    us_counties = gpd.read_file(shapefiles_dir / "conus_county_boundaries.geojson")[["geoid", "statefp", "county_name", "geometry"]].to_crs(TARGET_CRS)
    us_counties = us_counties.merge(us_states[["statefp", "state_alpha"]], on="statefp", how="left") # add state alpha to counties df
    blm_plss = gpd.read_file(shapefiles_dir / "blm_plss.gdb", layer="PLSSFirstDivision").to_crs('EPSG:3857')
    blm_plss.index = blm_plss['FRSTDIVID'].astype(str)
    blm_plss = blm_plss.drop(columns=['FRSTDIVID'])
    uic_authority = pd.read_excel(supporting_data_dir / "uic_authority.xlsx", dtype=str)
    well_subtypes = pd.read_excel(supporting_data_dir / "well_subtypes.xlsx", dtype=str)

    # cache and return
    cached_refs = Refs(us_states, us_counties, blm_plss, uic_authority, well_subtypes)
    return cached_refs

def reset():
    # clear cached reference tables
    global cached_refs
    cached_refs = None