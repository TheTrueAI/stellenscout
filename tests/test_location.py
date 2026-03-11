"""Tests for immermatch.location — canonical aliases and search variants."""

from immermatch.location import location_search_variants, normalize_location


class TestNormalizeLocation:
    def test_english_to_canonical(self) -> None:
        assert normalize_location("Munich") == "München"

    def test_local_identity(self) -> None:
        assert normalize_location("München") == "München"

    def test_alias_pair_equivalence(self) -> None:
        assert normalize_location("Munich") == normalize_location("München")

    def test_composite_city_and_country(self) -> None:
        assert normalize_location("Munich, Germany") == "München, Deutschland"

    def test_passthrough_unknown(self) -> None:
        assert normalize_location("Berlin") == "Berlin"

    def test_country_only(self) -> None:
        assert normalize_location("Germany") == "Deutschland"

    def test_empty_string(self) -> None:
        assert normalize_location("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_location("   ") == "   "

    def test_vienna(self) -> None:
        assert normalize_location("Vienna") == "Wien"
        assert normalize_location("Wien") == "Wien"

    def test_zurich(self) -> None:
        assert normalize_location("Zurich") == "Zürich"

    def test_multi_word_country(self) -> None:
        assert normalize_location("Prague, Czech Republic") == "Praha, Česká republika"


class TestLocationSearchVariants:
    def test_single_alias_city(self) -> None:
        variants = location_search_variants("Munich")
        assert "München" in variants
        assert "Munich" in variants

    def test_canonical_first(self) -> None:
        variants = location_search_variants("Munich")
        assert variants[0] == "München"

    def test_no_alias_single_element(self) -> None:
        assert location_search_variants("Berlin") == ["Berlin"]

    def test_symmetry(self) -> None:
        assert set(location_search_variants("Munich")) == set(location_search_variants("München"))

    def test_composite_variants(self) -> None:
        variants = location_search_variants("Munich, Germany")
        assert variants[0] == "München, Deutschland"
        assert "Munich, Germany" in variants

    def test_empty_string(self) -> None:
        assert location_search_variants("") == [""]

    def test_cache_key_equivalence(self) -> None:
        """Normalized forms match for all alias pairs — ensures cache consistency."""
        pairs = [
            ("Munich", "München"),
            ("Vienna", "Wien"),
            ("Cologne", "Köln"),
            ("Germany", "Deutschland"),
        ]
        for a, b in pairs:
            assert normalize_location(a) == normalize_location(b), f"{a} vs {b}"

    def test_vienna_variants(self) -> None:
        variants = location_search_variants("Vienna")
        assert "Wien" in variants
        assert "Vienna" in variants
        assert variants[0] == "Wien"

    def test_multi_word_country_variants(self) -> None:
        """Ensure multi-word aliases like 'Czech Republic' appear with proper casing."""
        variants = location_search_variants("Prague, Czech Republic")
        assert "Praha, Česká republika" in variants
        assert any("Czech Republic" in v for v in variants)
