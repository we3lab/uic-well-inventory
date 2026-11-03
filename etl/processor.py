#######################################################################################

# FILE NAME: processor.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

# Orchestrates field-by-field processing for a single sheet within a source file.

# Given a raw DataFrame (one sheet from a spreadsheet) and its corresponding YAML
# spec, processor.py walks the spec's field entries in order and resolves each
# output field by:
#   1. Dispatching to the appropriate mode function in modes.py
#   2. Applying any registered per-field post-processors from postprocess.py
#   3. Storing the resolved Series in a dict so later fields can reference it
#      (e.g. a tabular lookup that keys on an already-resolved field)

# The processor returns a single DataFrame of resolved output fields, with one
# row per row in the source sheet. It also attaches three metadata columns to every
# output DataFrame:
#   - _source_file  — the YAML filename (e.g. "fl_v.yaml")
#   - _source_sheet — the sheet name as it appears in the YAML (e.g. "Sheet1")
#   - _source_row   — the row number in the source sheet (1-indexed, as it appears in Excel
# These columns are used by run.py when stacking sheets and by validate.py when
# reporting issues back to a specific source.

#########################################################################################

from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

import yaml

from . import modes
from . import postprocessor
from .utils import *

def load_sheet(file_path, sheet_name, load_specs):
    """
    Loads a single sheet from a source file into a DataFrame, applying any
    sheet-level transformations specified in the YAML spec.

    Arguments:
        file_path : str or Path
            The path to the source file (e.g. "data/fl_v.xlsx").
        sheet_name : str
            The name of the sheet to load (e.g. "Sheet1").
        load_specs : dict
            The YAML load specs for the sheet being loaded.

    Returns:
        df : pd.DataFrame
            The loaded DataFrame for the sheet.

    """
    # get sheet spec information to help load
    header_row = load_specs["header_row"]
    data_cols = load_specs["data_cols"]
    
    # load the sheet into a DataFrame
    df = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        header=header_row,
        usecols=data_cols,
        dtype = str  # read all columns as strings to avoid type issues. mode functions will handle type conversion as needed
    )

    # strip leading and trailing whitespace from all column headers to handle accidental spaces in the source sheet
    df.columns = df.columns.str.strip()

    return df

##############################################################

def process_sheet(df, sheet_specs, source_file, source_sheet, refs):
    """
    Processes a raw DataFrame for one sheet according to its field spec.
    
    Walks the spec's fields in the order providd, dispatching each to the appropriate
    mode function, applying applicable post-processors, and storing results.

    Arguments:
        df : pd.DataFrame
            The raw DataFrame for the sheet being processed.
        sheet_specs : dict
            The full YAML spec for the sheet being processed.
        source_file : str
            The name of the source file (e.g. "fl_v.xlsx") from which the sheet was read.
        source_sheet : str
            The name of the sheet (e.g. "Sheet1") being processed.
        refs : Refs
            A Refs instance containing all loaded reference tables.
    
    Returns:
        processed_df : pd.DataFrame
            A DataFrame containing the processed output fields.

    """
    resolved = {} # empty dict to hold resolved fields for this sheet

    # extract source file, sheet, and rows
    resolved["_source_file"] = pd.Series(source_file, index=df.index)

    resolved["_source_sheet"] = pd.Series(source_sheet, index=df.index)

    # extract header row and source rows
    header_row = sheet_specs["load_specs"]["header_row"]
    source_rows = pd.Series(range(len(df)), index=df.index) + header_row + 2 # +1 for 1-indexing, +1 for header row
    resolved["_source_row"] = source_rows

    # iterate through each field in sheet_specs (other than load_specs) and dispatch mode functions
    for field_name, field_specs in sheet_specs.items():
        print(f"\tProcessing {field_name}...", end="\r")
        if field_name == "load_specs":
            continue # skip the load_specs entry (only needed for sheet load and source columns)
        if not isinstance(field_specs, dict):
            raise ValueError(f"Field spec for '{field_name}' must be a dict, got {type(field_specs)}")
        
        mode = field_specs.get("mode")
        mode_fn = modes.MODE_DISPATCH.get(mode)

        if mode_fn is None:
            raise ValueError(f"Unknown mode '{mode}' for field '{field_name}'")
        
        try:
            mode_output = mode_fn(field_name, field_specs, df, resolved, refs)
        except Exception as e:
            raise RuntimeError(f"Error processing field '{field_name}' with mode '{mode}': {e}") from e
        
        if field_name == "coordinates":
            resolved["latitude"] = mode_output["latitude"]
            resolved["longitude"] = mode_output["longitude"]
            resolved["location_flag"] = mode_output["location_flag"]
        else:
            resolved[field_name] = mode_output

        # run field postprocessing if applicable
        postprocessor_fn = postprocessor.FIELD_POSTPROCESSORS_DISPATCH.get(field_name)
        if postprocessor_fn is not None:
            try:
                if field_name == "coordinates":
                    coords_df = pd.DataFrame({
                        "latitude"   : resolved["latitude"],
                        "longitude"  : resolved["longitude"],
                        "location_flag": resolved["location_flag"],
                    }, index=df.index)
                    postprocessor_output = postprocessor_fn(coords_df, resolved, refs)
                    resolved["latitude"]    = postprocessor_output["latitude"]
                    resolved["longitude"]   = postprocessor_output["longitude"]
                    resolved["location_flag"] = postprocessor_output["location_flag"]
                else:
                    resolved[field_name] = postprocessor_fn(resolved[field_name], resolved, refs)
            except Exception as e:
                raise RuntimeError(f"Error postprocessing field '{field_name}': {e}") from e

    # pull into a single dataframe
    processed_df = pd.DataFrame(resolved, index=df.index)

    # run sheet level postprocessing
    processed_df = postprocessor.postprocess_sheet(processed_df, refs)

    return processed_df

##############################################################

def process_file(file_stem, refs):
    """
    Loads and processes all sheets defined in a YAML spec for a given source file.

    Locates the corresponding YAML spec for the source file, loads each sheet listed in the spec, 
    processes it, and returns a single stacked DataFrame of all processed sheets.

    Arguments:
        file_stem : str
            The stem of the source file (e.g. "fl_v" for "fl_v.xlsx").
        refs : Refs
            A Refs instance containing all loaded reference tables.
    
    Returns:
        processed_file : pd.DataFrame
            A DataFrame containing the processed output fields for all sheets in the source file.
    
    """
    yaml_path = Path(PROJECT_ROOT / "data" / "raw_data" / "spec_files" / f"{file_stem}.yaml")
    xlsx_path = Path(PROJECT_ROOT / "data" / "raw_data" / f"{file_stem}.xlsx")

    # check if excel and yaml exist
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML spec file not found: {yaml_path}")
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Excel source file not found: {xlsx_path}")

    # read through yaml to identify what sheets to process
    with yaml_path.open() as f:
        file_specs = yaml.safe_load(f) # file_specs = full yaml contents

    processed_sheets = [] # list to hold processed DataFrames for each sheet
    for i, sheet_name in enumerate(file_specs['sheets'].keys()):
        print(f"Processing sheet {i+1}/{len(file_specs['sheets'])}: {sheet_name}...", end='\r')
        
        # get spec for this sheet
        sheet_specs = file_specs['sheets'][sheet_name] # sheet spec = full yaml contents for this sheet
        load_specs = sheet_specs["load_specs"] # load_specs = yaml contents for this sheet's load_specs entry

        # load sheet into DataFrame
        df = load_sheet(xlsx_path, sheet_name, load_specs)

        # process into standardized format
        processed_sheet_df = process_sheet(df, sheet_specs, xlsx_path.name, sheet_name, refs)

        # append to results list
        processed_sheets.append(processed_sheet_df)

        print(f"Finished processing sheet {i+1}/{len(file_specs['sheets'])}: {sheet_name}.                    ")
    
    # concatenate all processed sheets into a single DataFrame
    processed_file = pd.concat(processed_sheets, ignore_index=True)

    return processed_file
