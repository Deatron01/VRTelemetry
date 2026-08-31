"""TOMBSTONE — safe to delete. Nothing imports this module any more.

It used to run `pip install -r requirements.txt` on every CLI launch, with
output sent to DEVNULL. A program that mutates its own environment at startup
means two runs a week apart are not the same software, which is indefensible
for a tool recording research data: a silently upgraded pyarrow can change how
a Parquet file is written mid-study with nothing in the record to show it. It
also could not work inside the frozen PyInstaller bundle the desktop app ships.

Environment construction now belongs to the installer:

    pip install -e ".[workstation]"

`src/tert_runner.py` no longer calls it. This file is left in place only
because this session cannot delete files on your machine.

    git rm pytest.ini tox.ini config.json src/utils/auto_installer.py

See VRT-5.
"""
