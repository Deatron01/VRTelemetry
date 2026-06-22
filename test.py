import pandas as pd

df = pd.read_parquet("scientific_test_telemetry.parquet")
print(df.dtypes)