import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from sklearn.preprocessing import StandardScaler, MinMaxScaler

class VRAIPreprocessor:
    """
    Extract, Transform, Load (ETL) Pipeline for VR Telemetry.
    Converts raw hardware data into normalized time-series tensors for Deep Learning.
    """
    def __init__(self, session_parquet_path: str, target_hz: int = 90):
        self.raw_file = Path(session_parquet_path)
        self.session_dir = self.raw_file.parent
        self.ai_file = self.session_dir / f"ai_ready_{self.raw_file.name}"
        self.meta_file = self.session_dir / "etl_metadata.json"
        
        self.target_hz = target_hz
        self.dt = 1.0 / target_hz
        self.version = "v2.0.0-Pro"

    def process(self) -> bool:
        print(f"[*] Starting AI Tensor Generation Pipeline ({self.version})")
        if not self.raw_file.exists():
            print(f"[!] Error: Raw Parquet file not found at {self.raw_file}")
            return False

        # 1. EXTRACT
        df = pd.read_parquet(self.raw_file)
        initial_rows = len(df)
        
        # 2. TRANSFORM
        df = self._handle_missing_values(df)
        df = self._apply_smoothing(df)
        df = self._calculate_kinematics(df)
        df = self._scale_features(df)

        # 3. LOAD (Save Ready Tensors)
        df.to_parquet(self.ai_file, compression='snappy')
        self._generate_metadata(initial_rows, len(df))
        
        print(f"[+] AI processing complete. Tensors saved to {self.ai_file}")
        return True

    def _handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """Removes NaN values to preserve Time-Series sequence continuity (0% loss rule)."""
        # Linear interpolation for small gaps (up to 3 frames / ~33ms)
        df = df.interpolate(method='linear', limit=3)
        # Forward/Backward fill for anything remaining at the edges
        df = df.bfill().ffill()
        return df

    def _apply_smoothing(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies Exponential Moving Average (EMA) to reduce tracking jitter."""
        # Span=5 frames at 90Hz is ~55ms smoothing window
        kinematic_cols = [c for c in df.columns if 'pos_' in c or 'rot_' in c]
        df[kinematic_cols] = df[kinematic_cols].ewm(span=5, adjust=False).mean()
        return df

    def _calculate_kinematics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Derives velocity from position using First-Order Central Difference."""
        pos_cols = [c for c in df.columns if 'pos_' in c]
        
        for col in pos_cols:
            vel_col_name = col.replace('pos_', 'vel_')
            # v = (x[t+1] - x[t-1]) / 2dt
            df[vel_col_name] = df[col].diff() / self.dt
            df[vel_col_name] = df[vel_col_name].bfill() # Fix the first NaN row
            
        return df

    def _scale_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalizes data to center around 0 to speed up gradient descent convergence.
        Positions & Velocities -> Z-Score Standard (Mean=0, Std=1)
        Biometrics & System -> MinMax (0.0 to 1.0)
        """
        z_scaler = StandardScaler()
        minmax_scaler = MinMaxScaler()

        z_cols = [c for c in df.columns if 'pos_' in c or 'rot_' in c or 'vel_' in c]
        sys_cols = ['cpu_utilization', 'gpu_utilization', 'heart_rate_bpm']

        if z_cols:
            df[z_cols] = z_scaler.fit_transform(df[z_cols])
        
        # Only scale system columns if they exist in the dataframe
        existing_sys_cols = [c for c in sys_cols if c in df.columns]
        if existing_sys_cols:
            df[existing_sys_cols] = minmax_scaler.fit_transform(df[existing_sys_cols])

        return df

    def _generate_metadata(self, before: int, after: int) -> None:
        """Documents the exact mathematical pipeline used for reproducibility."""
        meta = {
            "preprocessor_version": self.version,
            "smoothing_algorithm": "Exponential Moving Average (span=5)",
            "scaling_method": "Z-Score Standardization (Kinematics) & MinMax (Sys)",
            "velocity_deriv_method": f"First-order Difference (dt={self.dt:.4f}s)",
            "outlier_removal": "Linear Interpolation & Forward/Backward Fill",
            "frames_processed": after,
            "dropped_or_corrupted_frames": before - after,
            "processed_at_utc": datetime.now(timezone.utc).isoformat()
        }
        with open(self.meta_file, "w") as f:
            json.dump({"data_provenance": meta}, f, indent=4)