import pandas as pd
import glob
import os

# Find the most recently created parquet file in the Sessions folder
list_of_files = glob.glob('Sessions/*.parquet')
latest_file = max(list_of_files, key=os.path.getctime)

# Load the data into a pandas DataFrame
df = pd.read_parquet(latest_file)

# Display the first 5 frames and the structural info
print(f"Loaded: {latest_file}")
print("-" * 50)
print(df.head())
print("-" * 50)
print(f"Total Rows: {len(df)}")
print(f"Average CPU Usage: {df['cpu_utilization'].mean():.2f}%")