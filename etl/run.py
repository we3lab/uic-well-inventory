#######################################################################################

# FILE NAME: run.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

# Entry point for full processing pipeline.

# Iterates through all datasets in raw_data/ directory and processes into a single
# cleaned dataset saved to processed_data/ directory. Each dataset is processed
# according to its corresponding YAML spec in raw_data/spec_files/ directory.

#######################################################################################

from pathlib import Path

import pandas as pd

from . import processor, reference_tables
from .utils import *

##############################################################

def add_derived_fields(df, refs):
    """
    Adds fields to DataFrame that can be derived from existing fields.

    Arguments:
        df : pd.DataFrame
            The DataFrame to add derived fields to.
        refs : dict
            A dictionary of reference DataFrames, keyed by reference name.
    
    Returns:
        df : pd.DataFrame
            The DataFrame with derived fields added.
    
    """
    # --- unique_id -------------------------------------------------------------------
    # TODO: define a globally unique well identifier scheme
    df["unique_id"] = pd.NA

    # --- state_name -------------------------------------------------------------------
    # lookup from us_states using state_alpha
    state_alpha_to_name = dict(zip(refs["us_states"]["state_alpha"], refs["us_states"]["state_name"]))
    df["state_name"] = df["state_alpha"].map(state_alpha_to_name)

    # --- county_name ------------------------------------------------------------------
    # lookup from us_counties using geoid
    geoid_to_county_name = dict(zip(refs["us_counties"]["geoid"], refs["us_counties"]["county_name"]))
    df["county_name"] = df["geoid"].map(geoid_to_county_name)

    # --- primacy and responsible_office -----------------------------------------------
    # lookup from uic_authority using state_alpha and well_class
    uic_authority_df = refs["uic_authority"]
    df = df.merge(uic_authority_df[["state_alpha", "well_class", "primacy", "responsible_office"]], on=["state_alpha", "well_class"], how="left")

    # --- well_subytpe_desc ------------------------------------------------------------
    # lookup from well_subtypes using well_subtype
    well_subtype_to_desc = dict(zip(refs["well_subtypes"]["well_subtype"], refs["well_subtypes"]["well_subtype_desc"]))
    df["well_subtype_desc"] = df["well_subtype"].map(well_subtype_to_desc)

    return df

##############################################################

def reorder_columns(df):
    """
    Reorders columns to canonical output order.

    Arguments:
        df : pd.DataFrame
            The DataFrame to reorder columns for.
    Returns:
        df : pd.DataFrame
            The DataFrame with columns reordered to canonical output order.
    """
    output_column_order = [
        "unique_id",
        "latitude", "longitude", "location_flag",
        "state_alpha", "state_name",
        "geoid","county_name",
        "epa_region",
        "primacy", "responsible_office",
        "well_id", "well_id_desc",
        "well_class", "well_subtype", "well_subtype_desc", "well_subtype_raw",
        "well_depth_ft", "well_depth_ft_desc",
        "operator", "operator_desc",
        "status", "status_raw",
        "date", "date_desc",
        "_source_file", "_source_sheet", "_source_row"
    ]

    # check if any columns are missing from the DataFrame
    missing_columns = [col for col in output_column_order if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing columns in DataFrame: {missing_columns}")

    # check if any columns are in the DataFrame that are not in the output order
    extra_columns = [col for col in df.columns if col not in output_column_order]
    if extra_columns:
        raise ValueError(f"Extra columns in DataFrame: {extra_columns}")
    
    return df[output_column_order]

##############################################################

def write_output(df):
    """
    Writes the processed DataFrame to a parquet file in the processed_data/ directory.

    Arguments:
        df : pd.DataFrame
            The DataFrame to write to parquet.
    """
    # create output directory if it doesn't exist
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    
    # write to parquet
    output_path = output_dir / "uic_well_inventory.parquet"
    df.to_parquet(output_path, index=False)

##############################################################
    
def build_inventory():
    """
    Main processing pipeline for building UIC well inventory.

    Loads reference tables, iterates through all source files in raw_data/, 
    processes each file according to its YAML specs, adds derived fields, 
    reorders columns, and writes the final output to a parquet file.
    
    """
    # load reference tables
    print("Loading reference tables...", end="\r")
    refs = reference_tables.load()
    print(f"Finished loading reference tables.\n\n")

    # iterate through all source files in raw_data/
    processed_dfs = []
    for i, xlsx_file in enumerate(raw_data_dir.glob("*.xlsx")):
        # print header for each file
        print("=" * 60)
        print(f"{xlsx_file.name} ({i+1}/{len(list(raw_data_dir.glob('*.xlsx')))})")
        print("=" * 60)

        file_stem = xlsx_file.stem
        processed_df = processor.process_file(file_stem, refs)
        processed_dfs.append(processed_df)

        print(f"Finished processing {xlsx_file.name}.                                \n\n")

    print("=" * 60)
    print("Generating Master DataFrame")
    print("=" * 60)

    # concatenate all processed DataFrames into a single DataFrame
    print("Stacking all processed DataFrames into a single DataFrame...", end="\r")
    master_df = pd.concat(processed_dfs, ignore_index=True)
    print("Finished stacking all processed DataFrames.")

    # add derived fields
    print("Adding derived fields...", end="\r")
    master_df = add_derived_fields(master_df, refs)
    print("Finished adding derived fields.")

    # reorder columns to canonical output order
    print("Reordering columns...", end="\r")
    master_df = reorder_columns(master_df)
    print("Finished reordering columns.")

    # write final output to parquet
    print("Writing final output to parquet...", end="\r")
    write_output(master_df)
    print("Finished writing final output to parquet.")

    # print summary of final output
    print("\n\nComplete.")
    
if __name__ == "__main__":
    build_inventory()