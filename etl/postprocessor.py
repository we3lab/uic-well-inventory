#######################################################################################

# FILE NAME: postprocessor.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: November 2026

# Applies per-field and per-sheet post-processing corrections after mode functions
# have run.

# FIELD_POSTPROCESSORS_DISPATCH - dict keyed by field name. Each value is a
# function that takes a series, any other resolved fields, and the reference tables
# dict. Used for direct value corrections that only need the current field and already-
# resolved fields.

# SHEET_POSTPROCESSORS - list of functions that take a dataframe and the reference 
# tables dict. Used for corrections that require multiple fields or the entire sheet.

#######################################################################################

import re
import difflib

import numpy as np
import pandas as pd
import geopandas as gpd

from pathlib import Path
from .utils import *

##############################################################
### FIELD POSTPROCESSORS
##############################################################

FIELD_POSTPROCESSORS_DISPATCH = {}

def postprocess_coordinates(coords_df, _resolved, refs):
    # takes coords_df instead of series since multiple fields are at play here

    # cast all coordinates to float
    coords_df['latitude'] = coords_df['latitude'].astype(float)
    coords_df['longitude'] = coords_df['longitude'].astype(float)

    # make sure sign of longitude is negative
    coords_df['longitude'] = coords_df['longitude'].apply(lambda x: -abs(x))

    # if coordinates are significantly outside the boundaries of the US, set to NaN and flag
    oob_buffer_deg = 2.0 # degrees of buffer around CONUS borders in all directions (1 degre = ~100 km)
    county_df = refs['us_counties']
    conus_buffer = county_df.union_all().buffer(oob_buffer_deg)
    points = gpd.GeoSeries(gpd.points_from_xy(coords_df['longitude'], coords_df['latitude']), crs=TARGET_CRS)
    has_coords = coords_df['latitude'].notna() & coords_df['longitude'].notna()
    out_of_bounds = has_coords & ~points.within(conus_buffer)
    coords_df.loc[out_of_bounds, ['latitude', 'longitude']] = np.nan
    coords_df.loc[out_of_bounds, 'location_flag'] = 'OOB'

    return coords_df

FIELD_POSTPROCESSORS_DISPATCH['coordinates'] = postprocess_coordinates
    
##############################################################

def postprocess_epa_region(series, _resolved, _refs):
    # cast to int and set invalid values to NaN
    series = series.astype(float)
    series = series.apply(lambda x: int(x) if x in range(1, 11) else np.nan)
    return series

FIELD_POSTPROCESSORS_DISPATCH['epa_region'] = postprocess_epa_region

##############################################################

def postprocess_county_name(series, resolved, refs):
    county_df = refs['us_counties']
    state_alpha_series = resolved.get('state_alpha')

    def _normalize_county(name): # function to normalize county names for matching
        if pd.isna(name):
            return None
        name = str(name).lower().strip()
        name = re.sub(r'\s+(county|parish|borough|municipality|census area)\s*$', '', name)
        name = re.sub(r'\bst\.\s+', 'saint ', name)
        name = re.sub(r'\bste\.\s+', 'sainte ', name)
        name = re.sub(r"[.\-']", ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    # build lookup dictionaries from reference county names
    # pass 1: (state_alpha, normalized_name) -> canonical county_name
    # pass 2: (state_alpha, no_spaces_name)  -> canonical county_name
    # pass 3: state_alpha -> [normalized county names] for fuzzy matching
    ref = county_df[['state_alpha', 'county_name']].copy()
    ref['normalized'] = ref['county_name'].apply(_normalize_county)
    ref['no_spaces']  = ref['normalized'].str.replace(' ', '', regex=False)

    pass1_lookup = dict(zip(zip(ref['state_alpha'], ref['normalized']), ref['county_name']))
    pass2_lookup = dict(zip(zip(ref['state_alpha'], ref['no_spaces']),  ref['county_name']))
    pass3_candidates   = ref.groupby('state_alpha')['normalized'].apply(list).to_dict()

    # match each county name in the series to the canonical county name using the lookups
    def _match(county_name, state_alpha):
        normalized = _normalize_county(county_name)
        if normalized is None:
            return np.nan
        # pass 1
        if (state_alpha, normalized) in pass1_lookup:
            return pass1_lookup[(state_alpha, normalized)]
        # pass 2
        if (state_alpha, normalized.replace(' ', '')) in pass2_lookup:
            return pass2_lookup[(state_alpha, normalized.replace(' ', ''))]
        # pass 3 — fuzzy
        state_candidates = pass3_candidates.get(state_alpha, [])
        matches = difflib.get_close_matches(normalized, state_candidates, n=1, cutoff=0.85)
        if matches:
            return pass1_lookup[(state_alpha, matches[0])]
        return np.nan

    return pd.Series(
        [_match(county, state) for county, state in zip(series, state_alpha_series)],
        index=series.index
    )

FIELD_POSTPROCESSORS_DISPATCH['county_name'] = postprocess_county_name

##############################################################

def postprocess_geoid(series, _resolved, refs):
    # geoid is a 5-digit string, with leading zeros if necessary
    series = series.astype(str).str.zfill(5)
    # check if geoid exists in reference table
    valid_geoids = set(refs['us_counties']['geoid'])
    series = series.apply(lambda x: x if x in valid_geoids else np.nan)
    return series

FIELD_POSTPROCESSORS_DISPATCH['geoid'] = postprocess_geoid

##############################################################

def postprocess_well_class(series, _resolved, _refs):
    # make sure all values are in format of roman numerals and valid
    arabic_to_roman = {
        "1": "I",
        "2": "II",
        "3": "III",
        "4": "IV",
        "5": "V",
        "6": "VI",
    }   
    def _normalize_well_class(value):
        if pd.isna(value):
            return np.nan
        value = str(value).strip()
        return arabic_to_roman.get(value, value.upper())

    return series.apply(_normalize_well_class)

FIELD_POSTPROCESSORS_DISPATCH['well_class'] = postprocess_well_class

##############################################################

def postprocess_date(series, _resolved, _refs):
    # convert to datetime, coerce errors to NaT
    series = pd.to_datetime(series, errors='coerce', format='mixed')
    return series

FIELD_POSTPROCESSORS_DISPATCH['date'] = postprocess_date

##############################################################
### SHEET POSTPROCESSORS
##############################################################

def postprocess_sheet(df, refs):

    # if coordinates are NaN but county is provided, return county centroid coordinates and flag
    missing_coords = df['latitude'].isna() & df['longitude'].isna() & df['geoid'].notna()
    county_df = refs['us_counties']

    if missing_coords.any():
        geoid_to_centroid = county_df.to_crs('EPSG:3857').set_index('geoid').geometry.centroid.to_crs(TARGET_CRS) # convert to projected CRS for centroid calculation, then back to target CRS
        missing_geoids = df.loc[missing_coords, 'geoid']
        centroids = missing_geoids.map(geoid_to_centroid)
        df.loc[missing_coords, 'latitude']   = centroids.apply(lambda p: p.y if pd.notna(p) else np.nan).values
        df.loc[missing_coords, 'longitude']  = centroids.apply(lambda p: p.x if pd.notna(p) else np.nan).values
        df.loc[missing_coords, 'location_flag'] = 'CCTR'
    
    return df