"""Funding-news discovery: headline parsing, Inc42 deal tables, accumulation, metadata."""
from pathlib import Path
import pytest
from src.funding_discovery import (
    Deal,
    merge_deals,
    meta_rows,
    parse_amount,
    parse_feed,
    parse_headline,
    read_inputs,
    stage_to_segment,
    write_inputs,
)
from src.discovery import load_input_companies
from src.registry import CompanyMeta

FIXTURES = Path(__file__).parent / "fixtures"


def feed(name: str, source: str):
    return parse_feed((FIXTURES / name).read_text(encoding="utf-8"), source)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Space robotics startup Orbitly raises $1.5 Mn in pre-seed round", ("Orbitly", "pre-seed", 1.5)),
        ("Z47 leads $12.5 Mn Series A round in Kavach Health", ("Kavach Health", "Series A", 12.5)),
        ("Exclusive: Gridly kicks off pre-Series B round at 50% valuation premium", ("Gridly", "pre-Series B", None)),
        ("Enterprise AI Startup CanvasIQ Nets $29 Mn To Expand GTM Teams", ("CanvasIQ", "", 29.0)),
        ("Metalworks raises Rs 27 Cr led by IAN Alpha Fund", ("Metalworks", "", 3.105)),
        ("Google.org backs The/Nudge with $15 Mn to digitise MSMEs", ("The/Nudge", "", 15.0)),
    ],
)
def test_parse_funding_headlines(title, expected):
    assert parse_headline(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Bigco Imaging raises Rs 255 Cr from anchor investors ahead of IPO",
        "Frontier Advisors raises Rs 3,000 Cr for growth-stage AI and deeptech fund",
        "Funding and acquisitions in Indian startups this week [Oct 12- Oct 17]",
        "From Fitbolt To Orbitly — Indian Startups Raised Over $236 Mn This Week",
        "Quickhelp posts Rs 12 Cr revenue and Rs 168 Cr loss in FY26",
        "Urban Living Board Clears Plans To Raise Up To ₹2,500 Cr",
        "Cult.fit gets SEBI nod for proposed IPO",
        "",
    ],
)
def test_non_deal_headlines_are_skipped(title):
    assert parse_headline(title) is None


@pytest.mark.parametrize(
    "text, usd_mn",
    [("$29 Mn", 29.0), ("$1.5 Mn", 1.5), ("Rs 255 Cr", 29.325), ("₹109 Cr", 12.535), ("Rs 3,000 Cr", 345.0), ("$1.2 Bn", 1200.0), ("no money", None)],
)
def test_parse_amount(text, usd_mn):
    assert parse_amount(text) == usd_mn


@pytest.mark.parametrize(
    "stage, amount, segment",
    [
        ("Pre-Seed", None, "seed"), ("Seed", 9.0, "seed"), ("angel", None, "seed"),
        ("Series A", 30.0, "series_a"), ("pre-Series A", None, "series_a"),
        ("Series B", None, "series_b"), ("pre-Series B", None, "series_b"),
        ("Series C", 10.0, "series_c_plus"), ("Series E", None, "series_c_plus"),
        ("", 4.0, "seed"), ("", 5.0, "seed"), ("", 12.0, "series_a"), ("", 34.6, "series_b"),
        ("", 80.0, "series_c_plus"), ("", None, "unknown"), ("–", None, "unknown"),
    ],
)
def test_stage_to_segment(stage, amount, segment):
    assert stage_to_segment(stage, amount) == segment


def test_entrackr_feed_yields_only_startup_rounds():
    deals = feed("funding_entrackr_sample.xml", "entrackr")
    assert [d.name for d in deals] == ["Orbitly", "Kavach Health", "Gridly", "SmileCo", "Metalworks"]
    assert deals[0].published == "2026-10-18"
    assert deals[0].segment == "seed"
    assert {d.source for d in deals} == {"entrackr"}


def test_inc42_funding_table_rows_are_read():
    deals = feed("funding_inc42_sample.xml", "inc42")
    by_name = {d.name: d for d in deals}
    assert set(by_name) == {"Fitbolt", "GreenMove", "Orbitly", "AdLeaf", "CanvasIQ"}
    assert by_name["Fitbolt"].segment == "series_b"
    assert by_name["GreenMove"].stage == "" and by_name["GreenMove"].segment == "series_b"
    assert by_name["AdLeaf"].amount_usd_mn is None and by_name["AdLeaf"].segment == "seed"
    assert by_name["Orbitly"].sector == "Advanced Hardware & Technology"


def test_malformed_feed_returns_no_deals():
    assert parse_feed("<rss><channel><item>", "entrackr") == []


def test_deals_accumulate_and_keep_latest_round(tmp_path):
    path = tmp_path / "funding_news.csv"
    first = merge_deals([], [Deal("Orbitly", "Pre-Seed", 1.5, "Space", "2026-03-01", "inc42", "l1")])
    write_inputs(first, path)
    later = merge_deals(read_inputs(path), [
        Deal("Orbitly", "Series A", 12.0, "", "2026-10-01", "entrackr", "l2"),
        Deal("Kavach Health", "Series A", 12.5, "", "2026-10-02", "entrackr", "l3"),
        Deal("Orbitly", "Seed", 3.0, "", "2026-05-01", "inc42", "old"),
    ])
    write_inputs(later, path)
    rows = {r["name"]: r for r in read_inputs(path)}
    assert set(rows) == {"Orbitly", "Kavach Health"}
    assert rows["Orbitly"]["segment"] == "series_a"
    assert rows["Orbitly"]["sector"] == "Space"
    # discover reads the name column and ignores the extra columns.
    assert {i["name"] for i in load_input_companies([str(path)])} == {"Orbitly", "Kavach Health"}


def test_same_day_duplicate_keeps_the_row_naming_the_round():
    rows = merge_deals([], [
        Deal("CanvasIQ", "Series B", 29.0, "AI", "2026-10-16", "inc42", "a"),
        Deal("CanvasIQ", "", 29.0, "", "2026-10-16", "entrackr", "b"),
    ])
    assert rows[0]["stage"] == "Series B" and rows[0]["sector"] == "AI"


def test_funding_stage_overrides_headcount_estimate_but_keeps_team_size():
    rows = merge_deals([], [Deal("GoLorry", "Series A", 10.0, "", "2026-10-01", "entrackr", "x")])
    existing = {"golorry": CompanyMeta("GoLorry", "seed", 30, "India", "yc:S18")}
    meta = meta_rows(rows, existing)
    assert meta == [CompanyMeta("GoLorry", "series_a", 30, "India", "funding:entrackr:2026-10-01")]
