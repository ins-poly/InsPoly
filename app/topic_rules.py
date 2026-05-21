from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicMatch:
    matched: bool
    labels: tuple[str, ...]


TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Politics": (
        "election",
        "congress",
        "senate",
        "house",
        "cabinet",
        "president",
        "white house",
        "administration",
        "supreme court",
        "trump",
        "biden",
        "democrat",
        "republican",
        "governor",
    ),
    "Ukraine": (
        "ukraine",
        "kyiv",
        "kiev",
        "zelensky",
    ),
    "Russia": (
        "russia",
        "putin",
        "kremlin",
    ),
    "Iran": (
        "iran",
        "tehran",
    ),
    "Israel": (
        "israel",
        "gaza",
        "hamas",
        "hezbollah",
        "netanyahu",
    ),
    "War/Ceasefire": (
        "ceasefire",
        "strike",
        "airstrike",
        "drone",
        "troop",
        "frontline",
        "sanction",
        "missile",
        "war",
        "military",
    ),
    "Sanctions/NATO/EU": (
        "sanction",
        "nato",
        "eu",
        "european union",
    ),
    "China/Taiwan": (
        "china",
        "taiwan",
        "xi",
        "beijing",
    ),
    "Diplomacy/Intel": (
        "diplomatic",
        "foreign policy",
        "intelligence",
    ),
}


DEFAULT_TOPIC_SELECTION: tuple[str, ...] = tuple(TOPIC_KEYWORDS)


def available_topics() -> tuple[str, ...]:
    return DEFAULT_TOPIC_SELECTION


def match_focus_topic(text: str, selected_topics: tuple[str, ...] | None = None) -> TopicMatch:
    haystack = text.lower()
    enabled = selected_topics or DEFAULT_TOPIC_SELECTION
    labels: list[str] = []
    for label in enabled:
        keywords = TOPIC_KEYWORDS[label]
        if any(keyword in haystack for keyword in keywords):
            labels.append(label)
    return TopicMatch(matched=bool(labels), labels=tuple(labels))
