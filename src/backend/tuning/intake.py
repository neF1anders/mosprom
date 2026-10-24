"""Stage-1 task card v1.1 -> task_card/0 (the internal input of select_parameters)."""

from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.intake.values import ValueParseError, parse_bool, parse_list, parse_number, unit_matches

SUPPORTED_SCHEMA = "1.1"
_PROVENANCE_SOURCE = {
    "user": "user",
    "document": "user",
    "measurement": "model",
    "knowledge": "model",
    "assumption": "assumption",
}


class _Collected(object):
    """Notes gathered while reading the card: assumptions go to the user, warnings to the logs."""

    def __init__(self):
        self.assumptions = []  # type: list
        self.warnings = []  # type: list


def check_readiness(card):
    # type: (dict) -> list
    """Refuse a card stage 1 does not release for parameter selection; return notes for a preliminary one."""
    if card.get("schema_version") != SUPPORTED_SCHEMA:
        raise TuningError(
            "unsupported task card schema_version %r, expected %s" % (card.get("schema_version"), SUPPORTED_SCHEMA)
        )
    blocked = (card.get("blocked_actions") or {}).get("select_parameters") or []
    if card.get("readiness") == "blocked" or blocked:
        reasons = "; ".join(blocked) or "readiness is blocked"
        raise TuningError("stage 1 blocks parameter selection: %s" % reasons)
    if card.get("readiness") == "preliminary":
        return ["карточка предварительная (ревизия %s): результат может измениться" % card.get("revision")]
    if card.get("readiness") != "ready":
        raise TuningError("unknown task card readiness %r" % card.get("readiness"))
    return []


def task_card_from_stage1(card, vocabulary):
    # type: (dict, dict) -> tuple
    """Return (task_card/0, assumptions, warnings)."""
    notes = _Collected()
    notes.assumptions.extend(check_readiness(card))
    task_card = {
        "schema": "task_card/0",
        "status": "ready",
        "inputs": {"text": card.get("purpose") or "", "files": _files(card)},
        "part": {},
        "requirements": [],
        "preferences": {},
        "material": {},
    }
    for requirement, requirement_id in _with_ids(card.get("requirements") or []):
        _read_requirement(requirement, requirement_id, vocabulary, task_card, notes)
    _read_answers(card.get("answers") or {}, vocabulary, task_card)
    _read_free_text(card, vocabulary, task_card, notes)
    notes.assumptions.extend(text for text in card.get("assumptions") or [])
    notes.warnings.extend("stage 1 unknown: %s" % text for text in card.get("unknowns") or [])
    for conflict in card.get("conflicts") or []:
        if not conflict.get("resolved"):
            notes.assumptions.append("неразрешённое противоречие этапа 1: %s" % conflict.get("title"))
    return task_card, notes.assumptions, notes.warnings


def _files(card):
    analysis = card.get("stl_analysis") or {}
    if not analysis.get("attachment_id"):
        return []
    return [{"path": "attachment:" + analysis["attachment_id"], "kind": "stl"}]


def _with_ids(requirements):
    """Stage 1 has no requirement ids; its stable key is the id, made unique for repeated keys."""
    seen = {}  # type: dict
    for requirement in requirements:
        key = requirement.get("key") or "unnamed"
        seen[key] = seen.get(key, 0) + 1
        yield requirement, key if seen[key] == 1 else "%s-%d" % (key, seen[key])


def _source(requirement):
    if not requirement.get("verified"):
        return "assumption"
    return _PROVENANCE_SOURCE.get(requirement.get("provenance"), "assumption")


def _basis(requirement):
    quotes = [source.get("quote") for source in requirement.get("sources") or [] if source.get("quote")]
    return "; ".join([requirement.get("label") or ""] + quotes[:1]).strip("; ")


def _read_requirement(requirement, requirement_id, vocabulary, task_card, notes):
    key = requirement.get("key")
    label = "%s (%s)" % (requirement_id, requirement.get("label") or key)
    if key in vocabulary["card_fields"]:
        _read_card_field(vocabulary["card_fields"][key], requirement, requirement_id, vocabulary, task_card, notes)
        return
    entry = vocabulary["requirements"].get(key)
    if entry is None:
        _not_interpreted(requirement, label, notes)
        return
    try:
        value = _typed_value(entry, requirement, vocabulary)
    except ValueParseError as error:
        _not_interpreted(requirement, "%s: %s" % (label, error), notes)
        return
    task_card["requirements"].append(
        {
            "id": requirement_id,
            "kind": "stage1",
            "key": entry["key"],
            "value": value,
            "hard": bool(requirement.get("mandatory")),
            "source": _source(requirement),
            "basis": _basis(requirement),
        }
    )


def _typed_value(entry, requirement, vocabulary):
    text = "%s" % (requirement.get("value"),)
    if entry["type"] == "number":
        if not unit_matches(requirement.get("unit"), entry["unit"], vocabulary["units"]):
            raise ValueParseError("unit %r, expected %s" % (requirement.get("unit"), entry["unit"]))
        return parse_number(text, entry["range"])
    if entry["type"] == "bool":
        return parse_bool(text, vocabulary["booleans"])
    return parse_list(text)


def _not_interpreted(requirement, label, notes):
    if requirement.get("mandatory"):
        notes.assumptions.append("обязательное требование %s не учтено подбором параметров" % label)
    else:
        notes.warnings.append("requirement %s is not used by parameter selection" % label)


def _read_card_field(field, requirement, requirement_id, vocabulary, task_card, notes):
    text = "%s" % (requirement.get("value"),)
    label = "%s (%s)" % (requirement_id, requirement.get("label") or requirement.get("key"))
    if field == "quantity":
        try:
            task_card["preferences"]["quantity"] = int(parse_number(text, "upper"))
        except ValueParseError as error:
            notes.warnings.append("quantity %s: %s" % (label, error))
    elif field == "load":
        _set_load(text, label, vocabulary, task_card, notes)
    elif field == "printing_mode":
        _set_printing_mode(text.strip().lower(), requirement_id, vocabulary, task_card, notes)
    elif _source(requirement) == "assumption":
        notes.warnings.append("material %s is not confirmed, catalog ranking is used" % label)
    else:
        task_card["material"] = {"name": text, "requirement_id": requirement_id}


def _set_load(text, origin, vocabulary, task_card, notes):
    lowered = text.lower()
    for load, phrases in vocabulary["load_phrases"]:
        if any(phrase in lowered for phrase in phrases):
            task_card["part"]["load"] = load
            notes.assumptions.append("нагрузка «%s» выведена из текста: %s" % (load, origin))
            return
    notes.warnings.append("load of %s not recognised: %r" % (origin, text))


def _set_printing_mode(mode, requirement_id, vocabulary, task_card, notes):
    if mode in vocabulary["printing_modes"]:
        task_card["preferences"]["printing_mode"] = mode
        task_card["preferences"]["printing_mode_requirement_id"] = requirement_id
    else:
        notes.warnings.append(
            "printing mode %s is not one of %s" % (requirement_id, ", ".join(vocabulary["printing_modes"]))
        )


def _read_answers(answers, vocabulary, task_card):
    for question_id, field in sorted(vocabulary["answers"].items()):
        answer = answers.get(question_id)
        if field == "material" and answer and not task_card["material"].get("name"):
            task_card["material"] = {"name": answer, "requirement_id": "answer." + question_id}


def _read_free_text(card, vocabulary, task_card, notes):
    """Priorities and the ban on supports from preferences; load from production constraints."""
    preferences = [text for text in card.get("preferences") or [] if text]
    joined = " ".join(preferences).lower()
    positions = []
    for priority, phrases in sorted(vocabulary["priority_phrases"].items()):
        hits = [joined.find(phrase) for phrase in phrases if phrase in joined]
        if hits:
            positions.append((min(hits), priority))
    if positions:
        task_card["preferences"]["priority"] = [priority for _, priority in sorted(positions)]
        notes.assumptions.append(
            "приоритеты %s выведены из текста пожеланий" % ", ".join(task_card["preferences"]["priority"])
        )
    if any(phrase in joined for phrase in vocabulary["supports_forbidden_phrases"]):
        task_card["preferences"]["supports_allowed"] = False
        notes.assumptions.append("поддержки запрещены по тексту пожеланий")
    if "load" not in task_card["part"]:
        for constraint in card.get("production_constraints") or []:
            if _matches_load(constraint, vocabulary):
                _set_load(constraint, "ограничение производства «%s»" % constraint, vocabulary, task_card, notes)
                break


def _matches_load(text, vocabulary):
    lowered = text.lower()
    return any(phrase in lowered for _, phrases in vocabulary["load_phrases"] for phrase in phrases)
