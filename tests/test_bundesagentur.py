"""Tests for the Bundesagentur für Arbeit search provider."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from immermatch.bundesagentur import (
    BundesagenturProvider,
    _build_ba_link,
    _clean_html,
    _fetch_detail,
    _fetch_detail_api,
    _parse_listing,
    _parse_location,
    _parse_search_results,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stellenangebot(
    refnr: str = "10000-1234567890-S",
    titel: str = "Python Entwickler (m/w/d)",
    beruf: str = "Python Entwickler",
    arbeitgeber: str = "ACME GmbH",
    ort: str = "Berlin",
    region: str = "Berlin",
    land: str = "Deutschland",
    posted: str = "2026-02-25",
) -> dict:
    return {
        "beruf": beruf,
        "titel": titel,
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
        "page": "1",
        "size": "50",
    }


def _make_ng_state_html(jobdetail: dict) -> str:
    """Wrap a jobdetail dict in the Angular SSR ng-state script tag."""
    state = {"jobdetail": jobdetail}
    return f'<html><body><script id="ng-state" type="application/json">{json.dumps(state)}</script></body></html>'


def _make_detail(
    description: str = "<b>Great job</b> &amp; benefits",
    partner_url: str = "",
    partner_name: str = "",
) -> dict:
    d: dict = {"stellenangebotsBeschreibung": description}
    if partner_url:
        d["allianzpartnerUrl"] = partner_url
    if partner_name:
        d["allianzpartnerName"] = partner_name
    return d


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestBuildBaLink:
    def test_simple(self) -> None:
        assert _build_ba_link("10000-123-S") == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-123-S"


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


class TestCleanHtml:
    def test_strips_tags(self) -> None:
        assert _clean_html("<b>bold</b> text") == "bold text"

    def test_decodes_entities(self) -> None:
        # &amp; → &  (plain entities are decoded)
        assert _clean_html("AT&amp;T rocks") == "AT&T rocks"

    def test_collapses_whitespace(self) -> None:
        assert _clean_html("a   b\n\nc") == "a b c"

    def test_combined(self) -> None:
        assert _clean_html("<p>Hello &amp; world</p>  <br/>  ok") == "Hello & world ok"

    def test_empty_string(self) -> None:
        assert _clean_html("") == ""


class TestParseListing:
    def test_valid_item(self) -> None:
        item = _make_stellenangebot(refnr="REF1", titel="Dev (m/w/d)", beruf="Entwickler", arbeitgeber="Co")
        listing = _parse_listing(item)
        assert listing is not None
        assert listing.title == "Dev (m/w/d)"
        assert listing.company_name == "Co"
        assert listing.source == "bundesagentur"
        assert "REF1" in listing.link
        assert len(listing.apply_options) == 1
        assert listing.apply_options[0].source == "Arbeitsagentur"

    def test_description_includes_beruf_when_different_from_title(self) -> None:
        item = _make_stellenangebot(titel="Senior Dev", beruf="Softwareentwickler")
        listing = _parse_listing(item)
        assert listing is not None
        assert "Beruf: Softwareentwickler" in listing.description

    def test_description_omits_beruf_when_equal_to_title(self) -> None:
        item = _make_stellenangebot(titel="Python Dev", beruf="Python Dev")
        listing = _parse_listing(item)
        assert listing is not None
        assert "Beruf:" not in listing.description

    def test_missing_refnr_returns_none(self) -> None:
        item = {"beruf": "Dev", "arbeitgeber": "Co", "arbeitsort": {}}
        assert _parse_listing(item) is None

    def test_fallback_title_from_beruf(self) -> None:
        item = _make_stellenangebot(titel="", beruf="QA Engineer")
        listing = _parse_listing(item)
        assert listing is not None
        assert listing.title == "QA Engineer"

    def test_with_detail_description(self) -> None:
        item = _make_stellenangebot(refnr="REF1")
        detail = _make_detail(description="<p>Full desc</p> &amp; more")
        listing = _parse_listing(item, detail=detail)
        assert listing is not None
        assert listing.description == "Full desc & more"

    def test_with_detail_empty_description_falls_back(self) -> None:
        item = _make_stellenangebot(refnr="REF1", beruf="QA", arbeitgeber="Corp")
        detail = {"stellenangebotsBeschreibung": ""}
        listing = _parse_listing(item, detail=detail)
        assert listing is not None
        # Falls back to search-field description
        assert "Arbeitgeber: Corp" in listing.description

    def test_with_detail_external_apply_url(self) -> None:
        item = _make_stellenangebot(refnr="REF1")
        detail = _make_detail(partner_url="https://careers.acme.com/apply", partner_name="ACME Careers")
        listing = _parse_listing(item, detail=detail)
        assert listing is not None
        assert len(listing.apply_options) == 2
        assert listing.apply_options[1].source == "ACME Careers"
        assert listing.apply_options[1].url == "https://careers.acme.com/apply"

    def test_with_detail_external_url_adds_https_prefix(self) -> None:
        item = _make_stellenangebot(refnr="REF1")
        detail = _make_detail(partner_url="careers.acme.com")
        listing = _parse_listing(item, detail=detail)
        assert listing is not None
        assert listing.apply_options[1].url == "https://careers.acme.com"

    def test_with_detail_external_url_default_name(self) -> None:
        item = _make_stellenangebot(refnr="REF1")
        detail = _make_detail(partner_url="https://example.com")
        listing = _parse_listing(item, detail=detail)
        assert listing is not None
        assert listing.apply_options[1].source == "Company Website"

    def test_with_no_detail(self) -> None:
        item = _make_stellenangebot(refnr="REF1")
        listing = _parse_listing(item, detail=None)
        assert listing is not None
        assert len(listing.apply_options) == 1  # Only Arbeitsagentur


class TestParseSearchResults:
    def test_valid_items(self) -> None:
        data = _make_search_response(
            [
                _make_stellenangebot(refnr="r1", beruf="Dev", arbeitgeber="Co"),
                _make_stellenangebot(refnr="r2", beruf="QA", arbeitgeber="Co2"),
            ]
        )
        results = _parse_search_results(data)
        assert len(results) == 2
        # Returns raw dicts, not JobListing objects
        assert results[0]["arbeitgeber"] == "Co"
        assert results[1]["arbeitgeber"] == "Co2"

    def test_skips_missing_refnr(self) -> None:
        data = {"stellenangebote": [{"beruf": "Dev"}]}
        assert _parse_search_results(data) == []

    def test_empty_response(self) -> None:
        assert _parse_search_results({}) == []
        assert _parse_search_results({"stellenangebote": []}) == []


# ===========================================================================
# Tests for _fetch_detail
# ===========================================================================


class TestFetchDetail:
    def test_extracts_ng_state(self) -> None:
        detail = {"stellenangebotsBeschreibung": "<p>Hello</p>", "firma": "ACME"}
        html = _make_ng_state_html(detail)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        result = _fetch_detail(client, "REF-123")
        assert result == detail

    def test_missing_ng_state_returns_empty(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>No state here</body></html>"
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        assert _fetch_detail(client, "REF-123") == {}

    def test_non_200_returns_empty(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        assert _fetch_detail(client, "REF-123") == {}

    def test_retries_on_server_error(self) -> None:
        error_resp = MagicMock()
        error_resp.status_code = 503

        detail = {"stellenangebotsBeschreibung": "ok"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = _make_ng_state_html(detail)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = [error_resp, ok_resp]

        with patch("immermatch.bundesagentur.time.sleep"):
            result = _fetch_detail(client, "REF-123")
        assert result == detail

    def test_retries_on_403_then_succeeds(self) -> None:
        blocked_resp = MagicMock()
        blocked_resp.status_code = 403

        detail = {"stellenangebotsBeschreibung": "ok"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = _make_ng_state_html(detail)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = [blocked_resp, ok_resp]

        with patch("immermatch.bundesagentur.time.sleep"):
            result = _fetch_detail(client, "REF-123")
        assert result == detail

    def test_retries_on_network_error(self) -> None:
        detail = {"stellenangebotsBeschreibung": "recovered"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = _make_ng_state_html(detail)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = [httpx.ConnectError("timeout"), ok_resp]

        with patch("immermatch.bundesagentur.time.sleep"):
            result = _fetch_detail(client, "REF-123")
        assert result == detail

    def test_all_retries_fail(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("down")

        with patch("immermatch.bundesagentur.time.sleep"):
            result = _fetch_detail(client, "REF-123")
        assert result == {}


# ===========================================================================
# Integration-style tests for BundesagenturProvider
# ===========================================================================


class TestBundesagenturProviderSearch:
    """Test the full search pipeline with mocked HTTP."""

    def test_search_returns_listings(self) -> None:
        items = [
            _make_stellenangebot(refnr="r1", titel="Dev A", arbeitgeber="Co A"),
            _make_stellenangebot(refnr="r2", titel="Dev B", arbeitgeber="Co B"),
        ]
        resp_data = _make_search_response(items, total=2)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = resp_data

        provider = BundesagenturProvider(days_published=7)
        with (
            patch.object(provider, "_get_with_retry", return_value=mock_resp),
            patch.object(provider, "_enrich", side_effect=lambda it: [_parse_listing(i) for i in it]),
        ):
            jobs = provider.search("Python", "Berlin", max_results=10)

        assert len(jobs) == 2
        assert all(j.source == "bundesagentur" for j in jobs)
        assert jobs[0].title == "Dev A"
        assert jobs[1].title == "Dev B"

    def test_search_empty_results(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_search_response([], total=0)

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_get_with_retry", return_value=mock_resp),
            patch.object(provider, "_enrich", side_effect=lambda it: [_parse_listing(i) for i in it]),
        ):
            jobs = provider.search("Niche Job", "Berlin")
        assert jobs == []

    def test_search_empty_query_returns_empty(self) -> None:
        """Empty or whitespace-only queries are rejected before hitting the API."""
        provider = BundesagenturProvider()
        assert provider.search("", "Berlin") == []
        assert provider.search("   ", "Berlin") == []

    def test_search_respects_max_results(self) -> None:
        resp_data = _make_search_response(
            [_make_stellenangebot(refnr=f"r{i}") for i in range(5)],
            total=5,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = resp_data

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_get_with_retry", return_value=mock_resp),
            patch.object(provider, "_enrich", side_effect=lambda it: [_parse_listing(i) for i in it]),
        ):
            jobs = provider.search("Dev", "Berlin", max_results=3)

        assert len(jobs) == 3

    def test_veroeffentlichtseit_custom(self) -> None:
        provider = BundesagenturProvider(days_published=3)
        assert provider._days_published == 3


class TestBundesagenturProviderPagination:
    """Test pagination logic via _search_items."""

    def test_single_page(self) -> None:
        resp_data = _make_search_response(
            [_make_stellenangebot(refnr=f"r{i}") for i in range(5)],
            total=5,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = resp_data

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_get_with_retry", return_value=mock_resp),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            items = provider._search_items("Dev", "Berlin", max_results=50)

        assert len(items) == 5

    def test_multi_page(self) -> None:
        page_1 = _make_search_response(
            [_make_stellenangebot(refnr=f"p1_{i}") for i in range(50)],
            total=60,
        )
        page_2 = _make_search_response(
            [_make_stellenangebot(refnr=f"p2_{i}") for i in range(10)],
            total=60,
        )
        call_count = 0

        def mock_get(client, url, params):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = page_2 if params.get("page", 1) >= 2 else page_1
            return mock_resp

        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_get_with_retry", side_effect=mock_get),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            items = provider._search_items("Dev", "Berlin", max_results=100)

        assert len(items) == 60
        assert call_count == 2


class TestBundesagenturProviderErrors:
    """Test error handling in the provider."""

    def test_search_items_server_error_returns_empty(self) -> None:
        """A persistent failure from the search endpoint returns an empty list."""
        provider = BundesagenturProvider()
        with (
            patch.object(provider, "_get_with_retry", return_value=None),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            items = provider._search_items("Dev", "Berlin", max_results=50)
        assert items == []

    def test_get_with_retry_retries_on_403(self) -> None:
        blocked_resp = MagicMock()
        blocked_resp.status_code = 403

        ok_resp = MagicMock()
        ok_resp.status_code = 200

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = [blocked_resp, ok_resp]

        with patch("immermatch.bundesagentur.time.sleep"):
            result = BundesagenturProvider._get_with_retry(client, "https://example.com", {})

        assert result is ok_resp


class TestFetchDetailApi:
    def test_fetches_json_detail(self) -> None:
        detail = {"stellenangebotsBeschreibung": "API detail"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = detail

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = ok_resp

        assert _fetch_detail_api(client, "REF-123") == detail

    def test_retries_on_403_then_succeeds(self) -> None:
        blocked_resp = MagicMock()
        blocked_resp.status_code = 403

        detail = {"stellenangebotsBeschreibung": "API detail"}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = detail

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = [blocked_resp, ok_resp]

        with patch("immermatch.bundesagentur.time.sleep"):
            result = _fetch_detail_api(client, "REF-123")

        assert result == detail


class TestEnrich:
    """Test the _enrich detail-fetching pipeline."""

    def test_enriches_items_with_details(self) -> None:
        items = [
            _make_stellenangebot(refnr="r1", titel="Dev A"),
            _make_stellenangebot(refnr="r2", titel="Dev B"),
        ]
        details = {
            "r1": _make_detail(description="<b>Desc A</b>"),
            "r2": _make_detail(description="<p>Desc B</p>"),
        }

        provider = BundesagenturProvider()
        with (
            patch("immermatch.bundesagentur._fetch_detail_api", return_value={}),
            patch("immermatch.bundesagentur._fetch_detail", side_effect=lambda _c, refnr: details.get(refnr, {})),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings) == 2
        assert listings[0].description == "Desc A"
        assert listings[1].description == "Desc B"

    def test_enrich_falls_back_on_failed_detail(self) -> None:
        items = [_make_stellenangebot(refnr="r1", titel="Dev", arbeitgeber="Corp")]

        provider = BundesagenturProvider()
        with (
            patch("immermatch.bundesagentur._fetch_detail_api", return_value={}),
            patch("immermatch.bundesagentur._fetch_detail", return_value={}),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings) == 1
        # Uses fallback description from search fields
        assert "Arbeitgeber: Corp" in listings[0].description

    def test_enrich_with_external_apply_url(self) -> None:
        items = [_make_stellenangebot(refnr="r1")]
        detail = _make_detail(partner_url="https://jobs.example.com", partner_name="Example")

        provider = BundesagenturProvider()
        with (
            patch("immermatch.bundesagentur._fetch_detail_api", return_value={}),
            patch("immermatch.bundesagentur._fetch_detail", return_value=detail),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings[0].apply_options) == 2
        assert listings[0].apply_options[1].source == "Example"
        assert listings[0].apply_options[1].url == "https://jobs.example.com"

    def test_api_then_html_strategy_falls_back_to_html(self) -> None:
        items = [_make_stellenangebot(refnr="r1", titel="Dev", arbeitgeber="Corp")]
        html_detail = _make_detail(description="<b>HTML fallback</b>")

        provider = BundesagenturProvider(detail_strategy="api_then_html")
        with (
            patch("immermatch.bundesagentur._fetch_detail_api", return_value={}),
            patch("immermatch.bundesagentur._fetch_detail", return_value=html_detail),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings) == 1
        assert listings[0].description == "HTML fallback"

    def test_api_only_strategy_uses_api_detail(self) -> None:
        items = [_make_stellenangebot(refnr="r1", titel="Dev", arbeitgeber="Corp")]
        api_detail = {"stellenangebotsBeschreibung": "API detail"}

        provider = BundesagenturProvider(detail_strategy="api_only")
        with (
            patch("immermatch.bundesagentur._fetch_detail_api", return_value=api_detail),
            patch("immermatch.bundesagentur._fetch_detail", return_value={}),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings) == 1
        assert listings[0].description == "API detail"

    def test_html_only_strategy_uses_html_detail(self) -> None:
        items = [_make_stellenangebot(refnr="r1", titel="Dev", arbeitgeber="Corp")]
        html_detail = _make_detail(description="<b>HTML only detail</b>")

        provider = BundesagenturProvider(detail_strategy="html_only")
        with (
            patch("immermatch.bundesagentur._fetch_detail", return_value=html_detail),
            patch("immermatch.bundesagentur._fetch_detail_api"),
            patch("immermatch.bundesagentur.httpx.Client"),
        ):
            listings = provider._enrich(items)

        assert len(listings) == 1
        assert listings[0].description == "HTML only detail"


class TestSearchProviderProtocol:
    """Verify BundesagenturProvider satisfies the SearchProvider protocol."""

    def test_conforms_to_protocol(self) -> None:
        from immermatch.search_provider import SearchProvider

        provider = BundesagenturProvider()
        assert isinstance(provider, SearchProvider)

    def test_has_name(self) -> None:
        provider = BundesagenturProvider()
        assert provider.name == "Bundesagentur für Arbeit"
