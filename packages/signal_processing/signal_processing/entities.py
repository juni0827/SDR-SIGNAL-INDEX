from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .numbers import DIGITS, normalize_number_groups

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
RUSSIAN_PHONETIC = {
    "анна": "А",
    "борис": "Б",
    "василий": "В",
    "григорий": "Г",
    "дмитрий": "Д",
    "елена": "Е",
    "иван": "И",
    "константин": "К",
    "леонид": "Л",
    "михаил": "М",
    "николай": "Н",
    "ольга": "О",
    "павел": "П",
    "роман": "Р",
    "сергей": "С",
    "татьяна": "Т",
    "фёдор": "Ф",
    "харитон": "Х",
    "юрий": "Ю",
    "яков": "Я",
}
PHONETIC = {**NATO, **RUSSIAN_PHONETIC}


@dataclass(frozen=True)
class EntityCandidate:
    entity_type: str
    raw_value: str
    normalized_value: str
    confidence: float
    source: str = "RULE"


def extract_entities(text: str) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    all_groups = normalize_number_groups(text, deduplicate_adjacent=False)
    for group in dict.fromkeys(all_groups):
        candidates.append(EntityCandidate("NUMBER_GROUP", group, group, 0.88))
    for group, count in Counter(all_groups).items():
        if count > 1:
            candidates.append(
                EntityCandidate(
                    "REPEATED_PHRASE",
                    group,
                    group,
                    min(0.95, 0.65 + count * 0.08),
                )
            )
    lengths = [len(group) for group in all_groups]
    if len(lengths) >= 3 and len(set(lengths)) == 1:
        candidates.append(
            EntityCandidate(
                "CUSTOM",
                " ".join(all_groups),
                f"CONSTANT_NUMBER_GROUP_LENGTH:{lengths[0]}",
                0.82,
            )
        )
    lower = text.casefold()
    words = re.findall(r"[a-zа-яё]+(?:-[a-zа-яё]+)?", lower)
    for index in range(len(words)):
        run: list[str] = []
        cursor = index
        while cursor < len(words) and (words[cursor] in PHONETIC or words[cursor] in DIGITS):
            run.append(words[cursor])
            cursor += 1
        if len(run) >= 2 and any(token in PHONETIC for token in run):
            normalized = "".join(
                PHONETIC[token] if token in PHONETIC else DIGITS[token] for token in run
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
