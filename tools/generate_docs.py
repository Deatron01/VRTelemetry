import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

# Load environment variables from .env
load_dotenv()

# Initialize the Gemini Client
client = genai.Client()

# Project directory paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [PROJECT_ROOT / "src", PROJECT_ROOT / "CentralServer", PROJECT_ROOT / "LicenseServer"]
DOC_ROOT = PROJECT_ROOT / "doc"

# Allowed folder names for diagram categorization
VALID_FOLDERS = [
    "activity",
    "api",
    "architecture",
    "c4",
    "configuration",
    "dataflow",
    "deployment",
    "developer",
    "performance",
    "pipeline",
    "sequence",
    "shutdown",
    "state",
    "telemetry",
    "testing",
    "uml",
]

FOLDER_LIST_STR = " | ".join(VALID_FOLDERS)

# Template and formatting guidelines
SYSTEM_PROMPT = f"""
You are an expert technical documentation agent.
Analyze the provided source code (Python, TypeScript, or React) and return a JSON object with this exact schema:
{{
  "module_summary_md": "Formatted Markdown string following the strict 3-section template below.",
  "diagram_type": "{FOLDER_LIST_STR} | null",
  "diagram_filename": "descriptive_name.md",
  "mermaid_md": "Full markdown text containing a ```mermaid ... ``` block if relevant, else null"
}}

---
### MARKDOWN TEMPLATE FOR 'module_summary_md':
You MUST structure the Markdown content using strictly these three headings:

### Purpose
[2-4 sentences explaining the module's core responsibility, role in the system, and why it exists.]

### Key Components / Key Classes / Key Exports
- **`ClassName` / `FunctionName`**: Concise description of its contract, responsibilities, and behavior.
- **`AnotherComponent`**: Concise description...

### Integration Points
[Explain how this module interfaces with other parts of the project, external APIs, hardware drivers, state stores, or lifecycle hooks.]
---

CRITICAL INSTRUCTIONS:
1. Output ONLY valid JSON.
2. Select 'diagram_type' strictly from the allowed list: {VALID_FOLDERS} or 'null'.
3. Do not include introductory pleasantries or trailing commentary inside 'module_summary_md'.
"""

# Supported file extensions
ALLOWED_EXTENSIONS = {".py", ".tsx", ".ts", ".jsx", ".js"}

# Directories to ignore
IGNORE_DIRS = {
    "node_modules",
    "dist",
    "build",
    ".vite",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".git",
}


def process_file(file_path: Path):
    try:
        with open(file_path, encoding="utf-8") as f:
            code = f.read()
    except Exception as e:
        print(f"[-] Could not read {file_path}: {e}")
        return

    # Skip empty or negligible files
    if len(code.strip()) < 40:
        return

    rel_path = file_path.relative_to(PROJECT_ROOT)
    print(f"[>] Analyzing {rel_path}...")

    prompt = f"File: {file_path.name}\nPath: {rel_path}\n\nContent:\n{code}"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            chat = client.chats.create(
                model="gemini-3.5-flash-lite",
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "OBJECT",
                        "properties": {
                            "module_summary_md": {"type": "STRING"},
                            "diagram_type": {"type": "STRING", "enum": VALID_FOLDERS + ["null"]},
                            "diagram_filename": {"type": "STRING"},
                            "mermaid_md": {"type": "STRING"},
                        },
                        "required": [
                            "module_summary_md",
                            "diagram_type",
                            "diagram_filename",
                            "mermaid_md",
                        ],
                    },
                },
            )

            response = chat.send_message(prompt)
            data = json.loads(response.text)

            # 1. Save Structured Markdown Summary
            summary_md = data.get("module_summary_md")
            if summary_md:
                doc_file = file_path.parent / f"{file_path.stem}_doc.md"
                with open(doc_file, "w", encoding="utf-8") as out:
                    out.write(summary_md.strip() + "\n")
                print(f"    [+] Saved summary to: {doc_file.relative_to(PROJECT_ROOT)}")

            # 2. Save Mermaid Diagram
            diag_type = data.get("diagram_type")
            diag_file = data.get("diagram_filename")
            mermaid_md = data.get("mermaid_md")

            if diag_type and diag_type in VALID_FOLDERS and mermaid_md:
                target_subfolder = DOC_ROOT / diag_type
                target_subfolder.mkdir(parents=True, exist_ok=True)

                filename = (
                    diag_file if diag_file and diag_file.endswith(".md") else f"{file_path.stem}.md"
                )
                output_file = target_subfolder / filename

                with open(output_file, "w", encoding="utf-8") as out:
                    out.write(mermaid_md.strip() + "\n")
                print(f"    [+] Saved diagram to: {output_file.relative_to(PROJECT_ROOT)}")

            break

        except json.JSONDecodeError:
            print(f"    [!] JSON decode error on attempt {attempt + 1}. Retrying...")
            time.sleep(2)
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                wait_time = 60
                print(
                    f"    [!] Rate limit hit! Waiting {wait_time}s before retry ({attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
            else:
                print(f"[-] Error processing {file_path.name}: {e}")
                break


def main():
    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            continue

        print(f"\n--- Scanning directory: {target_dir.name} ---")
        for root, dirs, files in os.walk(target_dir):
            # Exclude build and dependency directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in ALLOWED_EXTENSIONS:
                    process_file(file_path)
                    time.sleep(4.0)

    print("\n[✓] Documentation generation complete!")


if __name__ == "__main__":
    main()
