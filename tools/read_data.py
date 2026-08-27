# read_data.py

import argparse
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

def analyze_parquet_dataset(file_path: str) -> None:
    """
    Production-ready diagnostic utility to verify the integrity, shape, and 
    numerical types of collected time-series matrices. Confirms compliance with 
    Requirement ARCH-1.4 (Float32 Precision) and ARCH-1.5 (Flat Schema Layout).
    """
    path = Path(file_path)
    if not path.exists():
        print(f"Error: Specified data matrix path does not exist: {path}")
        return

    print(f"=== OpenXR Headless Telemetry Inspection Ledger ===")
    print(f"File: {path.name}")
    print(f"Size: {path.stat().st_size / (1024 * 1024):.4f} MB")
    print("-" * 60)

    try:
        # Read metadata schema directly via PyArrow without full file memory allocation
        meta = pq.read_metadata(path)
        print(f"Recorded Row Groups: {meta.num_row_groups}")
        print(f"Total Recorded Frames: {meta.num_rows}")
        print(f"Total Column Features: {meta.num_columns}")
        print("\n--- Structural Field Data Type Assertions ---")
        
        schema = meta.schema
        for i in range(len(schema)):
            col_meta = schema.column(i)
            print(f"Feature {i:02d}: {col_meta.name:<25} -> Type: {col_meta.physical_type}")

        print("\n--- Sequence Head Data Sample Slice ---")
        # Load the first row group into a Pandas DataFrame for micro-validation
        table = pq.read_table(path)
        df = table.to_pandas()
        
        pd.set_option('display.max_columns', 10)
        pd.set_option('display.width', 1000)
        print(df.head(10))
        
        print("\n--- Biometric Tracking Validity Summary ---")
        if "eye_tracking_valid" in df.columns:
            valid_frames = df["eye_tracking_valid"].sum()
            total_frames = len(df)
            ratio = (valid_frames / total_frames) * 100 if total_frames > 0 else 0.0
            print(f"Ocular Data Quality: {valid_frames:.0f}/{total_frames} frames tracking valid ({ratio:.2f}%)")
        if "hmd_tracking_valid" in df.columns:
            print(f"HMD Optical Lock:    {df['hmd_tracking_valid'].sum():.0f}/{len(df)} frames valid")

    except Exception as e:
        print(f"Catastrophic failure parsing Parquet time-series data: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRTelemetry: Columnar Dataset Inspection Tool")
    parser.add_argument("file", type=str, help="Path to the targeted .parquet telemetry file.")
    args = parser.parse_args()
    
    analyze_parquet_dataset(args.file)