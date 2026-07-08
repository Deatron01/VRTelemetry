#!/usr/bin/env python3
"""
Mermaid Diagram Batch Converter

This script recursively searches for Markdown files in a given directory,
extracts Mermaid code blocks, writes them to temporary .mmd files, and
uses the Mermaid CLI (mmdc) to render them into images (SVG/PNG/PDF).

Features:
- Recursive directory traversal.
- Extracts multiple diagrams per file (naming them _1, _2, etc.).
- Uses temporary files with automatic cleanup.
- Detailed logging to both console and 'conversion.log'.
- Cross-platform executable resolution via `npx`.
- Multithreaded processing for high performance.
- PEP8 compliant and fully type-annotated.
"""

import argparse
import logging
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================

# Regex to find standard Markdown Mermaid blocks.
# Uses re.DOTALL to match across newlines.
MERMAID_REGEX = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)

# Default log file name
LOG_FILE = "conversion.log"


def setup_logger() -> logging.Logger:
    """
    Configures and returns a logger that outputs to both the console and a log file.
    
    Returns:
        logging.Logger: The configured logger instance.
    """
    logger = logging.getLogger("MermaidConverter")
    logger.setLevel(logging.INFO)
    
    # Prevent adding multiple handlers if function is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s", 
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # File Handler
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger

LOGGER = setup_logger()


def get_mmdc_command() -> str:
    """
    Determines the appropriate npx/mmdc command based on the operating system.
    Using 'npx mmdc' ensures that globally or locally installed npm packages 
    are found, bypassing Python virtual environment PATH restrictions.
    
    Returns:
        str: The command prefix for executing Mermaid CLI.
    """
    return "npx.cmd mmdc" if os.name == "nt" else "npx mmdc"


def process_single_diagram(mermaid_code: str, output_path: Path) -> bool:
    """
    Writes a single Mermaid code block to a temporary file, renders it via mmdc,
    and automatically cleans up the temporary file.
    
    Args:
        mermaid_code (str): The raw Mermaid syntax.
        output_path (Path): The destination path for the rendered image.
        
    Returns:
        bool: True if generation was successful, False otherwise.
    """
    # Create a temporary file that is not automatically deleted by the OS on close
    # (Fixes permission errors on Windows when passing file to external processes)
    fd, temp_mmd_path = tempfile.mkstemp(suffix=".mmd", text=True)
    try:
        with open(fd, 'w', encoding='utf-8') as temp_file:
            temp_file.write(mermaid_code.strip())
            
        cmd = f'{get_mmdc_command()} -i "{temp_mmd_path}" -o "{output_path}" -b transparent'
        
        # Execute the conversion
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        if result.returncode != 0:
            LOGGER.error(f"Failed to render {output_path.name}:\n{result.stderr.strip()}")
            return False
            
        LOGGER.info(f"Successfully generated: {output_path.name}")
        return True
        
    except Exception as e:
        LOGGER.error(f"Unexpected error while processing {output_path.name}: {e}")
        return False
        
    finally:
        # Guarantee cleanup of the temporary .mmd file
        try:
            os.remove(temp_mmd_path)
        except OSError:
            pass


def process_markdown_file(md_path: Path, output_format: str) -> int:
    """
    Parses a Markdown file, extracts all Mermaid blocks, and dispatches them 
    for rendering. Handles dynamic naming if multiple blocks exist.
    
    Args:
        md_path (Path): The path to the Markdown file.
        output_format (str): The desired output extension ('svg', 'png', 'pdf').
        
    Returns:
        int: The number of diagrams successfully generated from this file.
    """
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception as e:
        LOGGER.error(f"Could not read {md_path}: {e}")
        return 0
        
    blocks = MERMAID_REGEX.findall(content)
    if not blocks:
        return 0
        
    success_count = 0
    total_blocks = len(blocks)
    
    for idx, code in enumerate(blocks, start=1):
        # Append index only if there are multiple diagrams in the file
        suffix = f"_{idx}" if total_blocks > 1 else ""
        out_filename = f"{md_path.stem}{suffix}.{output_format}"
        out_path = md_path.parent / out_filename
        
        if process_single_diagram(code, out_path):
            success_count += 1
            
    return success_count


def run_batch_conversion(target_dir: str, output_format: str, max_workers: int) -> None:
    """
    Orchestrates the multithreaded batch processing of all Markdown files.
    
    Args:
        target_dir (str): The root directory to search for .md files.
        output_format (str): The format to export the diagrams as.
        max_workers (int): The number of concurrent threads to use.
    """
    target_path = Path(target_dir)
    
    if not target_path.exists() or not target_path.is_dir():
        LOGGER.error(f"Target directory '{target_dir}' does not exist or is not a directory.")
        return

    md_files = list(target_path.rglob("*.md"))
    LOGGER.info(f"Found {len(md_files)} markdown files in '{target_dir}'. Starting batch conversion...")
    
    total_generated = 0
    
    # Utilize ThreadPoolExecutor to run conversions in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks to the executor
        future_to_md = {
            executor.submit(process_markdown_file, md_file, output_format): md_file 
            for md_file in md_files
        }
        
        # Gather results as they complete
        for future in as_completed(future_to_md):
            md_file = future_to_md[future]
            try:
                result = future.result()
                total_generated += result
            except Exception as e:
                LOGGER.error(f"Unhandled exception while analyzing {md_file.name}: {e}")
                
    LOGGER.info(f"Batch conversion completed! Generated {total_generated} diagrams in total.")
    LOGGER.info(f"Detailed logs saved to: {Path(LOG_FILE).absolute()}")


def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments for the script.
    
    Returns:
        argparse.Namespace: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Extract and convert Mermaid blocks from Markdown files to images."
    )
    parser.add_argument(
        "-d", "--directory", 
        type=str, 
        default="doc", 
        help="Target directory to scan recursively (default: 'doc')"
    )
    parser.add_argument(
        "-f", "--format", 
        type=str, 
        choices=["svg", "png", "pdf"], 
        default="svg", 
        help="Output image format (default: 'svg')"
    )
    parser.add_argument(
        "-w", "--workers", 
        type=int, 
        default=4, 
        help="Number of parallel worker threads (default: 4)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    run_batch_conversion(args.directory, args.format, args.workers)