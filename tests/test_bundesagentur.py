"""Tests for the Bundesagentur für Arbeit search provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from immermatch.bundesagentur import (
    BundesagenturProvider,
    _build_ba_link,
    _JobStub,
    _parse_location,
    _parse_search_results,
    _stub_to_listing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stellenangebot(
    hash_id: str = "abc123",
    beruf: str = "Python Entwickler",
    arbeitgeber: str = "ACME GmbH",
    ort: str = "Berlin",
    region: str = "Berlin",
    land: str = "Deutschland",
    refnr: str = "10000-1234567890-S",
    posted: str = "2026-02-25",
) -> dict:
    return {
        "hashId": hash_id,
        "beruf": beruf,
        "arbeitgeber": arbeitgeber,
        "refnr": refnr,
        "aktuelleVeroeffentlichungsdatum": posted,
        "arbeitsort": {"ort": ort, "region": region, "land": land},
    }


def _make_search_response(
    items: list[dict] | None = None,
    total: int | None = None,
) -> dict:
    items = items if items is not None else [_make_stellenangebot()]
    return {
        "stellenangebote": items,
        "maxErgebnisse": str(total if total is not None else len(items)),
        "page": "0",
        "size": "50",
    }


def _make_detail_response(
    stellenbeschreibung: str = "Full job description here.",
    titel: str = "Python Entwickler (m/w/d)",
    arbeitgeber: str = "ACME GmbH",
    allianz_url: str | None = None,
) -> dict:
    d: dict = {
        "stellenbeschreibung": stellenbeschreibung,
        "titel": titel,
        "arbeitgeber": arbeitgeber,
    }
    if allianz_url:
        d["allianzPartnerUrl"] = allianz_url
    return d


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestBuildBaLink:
    def test_simple(self) -> None:
        assert _build_ba_link("abc123") == "https://www.arbeitsagentur.de/jobsuche/suche?id=abc123"


class TestParseLocation:
    def test_full(self) -> None:
        assert _parse_location({"ort": "Berlin", "region": "Berlin", "land": "Deutschland"}) == "Berlin, Deutschland"

    def test_city_and_different_region(self) -> None:
        assert _parse_location({"ort": "München", "region": "Bayern", "land": "Deutschland"}) == (
            "München, Bayern, Deutschland"
        )

    def test_empty(self) -> None:
        assert _parse_location({}) == "Germany"

    def test_city_only(self) -> None:
        assert _parse_location({"ort": "Hamburg"}) == "Hamburg"


class TestParseSearchResults:
    def test_valid_items(self) -> None:
        data = _make_search_response(
            [
                _make_stellenangebot(hash_id="a1", beruf="Dev", arbeitgeber="Co"),
                _make_stellenangebot(hash_id="a2", beruf="QA", arbeitgeber="Co2"),
            ]
        )
        stubs = _parse_search_results(data)
        assert len(stubs) == 2
        assert stubs[0].hash_id == "a1"
        assert stubs[0].title == "Dev"
        assert stubs[1].hash_id == "a2"

    def test_skips_missing_hash(self) -> None:
        data = {"stellenangebote": [{"beruf": "Dev"}]}
        assert _parse_search_results(data) == []

    def test_empty_response(self) -> None:
        assert _parse_search_results({}) == []
        assert _parse_search_results({"stellenangebote": []}) == []


class TestStubToListing:
    def test_basic_merge(self) -> None:
        stub = _JobStub(
            hash_id="abc",
            title="Dev",
            company_name="Co",
            location="Berlin",
            posted_at="2026-02-25",
            refnr="REF",
        )
        details = _make_detail_response(
            stellenbeschreibung="Desc",
            titel="Developer (m/w/d)",
            arbeitgeber="Co",
            allianz_url="https://company.de/apply",
        )
        listing = _stub_to_listing(stub, details)

        assert listing.title == "Developer (m/w/d)"
        assert listing.company_name == "Co"  # prefers detail value
        assert listing.description == "Desc"
        assert listing.source == "bundesagentur"
        assert listing.link == _build_ba_link("abc")
        assert len(listing.apply_options) == 2
        assert listing.apply_options[0].source == "Arbeitsagentur"
        assert listing.apply_options[1].source == "Company Website"
        assert listing.apply_options[1].url == "https://company.de/apply"

    def test_no_external_url(self) -> None:
        stub = _JobStub("h1", "T", "C", "Loc", "2026-01-01", "R")
        listing = _stub_to_listing(stub, _make_detail_response())
        assert len(listing.apply_options) == 1

    def test_empty_details_fallback(self) -> None:
        stub = _JobStub("h1", "Title", "Company", "Loc", "2026-01-01", "R")
        listing = _stub_to_listing(stub, {})
        assert listing.title == "Title"
        assert listing.company_name == "Company"
        assert listing.description == ""


# ===========================================================================
# Integration-style tests for BundesagenturProvider
# ===========================================================================


class TestBundesagenturProviderSearch:
    """Test the full search → enrich pipeline with mocked internals."""

    def test_search_returns_listings(self) -> None:
        stubs = [
            _JobStub("h1", "Dev A", "Co A", "Berlin", "2026-02-25", "REF1"),
            _JobStub("h2", "Dev B", "Co B", "München", "2026-02-24", "REF2"),
        ]
        detail = _make_detail_response(stellenbeschreibung="Full desc")

        provider = BundesagenturProvider(days_published=7)
        with (
            patch.object(provider, "_search_stubs", return_value=stubs),
            patch("immermatch.bundesagentur._fetch_job_details", return_value=detail),
        ):
            jobs = provider.search("Python", "Berlin", max_results=10)

        assert len(jobs) == 2
        assert all(j.source == "bundesagentur" for j in jobs)
        assert all(j.description == "Full desc" for j in jobs)

    def test_search_empty_results(self) -> None:
        provider = BundesagenturProvider()
        with patch.object(provider, "_search_stubs", return_value=[]):
            jobs = provider.search("Niche Job", "Berlin")
        assert jobs == []

    def test_search_respects_max_results(self) -> None:
        """max_results is enforced via _search_stubs truncation."""
        stubs = [_JobStub(f"h{i}", "Dev", "Co", "Berlin", "2026-01-01", f"R{i}") for i in range(3)]
        detail = _make_detail_response()

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_search_stubs", return_value=stubs) as mock_stubs,
            patch("immermatch.bundesagentur._fetch_job_details", return_value=detail),
        ):
            jobs = provider.search("Dev", "Berlin", max_results=3)
            mock_stubs.assert_called_once_with("Dev", "Berlin", 3)

        assert len(jobs) == 3

    def test_veroeffentlichtseit_default(self) -> None:
        provider = BundesagenturProvider()
        assert provider._days_published == 7

    def test_veroeffentlichtseit_custom(self) -> None:
        provider = BundesagenturProvider(days_published=3)
        assert provider._days_published == 3


class TestBundesagenturProviderPagination:
    """Test the search-stub pagination logic with mocked HTTP."""

    def test_single_page(self) -> None:
        resp_data = _make_search_response(
            [_make_stellenangebot(hash_id=f"h{i}") for i in range(5)],
            total=5,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = resp_data

        provider = BundesagenturProvider()
        with patch.object(provider, "_get_with_retry", return_value=mock_resp):
            with patch("immermatch.bundesagentur.httpx.Client"):
                stubs = provider._search_stubs("Dev", "Berlin", max_results=50)

        assert len(stubs) == 5

    def test_multi_page(self) -> None:
        page_0 = _make_search_response(
            [_make_stellenangebot(hash_id=f"p0_{i}") for i in range(50)],
            total=60,
        )
        page_1 = _make_search_response(
            [_make_stellenangebot(hash_id=f"p1_{i}") for i in range(10)],
            total=60,
        )
        call_count = 0

        def mock_get(client, url, params):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = page_1 if params.get("page", 0) >= 1 else page_0
            return mock_resp

        provider = BundesagenturProvider()
        with patch.object(provider, "_get_with_retry", side_effect=mock_get):
            with patch("immermatch.bundesagentur.httpx.Client"):
                stubs = provider._search_stubs("Dev", "Berlin", max_results=100)

        assert len(stubs) == 60
        assert call_count == 2


class TestBundesagenturProviderErrors:
    """Test error handling in the provider."""

    def test_search_server_error_returns_empty(self) -> None:
        """A persistent failure from the search endpoint returns an empty list."""
        provider = BundesagenturProvider()
        with patch.object(provider, "_get_with_retry", return_value=None):
            with patch("immermatch.bundesagentur.httpx.Client"):
                stubs = provider._search_stubs("Dev", "Berlin", max_results=50)
        assert stubs == []

    def test_detail_failure_still_returns_listing(self) -> None:
        """If detail-fetching fails, listing still appears with empty description."""
        stubs = [_JobStub("h1", "Python Dev", "Co", "Berlin", "2026-02-25", "REF")]

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_search_stubs", return_value=stubs),
            patch("immermatch.bundesagentur._fetch_job_details", return_value={}),
        ):
            jobs = provider.search("Dev", "Berlin")

        assert len(jobs) == 1
        assert jobs[0].description == ""
        assert jobs[0].title == "Python Dev"  # falls back to stub title


class TestSearchProviderProtocol:
    """Verify BundesagenturProvider satisfies the SearchProvider protocol."""

    def test_conforms_to_protocol(self) -> None:
        from immermatch.search_provider import SearchProvider

        provider = BundesagenturProvider()
        assert isinstance(provider, SearchProvider)

    def test_has_name(self) -> None:
        provider = BundesagenturProvider()
        assert provider.name == "Bundesagentur für Arbeit"
