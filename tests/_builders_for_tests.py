"""Real builder functions for tests — live in a proper module so
``inspect.getsource`` can read them."""


def wine_builder(info):
    name = info.get("wine", "Unknown")
    producer = info.get("producer", "Unknown")
    return f"Wine: {name}\nProducer: {producer}"


def vintage_context_builder(info, cached_body=""):
    name = info.get("wine", "Unknown")
    vintage = info.get("vintage", "")
    return f"Wine: {name}\nVintage: {vintage}\n\nExisting: {cached_body}"


def full_wine_builder(wine_info, include_vintage_context=False):
    """Wine-prompt builder with 9 dict-get fields and a conditional line."""
    name = wine_info.get("wine", "Unknown")
    vintage = wine_info.get("vintage", "")
    producer = wine_info.get("producer", "Unknown")
    varietal = wine_info.get("varietal", "")
    color = wine_info.get("color", "")
    region = wine_info.get("region", "")
    subregion = wine_info.get("subregion", "")
    country = wine_info.get("country", "")
    appellation = wine_info.get("appellation", "")
    has_vintage = include_vintage_context and vintage
    vintage_line = f"\nVintage: {vintage}" if has_vintage else ""

    return f"""Write a portrait for this wine.

Wine: {name}{vintage_line}
Producer: {producer}
Varietal: {varietal}
Color: {color}
Region: {region}
Sub-region: {subregion}
Appellation: {appellation}
Country: {country}"""
