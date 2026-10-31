#######################################################################################

# FILE NAME: modes.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

# This script implements one processing function for each field mode.

# Each function receives the output field name, the field's spec dict, the raw source
# DataFrame, the dict of the already-resolved output fields (for lookups that depend on
# earlier fields), and the loaded reference tables. Each function returns a pd.Series
# aligned to the source DataFrame's index.

# See mode_reference.yaml for the list of available modes and their specifications.

#######################################################################################

import numpy as np
import pandas as pd
import geopandas as gpd
from geopy.geocoders import ArcGIS
import re
from pathlib import Path

from . import coordinate_conversions as coord_convert
from .utils import *

MODE_DISPATCH = {} # dispatch dictionary to map node names to their processing functions

##############################################################
### NONE
### returns a null Series; field is not present or derivable
##############################################################

def mode_none(_field_name, _spec, df, _resolved, _refs):
    return pd.Series([np.nan] * len(df), index=df.index, dtype=object)

MODE_DISPATCH["none"] = mode_none

##############################################################
### CONSTANT
### returns a Series filled with a single literal value
##############################################################
def mode_constant(_field_name, spec, df, _resolved, _refs):
    return pd.Series([spec["constant"]] * len(df), index=df.index, dtype=object)

MODE_DISPATCH["constant"] = mode_constant

##############################################################
### COLUMN
### copies a source column directly
##############################################################
def mode_column(field_name, spec, df, _resolved, _refs):
    col_name = spec["column"]
    if col_name not in df.columns: # raise error if column doesn't exist in source data
        raise KeyError(f"{field_name}: column {col_name!r} not found in source data")
    else:
        return df[col_name].copy()
    
MODE_DISPATCH["column"] = mode_column

##############################################################
### EXTRACT
### derives a value from a source column via slice or regex
### methods: slilce and regex
##############################################################
def mode_extract(field_name, spec, df, _resolved, _refs):
    # determine extract method
    extract  = spec["extract"]
    col_name = extract["column"]
    method   = extract["method"]

    if col_name not in df.columns: # raise error if column doesn't exist in source data
        raise KeyError(f"{field_name}: column {col_name!r} not found in source data")
    
    col_data = df[col_name].astype(str) # convert to string for extraction

    # slice method - extract substring using start and end indices
    if method == "slice":
        start = extract["slice"]["start"]
        end   = extract["slice"]["end"]
        if end == -1: # handle -1 as a special case for "to the end"
            return col_data.str[start:]
        else:
            return col_data.str[start:end]
    
    # regex method - extract substring using a regular expression
    elif method == "regex":
        pattern = extract["regex"]["pattern"]
        group   = extract["regex"].get("group", 1) # default to first instance if no group provided
        # ensure group is a valid positive integer
        if not isinstance(group, int) or group < 1:
            raise ValueError(f"{field_name}: regex group must be a positive integer")
        # apply regex extraction
        extracted = col_data.str.extract(pattern, expand=True)
        return extracted.iloc[:, group - 1] # return the specified group (0-indexed)

MODE_DISPATCH["extract"] = mode_extract

##############################################################
### CONCAT
### joins multiple source columns with a delimiter
##############################################################
def mode_concat(field_name, spec, df, _resolved, _refs):
    col_names = spec["concat"]["columns"]
    delimiter = spec["concat"].get("delimiter", "")

    # check that all specified columns exist in the source DataFrame
    missing_cols = [col for col in col_names if col not in df.columns]
    if missing_cols:
        raise KeyError(f"{field_name}: columns {missing_cols} not found in source data")
    
    # concatenate the specified columns, handling NaN values by treating them as empty strings
    # and then replacing any resulting empty strings with NaN at the end
    return df[col_names].fillna("").astype(str).agg(delimiter.join, axis=1).replace("", np.nan)

MODE_DISPATCH["concat"] = mode_concat

##############################################################
### CROSSWALK
### maps source column values to output values via an explicit 
### dictionary
##############################################################
def mode_crosswalk(field_name, spec, df, _resolved, _refs):
    col_name = spec["crosswalk"]["column"]
    mapping  = spec["crosswalk"]["map"]

    if not mapping: # raise warning if mapping is empty or null
        raise ValueError(f"{field_name}: crosswalk mapping is empty or null")

    if col_name not in df.columns: # raise warning if column not found
        raise KeyError(f"{field_name}: column {col_name!r} not found in source data")
    
    # raise error if any source values were not mapped
    in_map = df[col_name].isin(mapping.keys())
    unmapped = df[col_name].notna() & ~in_map
    if unmapped.any():
        unmapped_values = df.loc[unmapped, col_name].unique()
        raise ValueError(f"{field_name}: unmapped source values found: {unmapped_values}")
    
    # normalize source values and map keys to uppercase, stripped of whitespace
    normalized_mapping = {str(k).strip().upper(): v for k, v in mapping.items()}
    normalized_source = df[col_name].astype(str).str.strip().str.upper()

    # map values to outputs and fill unmapped values with NaN
    mapped_result = normalized_source.map(normalized_mapping)
    mapped_result = mapped_result.where(df[col_name].notna(), other=np.nan)
    return mapped_result

MODE_DISPATCH["crosswalk"] = mode_crosswalk

##############################################################
### LOOKUP
### returns a value from a reference table by matching
### one already-resolved field
###
### Available Reference tables:
###   us_counties   →  conus_county_boundaries.geojson
###   us_states     →  conus_state_boundaries.geojson
###   uic_authority →  uic_authority.xlsx
##############################################################
def mode_lookup(field_name, spec, df, resolved, refs):
    lookup_spec  = spec["lookup"]
    resolved_col = lookup_spec["column"]
    table_name   = lookup_spec["table"]
    key_field    = lookup_spec["key_field"]
    return_field = lookup_spec["return_field"]

    if resolved is None or resolved_col not in resolved:
        raise KeyError(f"{field_name}: resolved field {resolved_col!r} not found — ensure it is processed before this field")

    if refs is None or table_name not in refs:
        raise KeyError(f"{field_name}: reference table {table_name!r} not found in refs")

    ref_table = refs[table_name].copy() # make a copy to avoid modifying the original reference table

    if key_field not in ref_table.columns:
        raise KeyError(f"{field_name}: key_field {key_field!r} not found in reference table {table_name!r}")

    if return_field not in ref_table.columns:
        raise KeyError(f"{field_name}: return_field {return_field!r} not found in reference table {table_name!r}")

    # build a lookup map from the reference table that maps the resolved column values to the return values
    lookup_map = dict(zip(ref_table[key_field], ref_table[return_field]))
    return resolved[resolved_col].map(lookup_map)

MODE_DISPATCH["lookup"] = mode_lookup

##############################################################
### COMPUTE
### applies an aggregate function (mean, min, max, etc.) across
### multiple numeric source columns within each row
##############################################################
def mode_compute(field_name, spec, df, _resolved, _refs):
    col_names = spec["compute"]["columns"]
    operation = spec["compute"]["operation"]

    # check that all specified columns exist in the source DataFrame
    missing_cols = [col for col in col_names if col not in df.columns]
    if missing_cols:
        raise KeyError(f"{field_name}: columns {missing_cols} not found in source data")
    
    # make sure all specified columns are numeric
    numeric_data = df[col_names].apply(pd.to_numeric, errors='coerce')
    if numeric_data.isnull().all(axis=0).any(): # if any full column is null, assume non-numeric
        raise ValueError(f"{field_name}: one or more specified columns contain all non-numeric values")

    # ensure that the specified method is one of the supported operations
    ops = {
        "mean"  : numeric_data.mean(axis=1),
        "median": numeric_data.median(axis=1),
        "sum"   : numeric_data.sum(axis=1, min_count=1),
        "min"   : numeric_data.min(axis=1),
        "max"   : numeric_data.max(axis=1),
    }
    if operation not in ops:
        raise ValueError(f"{field_name}: unsupported compute operation {operation!r}")
    return ops[operation]

MODE_DISPATCH["compute"] = mode_compute

##############################################################
### REPROJECT
### handles coordinate conversions and projection changes
### returns a DataFrame with latitude and longitude columns
##############################################################
def mode_reproject(field_name, spec, df, _resolved, _refs):
    reproject_spec  = spec["reproject"]
    input_format = reproject_spec["input_format"]
    source_crs = reproject_spec["crs"]
    if source_crs is not None:
        crs_note = "Known CRS"
    else:
        crs_note = "Unknown CRS"
        source_crs = "EPSG:4269" # default to NAD83 if not specified

    # normalize x_columns and y_columns to lists and make sure they all exist
    x_columns = reproject_spec.get("x_columns", [])
    y_columns = reproject_spec.get("y_columns", [])
    if isinstance(x_columns, str):
        x_columns = [x_columns]
    if isinstance(y_columns, str):
        y_columns = [y_columns]

    def _check_cols(*cols):
        for col in cols:
            if col not in df.columns:
                raise KeyError(f"{field_name}: column {col!r} not found in source data")

    # handle different input formats for coordinates
    if input_format == "dd": # decimal degrees, one column for each of latitude and longitude
        lat_col, lon_col = x_columns[0], y_columns[0]
        _check_cols(lat_col, lon_col)
        y = df[lat_col]
        x = df[lon_col]
        conv_note = "Reported"
    elif input_format in ("dms_colon", "dms_compact"): # only one column for each of latitude and longitude
        lat_col, lon_col = x_columns[0], y_columns[0]
        _check_cols(lat_col, lon_col)
        if input_format == "dms_colon":
            delimiter = reproject_spec.get("delimiter", ":")
            y = coord_convert.dms_colon_to_dd(df[lat_col], delimiter=delimiter, errors="coerce")
            x = coord_convert.dms_colon_to_dd(df[lon_col], delimiter=delimiter, errors="coerce")
        else:
            y = coord_convert.dms_compact_to_dd(df[lat_col], errors="coerce")
            x = coord_convert.dms_compact_to_dd(df[lon_col], errors="coerce")
        conv_note = "Converted"
    elif input_format == "dms_expanded":
        # x_columns = [deg, min, sec] for latitude
        # y_columns = [deg, min, sec] for longitude
        if len(x_columns) < 3 or len(y_columns) < 3:
            raise ValueError(
                f"{field_name}: dms_expanded requires 3 columns each in x_columns and "
                f"y_columns ([deg, min, sec]); got {len(x_columns)} and {len(y_columns)}"
            )
        _check_cols(*x_columns[:3], *y_columns[:3])
        fill_missing = reproject_spec.get("fill_missing", False)
        y = coord_convert.dms_expanded_to_dd(
            df[x_columns[0]], df[x_columns[1]], df[x_columns[2]],
            fill_missing=fill_missing,
        )
        x = coord_convert.dms_expanded_to_dd(
            df[y_columns[0]], df[y_columns[1]], df[y_columns[2]],
            fill_missing=fill_missing,
        )
        conv_note = "Converted"

    elif input_format == "northing_easting":
        # x_columns[0] = northing (y-direction), y_columns[0] = easting (x-direction)
        northing_col, easting_col = x_columns[0], y_columns[0]
        _check_cols(northing_col, easting_col)
        x = df[easting_col]
        y = df[northing_col]
        conv_note = "Converted"

    else:
        raise ValueError(
            f"{field_name}: unsupported reproject input_format {input_format!r}"
        )

    # apply crs_transform to all formats
    result = coord_convert.crs_transform(x=x, y=y, crs=source_crs)
    result["latlon_desc"] = f"{conv_note} ({crs_note})"

    return result[["latitude", "longitude", "latlon_desc"]]

MODE_DISPATCH["reproject"] = mode_reproject

##############################################################
### GEOCODE
### converts an address or PLSS description to coordinates
### methods: plss and address
##############################################################
def mode_geocode(field_name, spec, df, _resolved, refs):
    geocode_spec = spec["geocode"]
    method = geocode_spec["method"] # determine if geocoding PLSS or address

    if method == "plss":
        plss_df = pd.DataFrame(index=df.index) # empty dataframe to store PLSS fields by row
        plss_field_dict = geocode_spec["plss_fields"] # mode dict for each field

        # populate temporary df with PLSS fields by row, using the appropriate mode for each field
        for field_name, field_spec in plss_field_dict.items():
            mode = field_spec["mode"]
            if mode not in MODE_DISPATCH:
                raise ValueError(f"{field_name}: unsupported mode {mode!r} for PLSS field {field_name!r}")
            plss_df[field_name] = MODE_DISPATCH[mode](field_name, field_spec, df, _resolved, refs)

        # combine PLSS fields into a single ID code
        plss_pad_dict = {
            'meridian': 2, 
            'township_num': 3, 
            'range_num': 3, 
            'section': 2}

        def _generate_plss_id(row):
            try:
                state = str(row['state']).upper()
                meridian = str(row['meridian']).zfill(plss_pad_dict['meridian'])
                township_num = str(row['township_num']).zfill(plss_pad_dict['township_num'])
                township_frac = row['township_frac'] if pd.notna(row['township_frac']) else '0'
                township_dir = str(row['township_dir']).upper()
                range_num = str(row['range_num']).zfill(plss_pad_dict['range_num'])
                range_frac = row['range_frac'] if pd.notna(row['range_frac']) else '0'
                range_dir = str(row['range_dir']).upper()
                section = str(row['section']).zfill(plss_pad_dict['section'])
            
                return f"{state}{meridian}{township_num}{township_frac}{township_dir}{range_num}{range_frac}{range_dir}0SN{section}0"
            except Exception as e:
                raise ValueError(f"Error generating PLSS ID for row {row.name}: {e}")
        
        plss_df['plss_id'] = plss_df.apply(_generate_plss_id, axis=1)

        # load reference table of PLSS parcels from BLM (use pre-loaded ref if available)
        if refs is not None and 'blm_plss' in refs:
            blm_df = refs['blm_plss']
        else:
            try:
                blm_df = gpd.read_file(PROJECT_ROOT / 'data/shapefiles/blm_plss.gdb', layer='PLSSFirstDivision').to_crs('EPSG:3857').set_index('FRSTDIVID')
            except:
                raise FileNotFoundError(f"BLM PLSS shapefile not found. Please ensure the file exists at {PROJECT_ROOT / 'data/shapefiles/blm_plss.gdb'}. If not, the file can be downloaded directly from https://gbp-blm-egis.hub.arcgis.com/datasets/283939812bc34c11bad695a1c8152faf/about.")

        # get parcel coordinates from BLM shapefile based on PLSS ID
        def _get_parcel_coords(plss_id):
            if plss_id in blm_df.index:
                match = blm_df.loc[[plss_id]]
                centroid = match.geometry.centroid.to_crs(TARGET_CRS).iloc[0]
                return pd.Series({'latitude': centroid.y, 'longitude': centroid.x, 'latlon_desc': "Geocoded (Section Centroid)"})
            else:
                # if no match found, try to find a match up to Range level (ignoring section)
                plss_id_range = plss_id[:-6]
                match = blm_df[blm_df.index.str.startswith(plss_id_range)]
                if not match.empty:
                    union_pt = match.union_all().centroid
                    centroid = gpd.GeoSeries([union_pt], crs='EPSG:3857').to_crs(TARGET_CRS).iloc[0]
                    return pd.Series({'latitude': centroid.y, 'longitude': centroid.x, 'latlon_desc': "Geocoded (Range Centroid)"})
                else:
                    return pd.Series({'latitude': np.nan, 'longitude': np.nan, 'latlon_desc': "No PLSS Match Found"})

        # compute coordinates once per unique PLSS ID, then join back to avoid redundant lookups
        plss_centroids = plss_df['plss_id'].drop_duplicates().apply(_get_parcel_coords)
        plss_centroids.index = plss_df['plss_id'].drop_duplicates().values
        plss_df[['latitude', 'longitude', 'latlon_desc']] = plss_df['plss_id'].map(plss_centroids.to_dict(orient='index')).apply(pd.Series)

        return plss_df[['latitude', 'longitude', 'latlon_desc']]

    elif method == "address":
        addr_df = pd.DataFrame(index=df.index) # empty dataframe to store address fields by row
        addr_field_dict = geocode_spec["address_fields"] # mode dict for each field

        # populate temporary df with address fields by row, using the appropriate mode for each field
        for addr_field, addr_spec in addr_field_dict.items():
            mode = addr_spec["mode"]
            if mode not in MODE_DISPATCH:
                raise ValueError(f"{field_name}: unsupported mode {mode!r} for address field {addr_field!r}")
            addr_df[addr_field] = MODE_DISPATCH[mode](addr_field, addr_spec, df, _resolved, refs)

        # build full address string from available fields
        addr_cols = [c for c in ['street', 'city', 'state', 'zip'] if c in addr_df.columns]
        addr_df['full_address'] = addr_df[addr_cols].fillna('').astype(str).apply(
            lambda row: ', '.join(part for part in row if part.strip()), axis=1
        ).replace('', np.nan)

        geolocator = ArcGIS()
        geocode = geolocator.geocode

        def _geocode_address(address):
            if pd.isna(address):
                return pd.Series({'latitude': np.nan, 'longitude': np.nan, 'latlon_desc': np.nan})
            location = geocode(address)
            if location:
                return pd.Series({'latitude': location.latitude, 'longitude': location.longitude, 'latlon_desc': 'Geocoded (Address)'})
            else:
                return pd.Series({'latitude': np.nan, 'longitude': np.nan, 'latlon_desc': 'No Address Match Found'})

        unique_addrs = addr_df['full_address'].drop_duplicates()
        addr_centroids = unique_addrs.apply(_geocode_address)
        addr_centroids.index = unique_addrs.values
        addr_df[['latitude', 'longitude', 'latlon_desc']] = addr_df['full_address'].map(addr_centroids.to_dict(orient='index')).apply(pd.Series)

        return addr_df[['latitude', 'longitude', 'latlon_desc']]

MODE_DISPATCH["geocode"] = mode_geocode

##############################################################
### LOCATE
### derives a field value via spatial point-in-polygon join
### using resolved coordinates
##############################################################
def mode_locate(field_name, _spec, df, resolved, refs):
    # determine which scale this field corresponds to (county or state)
    field_to_level_dict = {
        'state_alpha' : 'state',
        'county_name' : 'county',
        'geoid'       : 'county'
    }
    if field_name not in field_to_level_dict:
        raise ValueError(f"{field_name}: unsupported field for locate mode")
    level = field_to_level_dict[field_name]
    gdf = refs[f'us_{level}s'].copy() # get the appropriate reference geodataframe

    # ensure the reference geodataframe is in the target CRS
    if gdf.crs != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)
    
    # create a GeoDataFrame from the resolved latitude and longitude
    if 'latitude' not in resolved or 'longitude' not in resolved:
        raise KeyError(f"{field_name}: resolved latitude and longitude fields not found")
    # resolved is a dictionary
    coords_df = pd.DataFrame(index=df.index)
    coords_df['latitude'] = resolved['latitude']
    coords_df['longitude'] = resolved['longitude']
    coords_gdf = gpd.GeoDataFrame(coords_df, geometry=gpd.points_from_xy(coords_df['longitude'], coords_df['latitude']), crs=TARGET_CRS)
    
    # perform spatial join to find which polygon each point falls into
    joined = gpd.sjoin(coords_gdf, gdf, how='left', predicate='within')

    return pd.Series(joined[field_name], index=df.index, dtype=object)

MODE_DISPATCH["locate"] = mode_locate