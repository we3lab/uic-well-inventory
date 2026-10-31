########################################################################################

# FILE NAME: coordinate_conversions.py
# AUTHOR: Caroline Adkins and Meerashree Sundara Raju
# LAST UPDATED: October 2026

"""
This script implements conversion functions for transforming values from one coordinate
system to decimage degrees (WGS84).

Supported Conversions:

Coordinates (to decimal degrees):
    - dms_colon_to_dd:          converts a delimiter-separated DMS string to decimal degrees
    - dms_compact_to_dd:        converts a compact DMS string (no delimiter, no hemisphere)
                                to decimal degrees
    - dms_expanded_to_dd:       converts DMS values stored in separate columns to decimal
                                degrees
    - crs_to_dd:                transforms x/y values from a source CRS to lon/lat in the
                                target CRS
    - northing_easting_to_dd:   converts northing/easting coordinates to decimal degrees

                            
"""

########################################################################################

import re

import numpy as np
import pandas as pd
from pyproj import CRS
from pyproj.transformer import TransformerGroup

from .utils import *

###############################################################
### HELPERS
### functions and variables supporting the unit conversions below
###############################################################

# strings treated as missing values
_NULLS = {"", "nan", "none", "null", "<na>"}

####################

def _clean(v):
    """
    Returns a stripped string, or None for missing values.
    """
    # return none if value is nan, none, or pd.NA
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    return None if s.lower() in _NULLS else s

####################

def _split_sign(s):
    """
    Strips a leading +/- or trailing N/S/E/W from a coordinate string.
    Returns (digits_string, sign).
    """
    sign = 1

    # check for leading sign
    if s.startswith("-"):
        sign, s = -1, s[1:]
    elif s.startswith("+"):
        s = s[1:]

    # check for trailing hemisphere letter (S and W are negative)
    if s and s[-1] in "SWsw":
        sign, s = -1, s[:-1]
    elif s and s[-1] in "NEne":
        s = s[:-1]

    return s.strip(), sign

####################

def _to_dd(deg, mins, secs, sign):
    """
    Combines degrees, minutes, seconds, and sign into decimal degrees.
    """
    # minutes and seconds must be less than 60
    if not (0 <= mins < 60 and 0 <= secs < 60):
        raise ValueError(f"Minutes/seconds out of range: {mins}, {secs}")

    # apply sign to the whole value, not just the degrees
    return sign * (abs(deg) + mins / 60.0 + secs / 3600.0)

###############################################################
### UNIT CONVERSIONS
### these functions support conversions between different 
### coordinate formats
###############################################################

def dms_colon_to_dd(series, delimiter=":", errors="raise"):
    """
    Converts "DD:MM:SS.ss" strings to decimal degrees (notation change only; the
    datum is unchanged). Accepts a leading '-' or trailing N/S/E/W for sign.

    Delimiter can be overridden to match source data.

    errors: "raise" or "coerce" (bad values become NaN).
    """
    def _parse(v):
        s = _clean(v)
        # return nan if value is nan or none
        if s is None:
            return np.nan
        try:
            # pull off sign or hemisphere letter
            s, sign = _split_sign(s)

            # split the string into parts by delimiter
            parts = s.split(delimiter)
            if len(parts) != 3:
                raise ValueError(f"Expected 3 parts for DMS, got {len(parts)}: {v!r}")
            deg, mins, secs = (float(p) for p in parts)

            return _to_dd(deg, mins, secs, sign)
        except ValueError:
            if errors == "coerce":
                return np.nan
            raise

    return series.apply(_parse)

####################

def dms_compact_to_dd(series, errors="raise"):
    """
    Converts compact DMS (DDMMSS[.ss] or DDDMMSS[.ss]) to decimal degrees.

    Format is inferred from integer digit count: 6 digits = DDMMSS
    (latitude), 7 digits = DDDMMSS (longitude). Sign comes only from an explicit
    '-' or N/S/E/W; unsigned input is returned positive.

    errors: "raise" or "coerce" (bad values become NaN).
    """
    def _parse(v):
        s = _clean(v)
        # return nan if value is nan or none
        if s is None:
            return np.nan
        try:
            # pull off sign or hemisphere letter before counting digits
            s, sign = _split_sign(s)

            # identify number of int digits to determine format
            n = len(s.split(".")[0])  # count digits before decimal
            if n == 6:  # DDMMSS
                deg, mins, secs = float(s[0:2]), float(s[2:4]), float(s[4:])
            elif n == 7:  # DDDMMSS
                deg, mins, secs = float(s[0:3]), float(s[3:5]), float(s[5:])
            else:
                raise ValueError(f"Unexpected digit count ({n}) for compact DMS: {v!r}")

            return _to_dd(deg, mins, secs, sign)
        except ValueError:
            if errors == "coerce":
                return np.nan
            raise

    return series.apply(_parse)

#####################

def dms_expanded_to_dd(deg_col, min_col, sec_col, hemisphere_col=None, fill_missing=False):
    """
    Convert DMS values stored in separate columns to decimal degrees.

    Sign comes from negative degrees or an optional hemisphere column (N/S/E/W).
    Rows with minutes/seconds out of range become NaN. Missing minutes/seconds
    become NaN unless fill_missing=True.
    """
    deg  = pd.to_numeric(deg_col, errors="coerce")
    mins = pd.to_numeric(min_col, errors="coerce")
    secs = pd.to_numeric(sec_col, errors="coerce")

    # treat missing minutes/seconds as zero only if requested
    if fill_missing:
        mins, secs = mins.fillna(0.0), secs.fillna(0.0)

    # get sign from negative degrees
    sign = pd.Series(np.where(deg < 0, -1.0, 1.0), index=deg.index)

    # override sign with hemisphere column if provided
    if hemisphere_col is not None:
        h = hemisphere_col.astype(str).str.strip().str.upper().str[:1]
        sign = sign.mask(h.isin(["S", "W"]), -1.0)

    # flag minutes/seconds that are out of range
    bad = (mins < 0) | (mins >= 60) | (secs < 0) | (secs >= 60)

    return (sign * (deg.abs() + mins / 60.0 + secs / 3600.0)).mask(bad)

###############################################################
### CRS TRANSFORMATIONS
### these functions support transformations between different
### coordinate reference systems (CRS)
###############################################################

def crs_transform(x, y, crs, target=TARGET_CRS):
    """
    Transforms x/y in a source CRS to lon/lat in the target CRS. Handles projections
    (e.g. UTM, State Plane) as well as datum shifts (e.g. NAD27 to WGS84).

    Axis order is always x/y (easting/longitude first), regardless of how the CRS
    is defined.

    Returns a DataFrame with columns lon, lat (NaN where invalid).
    """
    x = pd.to_numeric(x, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")
    crs = CRS.from_user_input(crs)

    # find the best transformation and check that its grid files are available
    group = TransformerGroup(crs, target, always_xy=True)
    if not group.best_available:
        raise RuntimeError(
            f"Best transformation {crs.name} -> {target} is unavailable (missing grids). "
            "Call group.download_grids() or enable PROJ network access."
        )
    t = group.transformers[0]

    out = pd.DataFrame({"longitude": np.nan, "latitude": np.nan}, index=x.index)

    # only transform rows where both values exist
    ok = x.notna() & y.notna()
    if ok.any():
        lon, lat = t.transform(x[ok].to_numpy(), y[ok].to_numpy())
        out.loc[ok, "longitude"], out.loc[ok, "latitude"] = lon, lat

    # pyproj returns inf for invalid transformations, so convert to nan
    return out.replace([np.inf, -np.inf], np.nan)


