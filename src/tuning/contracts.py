"""Validation of the stage-2 data contracts (task_card/0, param_set/0, verdict/0)."""

import re

from tuning.errors import TuningError

PARAM_STATUSES = ("proposed", "final", "exhausted", "infeasible")
VERDICT_SIGNALS = ("too_weak", "too_costly", "wrong_value", "conflict")
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
_SOURCE_PATTERN = re.compile(r"^(card|rank|rule:.+|search:it\d+|default:.+)$")


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


def validate_verdict(verdict):
    # type: (dict) -> None
    if not isinstance(verdict, dict) or "ok" not in verdict:
        raise TuningError("verdict must be an object with field 'ok'")
    for issue in verdict.get("issues", []):
        if issue.get("signal") not in VERDICT_SIGNALS:
            raise TuningError("verdict issue %s has unknown signal %r" % (issue.get("id"), issue.get("signal")))


def _check_explained(name, entry, errors):
    for field in ("source", "reason"):
        if not entry.get(field):
            errors.append("%s: empty %s" % (name, field))
    if entry.get("source") and not _SOURCE_PATTERN.match(entry["source"]):
        errors.append("%s: malformed source %r" % (name, entry["source"]))


def param_set_errors(param_set):
    # type: (dict) -> list
    """List of contract violations in a param_set/0; empty means valid."""
    errors = []
    if param_set.get("schema") != "param_set/0":
        errors.append("schema must be param_set/0")
    if param_set.get("status") not in PARAM_STATUSES:
        errors.append("unknown status %r" % param_set.get("status"))
    for name in ("printing_mode", "material"):
        entry = param_set.get(name)
        if not isinstance(entry, dict) or "value" not in entry:
            errors.append("%s: missing" % name)
        else:
            _check_explained(name, entry, errors)
    for setting in param_set.get("settings", []):
        label = "setting %s" % setting.get("key")
        for field in ("key", "value", "target"):
            if field not in setting:
                errors.append("%s: no %s" % (label, field))
        _check_explained(label, setting, errors)
    return errors
