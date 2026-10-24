"""Stage-2 data contracts: the internal task_card/0 and the structure of stage2.parameter_set v0.1."""

import re

from tuning.errors import TuningError

_CARD_FIELDS = frozenset(
    [
        "schema",
        "status",
        "inputs",
        "part",
        "requirements",
        "preferences",
        "material",
        "assumptions",
        "missing",
    ]
)
# `source` values of stage2.parameter_set v0.1 (same pattern as the stage-3 checker).
_SOURCE_PATTERN = re.compile(r"^(requirement|rule|constraint|assumption):[\w\-.]+$|^default$")
PARAMETER_SET_STATUSES = ("proposed", "infeasible")


def normalize_card(card):
    # type: (dict) -> tuple
    """Return (card without unknown fields, warnings). Only `status` and `inputs` are mandatory."""
    if not isinstance(card, dict):
        raise TuningError("task card must be a JSON object")
    for field in ("status", "inputs"):
        if field not in card:
            raise TuningError("task card has no required field '%s'" % field)
    if card["status"] != "ready":
        raise TuningError("task card status is '%s', expected 'ready'" % card["status"])
    warnings = ["unknown card field '%s' ignored" % name for name in sorted(set(card) - _CARD_FIELDS)]
    known = {name: value for name, value in card.items() if name in _CARD_FIELDS}
    requirements = []
    for index, requirement in enumerate(known.get("requirements", [])):
        missing = [name for name in ("id", "key", "value") if name not in requirement]
        if missing:
            warnings.append("requirement #%d skipped: no %s" % (index, ", ".join(missing)))
            continue
        normalized = dict(requirement)
        if "source" not in normalized:
            warnings.append("requirement %s has no source, treated as assumption" % requirement["id"])
            normalized["source"] = "assumption"
        normalized["hard"] = bool(normalized.get("hard", False))
        requirements.append(normalized)
    known["requirements"] = requirements
    return known, warnings


def _check_explained(name, entry, errors):
    if not isinstance(entry, dict) or not str(entry.get("why", "")).strip():
        errors.append("%s: empty why" % name)
        return
    if not _SOURCE_PATTERN.match(str(entry.get("source", ""))):
        errors.append("%s: malformed source %r" % (name, entry.get("source")))


def parameter_set_errors(parameter_set):
    # type: (dict) -> list
    """Structural violations of stage2.parameter_set v0.1 (plus our `status`); empty means valid.

    Values against the slicer definitions are checked by stage 3 (validation/tools/check_parameter_set.py).
    """
    errors = []
    if parameter_set.get("contract") != "stage2.parameter_set" or parameter_set.get("version") != "0.1":
        errors.append("contract must be stage2.parameter_set 0.1")
    if parameter_set.get("iteration") not in (1, 2):
        errors.append("iteration must be 1 or 2")
    reference = parameter_set.get("card_ref") or {}
    if not reference.get("job_id") or not isinstance(reference.get("revision"), int):
        errors.append("card_ref needs job_id and an integer revision")
    if parameter_set.get("status") not in PARAMETER_SET_STATUSES:
        errors.append("unknown status %r" % parameter_set.get("status"))
    _check_explained("printing_mode", parameter_set.get("printing_mode"), errors)
    _check_explained("quality", parameter_set.get("quality"), errors)
    materials = parameter_set.get("materials") or {}
    if not materials:
        errors.append("materials: missing")
    for position, material in sorted(materials.items()):
        _check_explained("materials[%s]" % position, material, errors)
    for key, setting in sorted((parameter_set.get("settings") or {}).items()):
        if not isinstance(setting, dict) or "value" not in setting:
            errors.append("settings.%s: no value" % key)
        _check_explained("settings.%s" % key, setting, errors)
    if not parameter_set.get("models"):
        errors.append("models: missing")
    for index, model in enumerate(parameter_set.get("models") or []):
        _check_explained("models[%d]" % index, model, errors)
    known = set(a.get("id") for a in parameter_set.get("assumptions") or [])
    for name, entry in _explained_entries(parameter_set):
        source = str(entry.get("source", ""))
        if source.startswith("assumption:") and source.split(":", 1)[1] not in known:
            errors.append("%s: source points to an unknown assumption %s" % (name, source))
    return errors


def _explained_entries(parameter_set):
    yield "printing_mode", parameter_set.get("printing_mode") or {}
    yield "quality", parameter_set.get("quality") or {}
    for position, material in sorted((parameter_set.get("materials") or {}).items()):
        yield "materials[%s]" % position, material
    for key, setting in sorted((parameter_set.get("settings") or {}).items()):
        yield "settings.%s" % key, setting
    for index, model in enumerate(parameter_set.get("models") or []):
        yield "models[%d]" % index, model
