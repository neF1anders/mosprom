"""Render stage-2 decisions as `stage2.parameter_set` v0.1 (the contract of stage 3 and of the slicer adapter).

Fields beyond the contract (`status`, `unsatisfied`, `warnings`, `idempotency_key`, material `alternatives` and
`checks`, model `orientation_candidate`) are our proposal; the stage-3 checker ignores unknown fields.
"""

from typing import Any  # noqa: F401  (used in type comments)

CONTRACT = "stage2.parameter_set"
VERSION = "0.1"
STAGE1_BASIS = "карточка этапа 1"
STAGE2_BASIS = "решение этапа 2"


def render(intake, decisions, iteration):
    # type: (Any, Any, int) -> dict
    assumptions, ids = _assumptions(intake.assumptions, decisions.assumptions)
    models = []
    for model in decisions.models:
        placed = dict(model)
        placed["source"] = "assumption:" + ids[decisions.orientation_assumption]
        models.append(placed)
    parameter_set = {
        "contract": CONTRACT,
        "version": VERSION,
        "card_ref": intake.card_ref,
        "iteration": iteration,
        "printer": decisions.profile["id"],
        "printing_mode": decisions.mode,
        "quality": decisions.quality,
        "materials": {"0": decisions.choice.block},
        "settings": decisions.settings,
        "models": models,
        "assumptions": assumptions,
        "status": "infeasible" if decisions.infeasible else "proposed",
        "unsatisfied": decisions.unsatisfied,
        "warnings": intake.warnings + decisions.warnings,
        "idempotency_key": intake.idempotency_key,
    }
    if iteration > 1:
        parameter_set["applied_constraints"] = decisions.applied_constraints
    return parameter_set


def _assumptions(from_card, from_selection):
    """Numbered assumptions (A1, A2, ...) and the id of each text, so that `source: assumption:<id>` can point to it."""
    entries, ids = [], {}
    for texts, basis in ((from_card, STAGE1_BASIS), (from_selection, STAGE2_BASIS)):
        for text in texts:
            if text in ids:
                continue
            ids[text] = "A%d" % (len(entries) + 1)
            entries.append({"id": ids[text], "text": text, "basis": basis})
    return entries, ids
