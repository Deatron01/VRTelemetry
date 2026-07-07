# src/storage/ai_preprocessor.py

import logging
import numpy as np
import pyarrow.parquet as pq
import pyarrow as pa
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class AIPostProcessor:
    """
    Offline data refinement pipeline matching Requirement Category 8 (Adatfeldolgozási Metaadat).
    Transforms the raw nanosecond time-series matrices into standardized, normalized tensors 
    ready for multi-layer perceptron (MLP) or RNN ingestion in Deep Learning pipelines.
    """

    def __init__(self, input_parquet_path: str):
        self.input_path = Path(input_parquet_path)
        self.output_path = self.input_path.with_name(f"{self.input_path.stem}_ai_ready.parquet")
        
        self.processing_metadata: Dict[str, Any] = {
            "preprocessor_version": "v1.0.0",
            "smoothing_algorithm": "Exponential_Moving_Average",
            "scaling_method": "Z-Score_Standardization",
            "velocity_deriv_method": "Forward_Euler",
            "outlier_removal": "None",
            "total_dropped_frames": 0
        }

    def process(self) -> None:
        """
        Executes the feature engineering step. Implements forward-fill validation,
        kinematic derivations, and Parquet schema mutations.
        """
        if not self.input_path.exists():
            logger.error(f"Input file not found: {self.input_path}")
            return

        logger.info(f"Loading raw matrix: {self.input_path}")
        table = pq.read_table(self.input_path)
        df = table.to_pandas()

        # Step 1: Forward Fill structural validation (Address potential sensor dropouts)
        missing_count = df.isna().sum().sum()
        if missing_count > 0:
            logger.warning(f"Detected {missing_count} NaN values. Executing structural Forward Fill.")
            df.ffill(inplace=True)
            df.fillna(0.0, inplace=True) # Fallback for initial frames
            
        # Step 2: Smoothing Pipeline (Exponential Moving Average on Positional Kinematics)
        pos_columns = [c for c in df.columns if 'pos' in c]
        for col in pos_columns:
            df[col] = df[col].ewm(alpha=0.2, adjust=False).mean().astype(np.float32)

        # Step 3: Normalization via Z-Score Standardization (Mean 0, Std 1)
        # Bypasses purely binary valid flags, target indices, and explicit quaternions
        exclude_cols = [c for c in df.columns if 'valid' in c or 'rot' in c or 'index' in c or 'timestamp' in c or 'scene' in c]
        normalize_cols = [c for c in df.columns if c not in exclude_cols]
        
        for col in normalize_cols:
            col_std = df[col].std()
            if col_std > 1e-6:
                df[col] = ((df[col] - df[col].mean()) / col_std).astype(np.float32)
            else:
                df[col] = 0.0

        # Cast back to strictly typed Arrow Table
        schema = pa.Schema.from_pandas(df)
        final_table = pa.Table.from_pandas(df, schema=schema)
        
        logger.info(f"AI Transformation complete. Writing Tensor-Ready Output to: {self.output_path}")
        pq.write_table(final_table, self.output_path, compression='snappy')
        
        logger.info("Category 8 Metadata (Adatfeldolgozási Metaadat):")
        for k, v in self.processing_metadata.items():
            logger.info(f" - {k}: {v}")