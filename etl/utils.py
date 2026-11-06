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

# dictionary mapping EPA region numbers to their corresponding state abbreviations
EPA_REGION_TO_STATES = {
    "Region 1":  {"CT", "ME", "MA", "NH", "RI", "VT"},
    "Region 2":  {"NJ", "NY"},
    "Region 3":  {"DE", "DC", "MD", "PA", "VA", "WV"},
    "Region 4":  {"AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"},
    "Region 5":  {"IL", "IN", "MI", "MN", "OH", "WI"},
    "Region 6":  {"AR", "LA", "NM", "OK", "TX"},
    "Region 7":  {"IA", "KS", "MO", "NE"},
    "Region 8":  {"CO", "MT", "ND", "SD", "UT", "WY"},
    "Region 9":  {"AZ", "CA", "HI", "NV"},
    "Region 10": {"AK", "ID", "OR", "WA"}
}

# dictionary mapping Arabic numerals to Roman numerals for well classes
ARABIC_TO_ROMAN = {
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
    "5": "V",
    "6": "VI",
}  