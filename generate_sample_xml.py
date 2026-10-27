"""
Generate a sample XML file from fictional test data.

Run:  python generate_sample_xml.py

Outputs: sample_refinance_batch.xml
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.conftest import _make_row
from services.xml_service import generate_xml, validate_xml

import pandas as pd


def main():
    # Create 3 fictional records
    rows = [_make_row(i) for i in range(1, 4)]
    df = pd.DataFrame(rows)

    xml_str = generate_xml(df)

    # Validate
    is_valid, msg = validate_xml(xml_str)
    print(f"Validation: {msg}")

    # Write to file
    out_path = Path(__file__).resolve().parent / "sample_refinance_batch.xml"
    out_path.write_text(xml_str, encoding="utf-8")
    print(f"Sample XML written to: {out_path}")


if __name__ == "__main__":
    main()
