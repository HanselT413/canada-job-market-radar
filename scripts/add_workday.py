"""Add a Workday company to config/search.yaml from its careers-page URL.

    python3 scripts/add_workday.py "https://cibc.wd3.myworkdayjobs.com/search" "CIBC"
    python3 scripts/add_workday.py "https://bmo.wd3.myworkdayjobs.com/en-US/External/job/..." "BMO"

The URL can be any page on the company's Workday career site (search page or a job).
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

CONFIG = Path(__file__).resolve().parents[1] / "config" / "search.yaml"
LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")  # e.g. en-US, fr-CA


def parse_workday_url(url: str) -> dict:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if not host.endswith(".myworkdayjobs.com"):
        raise ValueError("Not a Workday career site URL (it should contain myworkdayjobs.com)")
    tenant = host.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p]
    if parts and LOCALE.match(parts[0]):
        parts = parts[1:]
    if parts[:3] == ["wday", "cxs", tenant]:
        parts = parts[3:]
    if not parts:
        raise ValueError("The URL has no career-site name after the domain")
    return {"host": host, "tenant": tenant, "site": parts[0]}


def add_to_config(entry: dict, company: str, config_path: Path = CONFIG) -> str:
    text = config_path.read_text()
    if f"host: {entry['host']}, tenant: {entry['tenant']}, site: {entry['site']}," in text:
        return "already in the list"
    line = (f"  - {{host: {entry['host']}, tenant: {entry['tenant']}, "
            f"site: {entry['site']}, company: {company}}}\n")
    marker = "workday_settings:"
    if marker not in text:
        raise ValueError("config/search.yaml has no workday_settings section")
    config_path.write_text(text.replace(marker, line + marker, 1))
    return "added"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    try:
        entry = parse_workday_url(sys.argv[1])
        status = add_to_config(entry, sys.argv[2])
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(f"{sys.argv[2]}: {status} -> {entry}")
    print("It will be included in the next run (robots.txt is checked automatically).")
