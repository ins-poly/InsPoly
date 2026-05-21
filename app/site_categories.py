from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SiteCategory:
    label: str
    slug: str
    tag_id: str


SITE_CATEGORY_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("Sports", "sports"),
    ("Politics", "politics"),
    ("Crypto", "crypto"),
    ("Business", "business"),
    ("World", "world"),
    ("Tech", "tech"),
    ("Culture", "pop-culture"),
    ("Trump", "trump"),
    ("Middle East", "middle-east"),
    ("Ukraine", "ukraine"),
    ("Elections", "elections"),
    ("Science", "science"),
    ("AI", "ai"),
    ("Finance", "finance"),
    ("Esports", "esports"),
    ("Iran", "iran"),
    ("Geopolitics", "geopolitics"),
    ("Weather", "weather"),
    ("Mentions", "mention-markets"),
    ("Gaming", "gaming"),
    ("Entertainment", "entertainment"),
    ("Economy", "economy"),
)


SENSITIVITY_BY_CATEGORY: dict[str, tuple[int, str]] = {
    "Politics": (6, "Political markets have elevated information-asymmetry risk."),
    "World": (6, "World markets often depend on official statements and policy decisions."),
    "Trump": (6, "Trump-related markets can move on narrow political signals."),
    "Middle East": (7, "Middle East markets often react to sudden military or diplomatic developments."),
    "Ukraine": (7, "Ukraine markets are especially sensitive to war and diplomacy signals."),
    "Elections": (6, "Election markets can move sharply on narrow information edges."),
    "Business": (4, "Business markets can depend on event-specific corporate information."),
    "Economy": (4, "Economy markets are sensitive to releases and regulator decisions."),
    "Finance": (4, "Finance markets have moderate event-driven asymmetry risk."),
    "Geopolitics": (6, "Geopolitics markets often depend on official statements and narrow diplomatic signals."),
    "Iran": (7, "Iran markets are especially sensitive to sudden military or diplomatic developments."),
    "Crypto": (2, "Crypto is often noisy and momentum-driven, so baseline suspicion is lower."),
    "Tech": (2, "Tech has moderate sensitivity, but many moves are public."),
    "Technology": (2, "Technology has moderate sensitivity, but many moves are public."),
    "Weather": (2, "Weather markets are often public-data driven, so baseline suspicion is lower."),
    "Mentions": (2, "Mention markets are usually tied to public appearances and live transcripts."),
    "Science": (3, "Science can be niche and thinner than mainstream categories."),
    "AI": (3, "AI markets can be niche and news-sensitive."),
    "Sports": (1, "Sports is usually a lower-priority category for this scanner."),
    "Esports": (1, "Esports is usually a lower-priority category for this scanner."),
    "Culture": (1, "Culture is usually a lower-priority category for this scanner."),
    "Gaming": (1, "Gaming is usually a lower-priority category for this scanner."),
    "Entertainment": (1, "Entertainment is usually a lower-priority category for this scanner."),
}


def category_sensitivity(label: str) -> tuple[int, str]:
    return SENSITIVITY_BY_CATEGORY.get(
        label,
        (2, "This category has moderate sensitivity by default."),
    )
