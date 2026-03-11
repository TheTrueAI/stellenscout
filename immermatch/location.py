"""Canonical location aliases for consistent caching and multi-variant search.

Provides two main functions:

- ``normalize_location()`` — maps any known alias to the canonical (local) form,
  ensuring that e.g. "Munich" and "München" produce the same cache key.
- ``location_search_variants()`` — returns all known forms for a location so
  providers can search each variant and merge results.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import product

# ---------------------------------------------------------------------------
# City aliases — lowercase key → canonical (local) form
# ---------------------------------------------------------------------------

_CITY_ALIASES: dict[str, str] = {
    "munich": "München",
    "münchen": "München",
    "cologne": "Köln",
    "köln": "Köln",
    "nuremberg": "Nürnberg",
    "nürnberg": "Nürnberg",
    "hanover": "Hannover",
    "hannover": "Hannover",
    "dusseldorf": "Düsseldorf",
    "düsseldorf": "Düsseldorf",
    "vienna": "Wien",
    "wien": "Wien",
    "zurich": "Zürich",
    "zürich": "Zürich",
    "geneva": "Genève",
    "genève": "Genève",
    "prague": "Praha",
    "praha": "Praha",
    "warsaw": "Warszawa",
    "warszawa": "Warszawa",
    "krakow": "Kraków",
    "kraków": "Kraków",
    "wroclaw": "Wrocław",
    "wrocław": "Wrocław",
    "copenhagen": "København",
    "københavn": "København",
    "athens": "Athína",
    "athína": "Athína",
    "bucharest": "București",
    "bucurești": "București",
    "milan": "Milano",
    "milano": "Milano",
    "rome": "Roma",
    "roma": "Roma",
    "lisbon": "Lisboa",
    "lisboa": "Lisboa",
    "brussels": "Bruxelles",
    "bruxelles": "Bruxelles",
    "antwerp": "Antwerpen",
    "antwerpen": "Antwerpen",
    "gothenburg": "Göteborg",
    "göteborg": "Göteborg",
}

# ---------------------------------------------------------------------------
# Country aliases — lowercase key → canonical (local) form
# ---------------------------------------------------------------------------

_COUNTRY_ALIASES: dict[str, str] = {
    "germany": "Deutschland",
    "deutschland": "Deutschland",
    "austria": "Österreich",
    "österreich": "Österreich",
    "switzerland": "Schweiz",
    "schweiz": "Schweiz",
    "netherlands": "Niederlande",
    "niederlande": "Niederlande",
    "czech republic": "Česká republika",
    "česká republika": "Česká republika",
    "czechia": "Česko",
    "česko": "Česko",
    "poland": "Polska",
    "polska": "Polska",
    "sweden": "Sverige",
    "sverige": "Sverige",
    "norway": "Norge",
    "norge": "Norge",
    "denmark": "Danmark",
    "danmark": "Danmark",
    "finland": "Suomi",
    "suomi": "Suomi",
    "hungary": "Magyarország",
    "magyarország": "Magyarország",
    "romania": "România",
    "românia": "România",
    "greece": "Ελλάδα",
    "ελλάδα": "Ελλάδα",
}

# ---------------------------------------------------------------------------
# Reverse mappings: canonical → set of all known surface forms
# ---------------------------------------------------------------------------


def _build_groups(aliases: dict[str, str]) -> dict[str, set[str]]:
    """Build canonical → {all surface forms} mapping from an alias dict.

    Example: {"munich": "München", "münchen": "München"} →
             {"München": {"München", "Munich"}}
    """
    groups: dict[str, set[str]] = defaultdict(set)
    for key, canonical in aliases.items():
        groups[canonical].add(key)
    result: dict[str, set[str]] = {}
    for canonical, keys in groups.items():
        forms: set[str] = set()
        for k in keys:
            if k == canonical.lower():
                forms.add(canonical)
            else:
                forms.add(k.title())
        result[canonical] = forms
    return result


_CITY_GROUPS: dict[str, set[str]] = _build_groups(_CITY_ALIASES)
_COUNTRY_GROUPS: dict[str, set[str]] = _build_groups(_COUNTRY_ALIASES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_location(location: str) -> str:
    """Replace alias tokens with canonical (local) form.

    Examples::

        >>> normalize_location("Munich, Germany")
        'München, Deutschland'
        >>> normalize_location("München")
        'München'
        >>> normalize_location("Berlin")
        'Berlin'
    """
    if not location or not location.strip():
        return location

    parts = [p.strip() for p in location.split(",")]
    normalized: list[str] = []
    for part in parts:
        if not part:
            continue
        # Try country aliases first (may be multi-word like "Czech Republic")
        lower = part.lower()
        if lower in _COUNTRY_ALIASES:
            normalized.append(_COUNTRY_ALIASES[lower])
        elif lower in _CITY_ALIASES:
            normalized.append(_CITY_ALIASES[lower])
        else:
            normalized.append(part)
    return ", ".join(normalized)


def location_search_variants(location: str) -> list[str]:
    """Return all location forms to search with.

    The canonical (normalized) form is always first.  For composite
    locations like "Munich, Germany", each part is expanded independently
    and the results are combined via cartesian product.

    Examples::

        >>> location_search_variants("Munich")
        ['München', 'Munich']
        >>> location_search_variants("München")
        ['München', 'Munich']
        >>> location_search_variants("Berlin")
        ['Berlin']
    """
    if not location or not location.strip():
        return [location]

    canonical = normalize_location(location)

    # Collect variant sets for each comma-separated part
    parts = [p.strip() for p in location.split(",")]
    part_variants: list[list[str]] = []

    for part in parts:
        if not part:
            continue
        lower = part.lower()
        if lower in _CITY_ALIASES:
            canon = _CITY_ALIASES[lower]
            forms = _CITY_GROUPS.get(canon, {canon})
            part_variants.append(sorted(forms))
        elif lower in _COUNTRY_ALIASES:
            canon = _COUNTRY_ALIASES[lower]
            forms = _COUNTRY_GROUPS.get(canon, {canon})
            part_variants.append(sorted(forms))
        else:
            part_variants.append([part])

    results = [", ".join(combo) for combo in product(*part_variants)]

    # Ensure canonical is first, deduplicate, preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for item in [canonical, *results]:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
