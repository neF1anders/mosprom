"""Printing mode: weighted votes of the fired rules and of a check constraint.

A mode the part does not fit as loaded, or one a constraint forbids, gets no votes; a request
for it that outweighs the default is told to the user.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .constraints import MODE_KEY, Choices
from .geometry import Point
from .intake import ModeRequest
from .notes import EPSILON, Unmet
from .printer import Mode
from .rules import REASONS, FactValue, ModeVoteAction, Rule, vote_mode

CARD_HINT_RULE = "MODE-CARD-HINT"
CONSTRAINT_WEIGHT = 1000.0
FALLBACK_MODE = "classic"


@dataclass(frozen=True)
class Vote:
    mode: str
    weight: float
    rule_id: str


@dataclass(frozen=True)
class ModeChoice:
    value: str
    why: str
    source: str
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unmet: tuple[Unmet, ...] = ()
    # The part fits none of the modes it was meant for.
    misfit: bool = False


def choose_mode(
    fired: Sequence[Rule],
    facts: Mapping[str, FactValue],
    choices: Choices,
    request: ModeRequest | None,
    size: Point,
    modes: Mapping[str, Mode],
) -> ModeChoice:
    votes = [
        Vote(vote_mode(action.mode, facts), action.weight, rule.id)
        for rule in fired
        for action in rule.then
        if isinstance(action, ModeVoteAction)
    ]
    forced = choices.forced.get(MODE_KEY)
    if forced is not None:
        votes.append(
            Vote(str(forced.value), CONSTRAINT_WEIGHT, f"constraint:{forced.constraint_id}")
        )
    warnings = tuple(
        f"printing mode '{vote.mode}' from {vote.rule_id} is unknown, ignored"
        for vote in votes
        if vote.mode not in modes
    )
    weights: dict[str, float] = {}
    assumptions = []
    for vote in (vote for vote in votes if vote.mode in modes):
        rejected = _rejection(vote.mode, choices, size, modes[vote.mode])
        if rejected is None:
            weights[vote.mode] = weights.get(vote.mode, 0.0) + vote.weight
        elif vote.weight > 1.0:
            assumptions.append(f"режим {vote.mode} не выбран: {rejected}")
    if not weights:
        return _nowhere(size, modes, tuple(assumptions), warnings)
    winner = max(sorted(weights), key=lambda mode: weights[mode])
    top = max((vote for vote in votes if vote.mode == winner), key=lambda vote: vote.weight)
    why, source = _reason(top.rule_id, request)
    return ModeChoice(winner, why, source, tuple(assumptions), warnings)


def fits(size: Point, mode: Mode) -> bool:
    """The part as loaded inside the print area: the ellipse of 5D, the usable strip of 3D."""
    width, depth, height = size
    if height > mode.height + EPSILON:
        return False
    if mode.elliptic:
        semi_x, semi_y = mode.width / 2.0, mode.depth / 2.0
        return (width / 2.0 / semi_x) ** 2 + (depth / 2.0 / semi_y) ** 2 <= 1.0 + EPSILON
    low, high = mode.usable_x
    return width <= high - low + EPSILON and depth <= mode.depth + EPSILON


def _rejection(name: str, choices: Choices, size: Point, mode: Mode) -> str | None:
    if not choices.permits(MODE_KEY, name):
        return "запрещён ограничением этапа 3"
    if not fits(size, mode):
        return "деталь не помещается в область печати этого режима"
    return None


def _reason(rule_id: str, request: ModeRequest | None) -> tuple[str, str]:
    if rule_id.startswith("constraint:"):
        return "режим задан ограничением этапа 3", rule_id
    if rule_id == CARD_HINT_RULE:
        requirement_id = request.requirement_id if request else "printing_mode"
        return REASONS[rule_id], f"requirement:{requirement_id}"
    return REASONS[rule_id], f"rule:{rule_id}"


def _nowhere(
    size: Point,
    modes: Mapping[str, Mode],
    assumptions: tuple[str, ...],
    warnings: tuple[str, ...],
) -> ModeChoice:
    fitting = [name for name in sorted(modes) if fits(size, modes[name])]
    where = f"помещаются в: {', '.join(fitting)}" if fitting else "не помещаются ни в один режим"
    why = (
        f"габариты {list(size)} мм при ориентации «как загружено» не помещаются в выбранный режим"
        f"; {where}"
    )
    return ModeChoice(
        FALLBACK_MODE,
        "деталь не помещается ни в один режим; оставлен 3D",
        "default",
        assumptions,
        warnings,
        (Unmet("GEOMETRY", why),),
        misfit=True,
    )
