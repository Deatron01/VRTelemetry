import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from sklearn.preprocessing import StandardScaler

class VRAIPreprocessor:
    """
    A mathematical normalization ETL context driver. Translates raw time-series matrices
    into zero-gap arrays formatted for high-velocity ML optimization pipelines.
    """
    def __init__(self, raw_parquet_path: Path, target_hz: int = 90):
        self.raw_file = raw_parquet_path
        self.out_file = self.raw_file.parent / f"ai_ready_{self.raw_file.name}"
        self.meta_file = self.raw_file.parent / f"etl_meta_{self.raw_file.stem}.json"
        self.dt = 1.0 / target_hz

    def execute_transform(self) -> None:
        if not self.raw_file.exists():
            return
        
        df = pd.read_parquet(self.raw_file)
        initial_frames = len(df)

        # 1. Resolve discontinuous gaps securely using linear extrapolation bounded trends
        df = df.interpolate(method='linear', limit=5).bfill().ffill()

        # 2. Derive linear vector trends via centralized differentiations
        pos_headers = [h for h in df.columns if 'pos_' in h]
        for header in pos_headers:
            vel_header = header.replace('pos_', 'vel_')
            df[vel_header] = np.gradient(df[header].to_numpy(), self.dt)

        # 3. Apply standard scaling architectures to center vectors at zero variance
        transform_headers = [h for h in df.columns if 'pos_' in h or 'rot_' in h or 'vel_' in h]
        scaler = StandardScaler()
        df[transform_headers] = scaler.fit_transform(df[transform_headers].astype(np.float32))

        # Output processed parameters
        df.to_parquet(self.out_file, compression='snappy')

        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump({
                "preprocessor_version": "v2.0.0-Pro",
                "transform_timestamp": datetime.now(timezone.utc).isoformat(),
                "total_frames_extracted": initial_frames,
                "velocity_derivation_method": "Central Difference"
            }, f, indent=4)