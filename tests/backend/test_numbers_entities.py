from signal_processing.entities import extract_entities
from signal_processing.numbers import normalize_number_groups


def test_spoken_number_normalization_preserves_groups() -> None:
    text = "two eight one, four six, nine nine two"
    assert normalize_number_groups(text) == ["281", "46", "992"]


def test_russian_number_normalization_is_extensible() -> None:
    assert normalize_number_groups("два восемь один, четыре шесть") == ["281", "46"]


def test_callsign_and_phonetic_extraction() -> None:
    entities = extract_entities("Kilo Seven Two message TEST72 two eight one")
    normalized = {(item.entity_type, item.normalized_value) for item in entities}
    assert ("CALLSIGN", "TEST72") in normalized
    assert any(kind == "PHONETIC_TOKEN" for kind, _ in normalized)
    assert ("NUMBER_GROUP", "281") in normalized
