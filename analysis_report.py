#!/usr/bin/env python3
# robust_ptr_parser.py
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

import pdfplumber
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

PDF_FILE = Path("20026590.pdf")
DASH = r"[-–—]"  # hyphen, en-dash, em-dash
NULL_RE = re.compile(r"[\x00-\x1F\x7F]")

# ─────────────────────────── Regex ─────────────────────────── #
ROW_RE = re.compile(
    rf"""
    ^SP\s+
    (?P<asset_head>.+?)\s+                              # part before action
    (?P<action>P(?:urchase)?|S(?:ale)?(?:\s*\(partial\))?)\s+
    (?P<trans_date>\d{{2}}/\d{{2}}/\d{{4}})\s+
    (?P<notif_date>\d{{2}}/\d{{2}}/\d{{4}})\s+
    \$?(?P<amt_low>[\d,]+)\s*{DASH}\s+
    (?P<asset_tail>.+?)\s+\[(?P<atype>\w{{2}})]\s+      # until [OP]/[ST]
    \$?(?P<amt_high>[\d,]+)
    """,
    re.VERBOSE,
)


# ─────────────────────────── Helpers ─────────────────────────── #
def _clean(s: str) -> str:
    s = NULL_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _join_rows(text: str) -> List[str]:
    """
    Merge physical lines into logical rows starting with 'SP '.
    """
    logical, buf = [], []
    for raw in text.splitlines():
        ln = _clean(raw)
        if not ln:
            continue
        if ln.startswith("SP "):
            if buf:
                logical.append(" ".join(buf))
            buf = [ln]
        else:
            buf.append(ln)
    if buf:
        logical.append(" ".join(buf))
    return logical


# ─────────────────────────── Core Parser ─────────────────────────── #
def parse_transactions(pdf_path: Path | str) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, 1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            for line in _join_rows(text):
                m = ROW_RE.search(line)
                if m:
                    gd = m.groupdict()
                    gd["asset"] = (
                        f'{gd.pop("asset_head")} {gd.pop("asset_tail")}'.strip()
                    )
                    rows.append(gd)
                else:
                    logging.debug("p%d no-match: %s", idx, line)

    if not rows:
        raise ValueError("No transaction rows parsed – adjust regex again.")

    df = pd.DataFrame(rows)
    # convert amounts to int
    df[["amt_low", "amt_high"]] = df[["amt_low", "amt_high"]].apply(
        lambda s: s.str.replace(",", "", regex=False).astype("int64")
    )
    # re-order columns
    df = df[
        [
            "asset",
            "atype",
            "action",
            "trans_date",
            "notif_date",
            "amt_low",
            "amt_high",
        ]
    ]
    return df


# ─────────────────────────── CLI Test ─────────────────────────── #
if __name__ == "__main__":
    df = parse_transactions(PDF_FILE)
    print(df.to_string(index=False))
