#######################################################################################

# FILE NAME: utils.py
# AUTHOR: Caroline Adkins
# LAST UPDATED: October 2026

# Utility functions and variables used across the ETL pipeline

#######################################################################################

from pathlib import Path

TARGET_CRS = "EPSG:4269"
PROJECT_ROOT = Path(__file__).parent.parent

raw_data_dir = PROJECT_ROOT / "data" / "raw_data"
shapefiles_dir = Path(PROJECT_ROOT / "data" / "shapefiles")
supporting_data_dir = Path(PROJECT_ROOT / "data" / "supporting_data")
output_dir = Path(PROJECT_ROOT / "data" / "processed_data")