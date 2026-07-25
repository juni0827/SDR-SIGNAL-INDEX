from __future__ import annotations

import re

ENGLISH_DIGITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
RUSSIAN_DIGITS = {
    "ноль": "0",
    "нуль": "0",
    "один": "1",
    "одна": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
}
DIGITS = {**ENGLISH_DIGITS, **RUSSIAN_DIGITS}
SEPARATOR = re.compile(r"\s*(?:,|;|/|\b(?:break|group|группа)\b)\s*", re.IGNORECASE)


def normalize_number_groups(text: str) -> list[str]:
    groups: list[str] = []
    for part in SEPARATOR.split(text.casefold()):
        tokens = re.findall(r"[a-zа-яё]+|\d+", part, re.IGNORECASE)
        current = ""
        saw_spoken = False
        saw_explicit = False
        for token in tokens:
            if token in DIGITS:
                if current and saw_explicit:
                    if len(current) >= 2:
                        groups.append(current)
                    current = ""
                    saw_explicit = False
                current += DIGITS[token]
                saw_spoken = True
            elif token.isdigit():
                current += token
                saw_explicit = True
            elif current:
                if len(current) >= 2:
                    groups.append(current)
                current = ""
                saw_explicit = False
        if current and (saw_spoken or len(current) >= 2):
            groups.append(current)
    deduplicated: list[str] = []
    for group in groups:
        if not deduplicated or deduplicated[-1] != group:
            deduplicated.append(group)
    return deduplicated
