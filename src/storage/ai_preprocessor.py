# src/storage/ai_preprocessor.py

import logging
import numpy as np
import pandas as pd
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

    # Columns where -1.0 is a legitimate "unavailable" sentinel, not a real reading.
    # Must never be folded into ffill/EWM/z-score statistics as if it were a sample.
    SENTINEL_COLUMNS: Dict[str, float] = {
        "battery_hmd": -1.0,
        "battery_left": -1.0,
        "battery_right": -1.0,
        "distance_to_boundary": -1.0,
        "gaze_focal_distance": -1.0,
        "gpu_utilization": -1.0,
        "left_pupil_size": -1.0,
        "right_pupil_size": -1.0,
    }

    def __init__(self, input_parquet_path: str):
        self.input_path = Path(input_parquet_path)
        self.output_path = self.input_path.with_name(f"{self.input_path.stem}_ai_ready.parquet")

        self.processing_metadata: Dict[str, Any] = {
            "preprocessor_version": "v1.1.0",
            "smoothing_algorithm": "Exponential_Moving_Average",
            "scaling_method": "Z-Score_Standardization",
            "velocity_deriv_method": "Forward_Euler",
            "outlier_removal": "None",
            "sentinel_handling": "Masked to NaN pre-normalization, restored post-normalization; "
                                  "companion *_available flags added",
            "total_dropped_frames": 0,
        }

    def process(self) -> None:
        """
        Executes the feature engineering step. Implements forward-fill validation,
        sentinel masking, kinematic derivations, and Parquet schema mutations.
        """
        if not self.input_path.exists():
            logger.error(f"Input file not found: {self.input_path}")
            return

        logger.info(f"Loading raw matrix: {self.input_path}")
        table = pq.read_table(self.input_path)
        df = table.to_pandas()

        # Step 1: Forward Fill structural validation (Address potential sensor dropouts).
        # This only touches genuine NaN gaps — sentinel values (-1.0) aren't NaN yet at this
        # point, so they're untouched here regardless of ordering relative to Step 1b.
        missing_count = df.isna().sum().sum()
        if missing_count > 0:
            logger.warning(f"Detected {missing_count} NaN values. Executing structural Forward Fill.")
            df.ffill(inplace=True)
            df.fillna(0.0, inplace=True)  # Fallback for initial frames

        # Step 1b: Mask "unavailable" sentinel values BEFORE any smoothing/normalization can
        # see them. Do this AFTER Step 1's ffill so the generic fallback pass above doesn't
        # smear a forward-filled real value across what should stay a NaN gap here, and so it
        # doesn't fillna(0.0) over what we're about to mark NaN either.
        sentinel_masks: Dict[str, pd.Series] = {}
        for col, sentinel_value in self.SENTINEL_COLUMNS.items():
            if col not in df.columns:
                continue
            mask = np.isclose(df[col].astype(np.float64), sentinel_value)
            df[f"{col}_available"] = (~mask).astype(np.float32)
            if mask.any():
                sentinel_masks[col] = mask
                df.loc[mask, col] = np.nan

        # Step 2: Smoothing Pipeline (Exponential Moving Average on Positional Kinematics)
        pos_columns = [c for c in df.columns if 'pos' in c and c not in sentinel_masks]
        for col in pos_columns:
            df[col] = df[col].ewm(alpha=0.2, adjust=False, ignore_na=True).mean().astype(np.float32)

        # Step 3: Normalization via Z-Score Standardization (Mean 0, Std 1)
        # Bypasses purely binary valid flags, target indices, explicit quaternions, and the
        # availability flags we just added (those are already 0/1 semantic, not to be scaled).
        exclude_cols = [
            c for c in df.columns
            if 'valid' in c or 'rot' in c or 'index' in c or 'timestamp' in c or 'scene' in c
            or c.endswith('_available')
        ]
        normalize_cols = [c for c in df.columns if c not in exclude_cols]

        for col in normalize_cols:
            # pandas .mean()/.std() skip NaN by default, so masked sentinel entries never
            # pollute the statistics computed here.
            col_mean = df[col].mean()
            col_std = df[col].std()
            if col_std and col_std > 1e-6:
                df[col] = ((df[col] - col_mean) / col_std).astype(np.float32)
            else:
                df[col] = 0.0

            # Restore the original sentinel now that it's been correctly excluded from the
            # statistics — a masked value must not come back out as "0.0" (looks like a
            # normalized real reading) or as NaN (breaks tensor ingestion downstream).
            if col in sentinel_masks:
                df.loc[sentinel_masks[col], col] = np.float32(self.SENTINEL_COLUMNS[col])

        # Cast back to strictly typed Arrow Table
        schema = pa.Schema.from_pandas(df)
        final_table = pa.Table.from_pandas(df, schema=schema)

        logger.info(f"AI Transformation complete. Writing Tensor-Ready Output to: {self.output_path}")
        pq.write_table(final_table, self.output_path, compression='snappy')

        logger.info("Category 8 Metadata (Adatfeldolgozási Metaadat):")
        for k, v in self.processing_metadata.items():
            logger.info(f" - {k}: {v}")