#!/usr/bin/env python3
"""
House Clerk Financial/PTR scraper
---------------------------------
Generic, typed, and ready for CLI use.

Example:
    python clerk_scraper.py --last-name Pelosi --top-n 1
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# ──────────────────────────── Constants ──────────────────────────── #

BASE_URL = "https://disclosures-clerk.house.gov"
SEARCH_PAGE = f"{BASE_URL}/FinancialDisclosure/ViewSearch"
SEARCH_API = f"{BASE_URL}/FinancialDisclosure/ViewMemberSearchResult"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DisclosureScraper/1.0; +https://github.com/your-org)"
    )
}
TIMEOUT = 30  # seconds

# ──────────────────────────── Exceptions ──────────────────────────── #


class DisclosureScraperError(RuntimeError):
    """Generic scraper exception."""


# ──────────────────────────── Data Model ──────────────────────────── #


@dataclass(slots=True)
class FilingRecord:
    """Single filing entry parsed from result table."""

    name: str
    office: str
    filing_year: int
    report_type: str
    pdf_url: str

    @property
    def filing_id(self) -> str:
        return self.pdf_url.rstrip(".pdf").split("/")[-1]


# ──────────────────────────── Scraper Logic ──────────────────────────── #


class ClerkScraper:
    """Scraper encapsulating session & helper functions."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ---------- public API ------------------------------------------------ #

    def fetch_filings(
        self,
        last_name: str,
        *,
        year: str = "",
        state: str = "",
        district: str = "",
    ) -> List[FilingRecord]:
        """
        Search filings for given member filters and return parsed records.
        """
        logging.info("Fetching search page to obtain hidden form fields…")
        hidden_fields = self._get_hidden_fields()

        # Build payload
        payload: Dict[str, str] = {
            **hidden_fields,
            "LastName": last_name,
            "FilingYear": year,
            "State": state,
            "District": district,
        }

        logging.info("Submitting search form for '%s' …", last_name)
        response = self.session.post(SEARCH_API, data=payload, timeout=TIMEOUT)
        response.raise_for_status()

        return self._parse_results(response.text)

    # ---------- helpers --------------------------------------------------- #

    def _get_hidden_fields(self) -> Dict[str, str]:
        """Grab __VIEWSTATE / tokens from the initial search page."""
        resp = self.session.get(SEARCH_PAGE, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        form: Optional[Tag] = soup.find(
            "form", {"action": "/FinancialDisclosure/ViewMemberSearchResult"}
        )
        if form is None:
            raise DisclosureScraperError("Search form not found. Page layout changed.")

        fields: Dict[str, str] = {}
        for inp in form.find_all("input", {"type": ["hidden", "submit"]}):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")
        if not fields:
            raise DisclosureScraperError("No hidden form fields extracted.")
        return fields

    def _parse_results(self, html: str) -> List[FilingRecord]:
        """Parse HTML table into FilingRecord list."""
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", {"class": "library-table"})
        if table is None:
            raise DisclosureScraperError("Result table not found.")

        rows = table.find_all("tr")[1:]  # skip header
        records: List[FilingRecord] = []
        for tr in rows:
            cols = [td.get_text(strip=True) for td in tr.find_all("td")]
            link_tag = tr.find("a")
            if not cols or link_tag is None:
                continue  # skip malformed rows
            pdf_url = urljoin(BASE_URL, link_tag["href"])
            try:
                filing_year = int(cols[2])
            except ValueError:
                logging.warning("Unable to parse filing year for row: %s", cols)
                continue
            record = FilingRecord(
                name=cols[0],
                office=cols[1],
                filing_year=filing_year,
                report_type=cols[3],
                pdf_url=pdf_url,
            )
            records.append(record)

        if not records:
            raise DisclosureScraperError("No filing records parsed.")
        return records


# ──────────────────────────── Utility Functions ──────────────────────────── #


def select_latest(records: List[FilingRecord], *, top_n: int = 1) -> List[FilingRecord]:
    """
    Return filings belonging to the newest `top_n` years.

    Sorted first by filing_year DESC then filing_id DESC.
    """
    newest_years = sorted({r.filing_year for r in records}, reverse=True)[:top_n]
    latest = [r for r in records if r.filing_year in newest_years]
    latest.sort(key=lambda r: (r.filing_year, r.filing_id), reverse=True)
    return latest


# ──────────────────────────── CLI ──────────────────────────── #


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape House PTR / FD filings.")
    p.add_argument("--last-name", required=True, help="Member last name, e.g. Pelosi")
    p.add_argument("--year", default="", help="Filter by filing year (optional)")
    p.add_argument("--state", default="", help="Filter by state code, e.g. CA (opt)")
    p.add_argument("--district", default="", help="Filter by district code (opt)")
    p.add_argument(
        "--top-n", type=int, default=1, help="Return filings for N latest years"
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logs")
    return p


def main(argv: List[str] | None = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    scraper = ClerkScraper()
    try:
        all_records = scraper.fetch_filings(
            last_name=args.last_name,
            year=args.year,
            state=args.state,
            district=args.district,
        )
        latest = select_latest(all_records, top_n=args.top_n)
    except (requests.RequestException, DisclosureScraperError) as err:
        logging.error("Scraping failed: %s", err)
        sys.exit(1)

    print(f"Found {len(latest)} filings for newest {args.top_n} year(s):")
    for rec in latest:
        print(f"{rec.filing_year} | {rec.filing_id} | {rec.pdf_url}")


if __name__ == "__main__":
    main()
