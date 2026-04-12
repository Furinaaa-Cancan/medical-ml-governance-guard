#!/usr/bin/env python3
"""Fetch NHANES Aug 2021 - Aug 2023 codebook metadata from CDC.

Scrapes variable definitions and codebooks from the CDC NHANES website
for the latest cycle (_L suffix), then outputs in the same TSV format
as Harvard CCB-HMS metadata for merging.

Usage:
  python3 scripts/tools/fetch_nhanes_2021_2023.py
"""
from __future__ import annotations

import csv
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CDC_BASE = "https://wwwn.cdc.gov"

# All known 2021-2023 data file pages by component
COMPONENT_URLS = {
    "Demographics": "/nchs/nhanes/search/datapage.aspx?Component=Demographics&Cycle=2021-2023",
    "Examination": "/nchs/nhanes/search/datapage.aspx?Component=Examination&Cycle=2021-2023",
    "Laboratory": "/nchs/nhanes/search/datapage.aspx?Component=Laboratory&Cycle=2021-2023",
    "Questionnaire": "/nchs/nhanes/search/datapage.aspx?Component=Questionnaire&Cycle=2021-2023",
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_VARS = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_2021_2023_variables.tsv"
OUTPUT_CODES = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_2021_2023_codebooks.tsv"


# ── HTML Parsing ─────────────────────────────────────────────────────────────

class DataPageParser(HTMLParser):
    """Extract doc file URLs from NHANES data page."""

    def __init__(self):
        super().__init__()
        self.doc_urls: List[str] = []
        self._in_a = False
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.endswith(".htm") and "/DataFiles/" in href:
                self.doc_urls.append(href)


class CodebookPageParser(HTMLParser):
    """Extract variable definitions and codebook from a NHANES doc (.htm) page."""

    def __init__(self):
        super().__init__()
        self.variables: List[Dict[str, str]] = []
        self.codebook_entries: List[Dict[str, str]] = []
        self.table_name = ""

        self._in_h3 = False
        self._h3_text = ""
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._td_texts: List[str] = []
        self._current_td = ""
        self._current_var_name = ""
        self._current_var_label = ""
        self._section = ""  # "variable_list" or "codebook"
        self._var_sections: List[Dict[str, str]] = []
        self._collecting_dd = False
        self._dd_key = ""
        self._dd_value = ""

        # Simplified approach: collect all text, parse structure
        self._all_text = []
        self._in_body = False
        self._raw_html = ""

    def feed(self, data):
        self._raw_html = data
        super().feed(data)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True

    def handle_data(self, data):
        if self._in_body:
            self._all_text.append(data)


def parse_codebook_page(html: str, table_name: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse a NHANES codebook HTML page into variables and codebook entries.

    Uses regex-based extraction since the HTML structure varies across tables.
    """
    variables = []
    codebook_entries = []

    # Extract variable sections: each starts with a variable name header
    # Pattern: <h3 id="VARNAME">VARNAME - Label</h3>
    var_pattern = re.compile(
        r'<h3[^>]*id="([^"]+)"[^>]*>\s*(\w+)\s*[-–—]\s*(.+?)\s*</h3>',
        re.IGNORECASE,
    )

    for m in var_pattern.finditer(html):
        var_code = m.group(2).strip()
        label = re.sub(r"<[^>]+>", "", m.group(3)).strip()

        # Find the section after this h3 until the next h3
        start = m.end()
        next_h3 = re.search(r"<h3", html[start:], re.IGNORECASE)
        section_html = html[start : start + next_h3.start()] if next_h3 else html[start:]

        # Extract description fields (SAS Label, English Text, Target, etc.)
        sas_label = ""
        english_text = ""
        english_instructions = ""
        target_pop = ""

        # Look for dt/dd pairs
        dd_pattern = re.compile(r"<dt>([^<]+)</dt>\s*<dd>([^<]*(?:<[^>]+>[^<]*)*)</dd>", re.IGNORECASE)
        for dd_m in dd_pattern.finditer(section_html):
            key = dd_m.group(1).strip().lower()
            val = re.sub(r"<[^>]+>", "", dd_m.group(2)).strip()
            if "sas label" in key:
                sas_label = val
            elif "english text" in key:
                english_text = val
            elif "english instruction" in key:
                english_instructions = val
            elif "target" in key:
                target_pop = val

        if not sas_label:
            sas_label = label

        variables.append({
            "Variable": var_code,
            "Table": table_name,
            "SASLabel": sas_label,
            "EnglishText": english_text or sas_label,
            "EnglishInstructions": english_instructions,
            "Target": target_pop,
            "UseConstraints": "",
            "IsPhenotype": "FALSE",
            "OntologyMapped": "False",
        })

        # Extract codebook table
        # Pattern: <table ...> rows with code/value/description/count
        table_pattern = re.compile(r"<table[^>]*class=\"values\"[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
        table_m = table_pattern.search(section_html)
        if not table_m:
            # Try any table in the section
            table_m = re.search(r"<table[^>]*>(.*?)</table>", section_html, re.IGNORECASE | re.DOTALL)

        if table_m:
            # Extract rows
            row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
            cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)

            rows = row_pattern.findall(table_m.group(1))
            for row_html in rows[1:]:  # skip header row
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cell_pattern.findall(row_html)]
                if len(cells) >= 4:
                    code_or_value = cells[0]
                    value_desc = cells[1]
                    count = cells[2]
                    cumulative = cells[3]
                    skip_to = cells[4] if len(cells) > 4 else ""

                    codebook_entries.append({
                        "Variable": var_code,
                        "Table": table_name,
                        "CodeOrValue": code_or_value,
                        "ValueDescription": value_desc,
                        "Count": count,
                        "Cumulative": cumulative,
                        "SkipToItem": skip_to,
                    })

    return variables, codebook_entries


def fetch_url(url: str, retries: int = 3) -> str:
    """Fetch URL with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MLGG-NHANES-Codebook/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def main() -> int:
    all_variables: List[Dict] = []
    all_codebooks: List[Dict] = []

    # Step 1: Get all doc URLs from each component page
    doc_urls: List[Tuple[str, str]] = []  # (table_name, doc_url)

    for component, path in COMPONENT_URLS.items():
        url = CDC_BASE + path
        print(f"Fetching {component} page list...")
        try:
            html = fetch_url(url)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        parser = DataPageParser()
        parser.feed(html)

        for doc_url in parser.doc_urls:
            # Extract table name from URL: /Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.htm
            table_m = re.search(r"/(\w+)\.htm$", doc_url, re.IGNORECASE)
            if table_m:
                table_name = table_m.group(1)
                full_url = doc_url if doc_url.startswith("http") else CDC_BASE + doc_url
                doc_urls.append((table_name, full_url))

        print(f"  Found {len(parser.doc_urls)} doc files")

    print(f"\nTotal doc files to process: {len(doc_urls)}")

    # Step 2: Parse each codebook page
    for i, (table_name, doc_url) in enumerate(doc_urls):
        print(f"  [{i+1}/{len(doc_urls)}] {table_name}...", end="", flush=True)
        try:
            html = fetch_url(doc_url)
            variables, codebooks = parse_codebook_page(html, table_name)
            all_variables.extend(variables)
            all_codebooks.extend(codebooks)
            print(f" {len(variables)} vars, {len(codebooks)} codes")
        except Exception as e:
            print(f" ERROR: {e}")
        time.sleep(0.5)  # rate limit

    # Step 3: Write TSV files
    print(f"\nWriting {len(all_variables)} variables to {OUTPUT_VARS}...")
    with open(OUTPUT_VARS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter="\t",
            fieldnames=["Variable", "Table", "SASLabel", "EnglishText",
                        "EnglishInstructions", "Target", "UseConstraints",
                        "IsPhenotype", "OntologyMapped"])
        writer.writeheader()
        writer.writerows(all_variables)

    print(f"Writing {len(all_codebooks)} codebook entries to {OUTPUT_CODES}...")
    with open(OUTPUT_CODES, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, delimiter="\t",
            fieldnames=["Variable", "Table", "CodeOrValue", "ValueDescription",
                        "Count", "Cumulative", "SkipToItem"])
        writer.writeheader()
        writer.writerows(all_codebooks)

    print(f"\nDone! 2021-2023 cycle ({len(all_variables)} variables, {len(all_codebooks)} codebook entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
