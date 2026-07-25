from __future__ import annotations

import re
from dataclasses import dataclass

from .numbers import ENGLISH_DIGITS, normalize_number_groups

NATO = {
    "alpha": "A",
    "bravo": "B",
    "charlie": "C",
    "delta": "D",
    "echo": "E",
    "foxtrot": "F",
    "golf": "G",
    "hotel": "H",
    "india": "I",
    "juliett": "J",
    "kilo": "K",
    "lima": "L",
    "mike": "M",
    "november": "N",
    "oscar": "O",
    "papa": "P",
    "quebec": "Q",
    "romeo": "R",
    "sierra": "S",
    "tango": "T",
    "uniform": "U",
    "victor": "V",
    "whiskey": "W",
    "x-ray": "X",
    "yankee": "Y",
    "zulu": "Z",
}


@dataclass(frozen=True)
class EntityCandidate:
    entity_type: str
    raw_value: str
    normalized_value: str
    confidence: float
    source: str = "RULE"


def extract_entities(text: str) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    for group in normalize_number_groups(text):
        candidates.append(EntityCandidate("NUMBER_GROUP", group, group, 0.88))
    lower = text.casefold()
    words = re.findall(r"[a-z]+(?:-[a-z]+)?", lower)
    for index in range(len(words)):
        run: list[str] = []
        cursor = index
        while cursor < len(words) and (words[cursor] in NATO or words[cursor] in ENGLISH_DIGITS):
            run.append(words[cursor])
            cursor += 1
        if len(run) >= 2 and any(token in NATO for token in run):
            normalized = "".join(
                NATO[token] if token in NATO else ENGLISH_DIGITS[token] for token in run
            )
            raw = " ".join(run)
            candidates.append(EntityCandidate("PHONETIC_TOKEN", raw, normalized, 0.9))
            if 2 <= len(normalized) <= 8:
                candidates.append(EntityCandidate("CALLSIGN", raw, normalized, 0.72))
    for match in re.finditer(r"\b[A-Z]{1,5}\d[A-Z0-9]{0,5}\b", text):
        candidates.append(EntityCandidate("CALLSIGN", match.group(), match.group().upper(), 0.86))
    if re.search(r"\b(message|attention|nachricht|сообщение)\b", lower):
        candidates.append(EntityCandidate("MESSAGE_HEADER", text[:120], "MESSAGE_HEADER", 0.7))
    if re.search(r"\b(end|out|конец|конец связи)\b", lower):
        candidates.append(EntityCandidate("MESSAGE_FOOTER", text[-120:], "MESSAGE_FOOTER", 0.7))
    unique: dict[tuple[str, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.entity_type, candidate.normalized_value)
        if key not in unique or unique[key].confidence < candidate.confidence:
            unique[key] = candidate
    return list(unique.values())
