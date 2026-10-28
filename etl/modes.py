#######################################################################################

# FILE NAME: modes.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

"""
This script implements one processing function for each field mode.

Each function receives the output field name, the field's spec dict, the raw source
DataFrame, the dict of the already-resolved output fields (for lookups that depend on
earlier fields), and the loaded reference tables. Each function returns a pd.Series
aligned to the source DataFrame's index.

Supported Modes:
    - none:             returns a null Series; field is not present or derivable
    - constant:         returns a Series filled with a single literal value
    - column:           copies a source column directly
    - extract:          derives a value from a source column via slice or regex
    - crosswalk:        maps source column values to output values via an explicit dict
    - concat:           joins multiple source columns with a delimiter
    - compute:          applies an aggregate function (mean, min, max, etc.) across
                        multiple numeric source columns within each row
    - reproject:        handles coordinate conversions and projection changes; returns a
                        DataFrame with latitude and longitude columns
    - geocode:          converts an address or PLSS description to coordinates
"""

#######################################################################################

import numpy as np
import pandas as pd
import re

from . import coordinate_conversions as coord_convert

##############################################################
### NONE
### returns a null Series; field is not present or derivable
##############################################################

def mode_none(_field_name, _spec, df, _resolved, _refs):
    return pd.Series([np.nan] * len(df), index=df.index, dtype=object)

##############################################################
### CONSTANT
### returns a Series filled with a single literal value
##############################################################
def mode_constant(_field_name, spec, df, _resolved, _refs):
    return pd.Series([spec["constant"]] * len(df), index=df.index, dtype=object)

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

##############################################################
### EXTRACT
### derives a value from a source column via slice or regex
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

##############################################################
### CROSSWALK
### maps source column values to output values via an explicit 
### dict
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

##############################################################
### REPROJECT
### handles coordinate conversions and projection changes
### returns a DataFrame with latitude and longitude columns
##############################################################
def mode_reproject(field_name, spec, df, _resolved, _refs):
    reproject_spec  = spec["reproject"]
    input_format = spec["reproject"]["input_format"]
    source_crs   = reproject_spec.get("crs", "EPSG:4269") # default to NAD83 if not specified

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
    if input_format in ("dms_colon", "dms_compact"): # only one column for each of latitude and longitude
        lat_col, lon_col = x_columns[0], y_columns[0]
        _check_cols(lat_col, lon_col)
        if input_format == "dms_colon":
            delimiter = reproject_spec.get("delimiter", ":")
            y = coord_convert.dms_colon_to_dd(df[lat_col], delimiter=delimiter, errors="coerce")
            x = coord_convert.dms_colon_to_dd(df[lon_col], delimiter=delimiter, errors="coerce")
        else:
            y = coord_convert.dms_compact_to_dd(df[lat_col], errors="coerce")
            x = coord_convert.dms_compact_to_dd(df[lon_col], errors="coerce")

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

    elif input_format == "northing_easting":
        # x_columns[0] = northing (y-direction), y_columns[0] = easting (x-direction)
        northing_col, easting_col = x_columns[0], y_columns[0]
        _check_cols(northing_col, easting_col)
        x = df[easting_col]
        y = df[northing_col]

    else:
        raise ValueError(
            f"{field_name}: unsupported reproject input_format {input_format!r}"
        )

    # apply crs_transform to all formats
    result = coord_convert.crs_transform(x=x, y=y, crs=source_crs)

    return pd.DataFrame({"latitude": result["latitude"], "longitude": result["longitude"]}, index=df.index)

##############################################################
### GEOCODE
### converts an address or PLSS description to coordinates
##############################################################
"""
NEED TO FIGURE OUT HOW TO DO THIS. HANDLE ADDRESSES AND PLSS. FIGURE OUT WHICH FILES HAVE AND WHAT FORMAT DATA IS IN.
"""