import json
from datetime import datetime, timezone
from typing import List, Optional

from knowledge_map.adapters.sqlite_db import (
    DEFAULT_DB_PATH,
    insert_selector_version,
    get_selector_versions,
    update_selector_window,
    get_selector_version_by_id
)
from knowledge_map.schemas.selectors import ArticleSelectors, SelectorVersion

def parse_db_datetime(val: str) -> datetime:
    """
    Parses an ISO 8601 string from SQLite and returns a timezone-aware UTC datetime.
    """
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_datetime_utc(dt: datetime) -> str:
    """
    Formats a datetime as an ISO 8601 UTC string ending with 'Z'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def add_selector_version(
    publication_id: str,
    selectors: ArticleSelectors,
    earliest_success_date: datetime,
    latest_success_date: datetime,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Saves a selector version using the core database adapters.
    """
    earliest_str = format_datetime_utc(earliest_success_date)
    latest_str = format_datetime_utc(latest_success_date)
    selectors_json = json.dumps(selectors.model_dump())
    
    return insert_selector_version(
        publication_id=publication_id,
        selectors_json=selectors_json,
        earliest_success_date=earliest_str,
        latest_success_date=latest_str,
        db_path=db_path
    )


def get_selector_versions_by_proximity(
    publication_id: str,
    fetch_date: datetime,
    db_path: str = DEFAULT_DB_PATH
) -> List[SelectorVersion]:
    """
    Yields selector versions for a given publication ordered by success-window proximity.
    """
    if fetch_date.tzinfo is None:
        fetch_date = fetch_date.replace(tzinfo=timezone.utc)
    else:
        fetch_date = fetch_date.astimezone(timezone.utc)

    raw_versions = get_selector_versions(publication_id, db_path=db_path)
    parsed_versions = []
    
    for r in raw_versions:
        selectors_dict = json.loads(r["selectors_json"])
        selectors = ArticleSelectors(**selectors_dict)
        
        earliest = parse_db_datetime(r["earliest_success_date"])
        latest = parse_db_datetime(r["latest_success_date"])
        created_at = parse_db_datetime(r["created_at"]) if r.get("created_at") else None
        
        version = SelectorVersion(
            id=r["id"],
            publication_id=r["publication_id"],
            selectors=selectors,
            earliest_success_date=earliest,
            latest_success_date=latest,
            created_at=created_at
        )
        parsed_versions.append(version)

    def calculate_distance(v: SelectorVersion) -> float:
        if v.earliest_success_date <= fetch_date <= v.latest_success_date:
            return 0.0
        dist = min(abs(fetch_date - v.earliest_success_date), abs(fetch_date - v.latest_success_date))
        return dist.total_seconds()

    # Sort key: distance ascending, then id descending (newer first)
    parsed_versions.sort(key=lambda x: (calculate_distance(x), -(x.id or 0)))
    return parsed_versions


def widen_selector_version_window(
    selector_version_id: int,
    fetch_date: datetime,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Widens the validity success window of a selector version to include fetch_date.
    """
    if fetch_date.tzinfo is None:
        fetch_date = fetch_date.replace(tzinfo=timezone.utc)
    else:
        fetch_date = fetch_date.astimezone(timezone.utc)

    row = get_selector_version_by_id(selector_version_id, db_path=db_path)
    if not row:
        raise ValueError(f"Selector version {selector_version_id} not found.")

    earliest = parse_db_datetime(row["earliest_success_date"])
    latest = parse_db_datetime(row["latest_success_date"])

    new_earliest = min(earliest, fetch_date)
    new_latest = max(latest, fetch_date)

    update_selector_window(
        selector_version_id=selector_version_id,
        earliest_success_date=format_datetime_utc(new_earliest),
        latest_success_date=format_datetime_utc(new_latest),
        db_path=db_path
    )
