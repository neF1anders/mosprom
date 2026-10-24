"""Facts parameter selection needs, checked by the quick triage before the deep reading.

A field the triage could not cite becomes a question. Its id is tied to the field, so an
answered question never comes back under another wording.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Question

MAX_TRIAGE_QUESTIONS = 5


@dataclass(frozen=True)
class Field:
    key: str
    title: str
    impact: str
    hint: str
    options: tuple[str, ...] = ()
    blocking: bool = False

    @property
    def question_id(self) -> str:
        return "purpose" if self.key == "purpose" else f"field.{self.key}"


FIELDS = (
    Field(
        "purpose",
        "Для чего нужна деталь",
        "Назначение определяет требования к материалу и параметрам",
        "что это за деталь и где она работает",
        blocking=True,
    ),
    Field(
        "geometry_editable",
        "Можно ли править геометрию модели",
        "Определяет, можно ли утолщать стенки и добавлять припуски",
        "разрешено ли менять модель или печатать строго по ней",
        ("Можно править", "Печать строго по модели"),
        blocking=True,
    ),
    Field(
        "environment",
        "В какой среде работает деталь",
        "Влияет на выбор материала по химической стойкости, влажности и ультрафиолету",
        "среда, жидкости, химия, влажность, улица или помещение",
    ),
    Field(
        "temperature",
        "Какая рабочая температура у детали",
        "Влияет на выбор материала по теплостойкости",
        "рабочая и предельная температура",
    ),
    Field(
        "loads",
        "Какие нагрузки действуют на деталь",
        "Влияет на прочность, заполнение и ориентацию при печати",
        "силы, моменты, давление, удары, вибрация, режим работы",
    ),
    Field(
        "fits",
        "Есть ли посадочные места и допуски",
        "Влияет на точность размеров и припуски",
        "посадки, отверстия под вал или крепёж, допуски",
    ),
    Field(
        "post_processing",
        "Допустима ли обработка после печати",
        "Влияет на припуски и выбор режима печати",
        "можно ли шлифовать, сверлить, отжигать, дорабатывать",
        ("Допустима", "Без обработки"),
    ),
)
BY_KEY = {field.key: field for field in FIELDS}


def field_question(
    key: str,
    options: list[str] | None = None,
    suggested: str | None = None,
    basis: str | None = None,
) -> Question:
    field = BY_KEY[key]
    choices = [o for o in (options or []) if o.strip()] or list(field.options)
    return Question(
        id=field.question_id,
        kind="purpose" if key == "purpose" else "clarify",
        title=field.title,
        impact=field.impact,
        options=list(dict.fromkeys(choices)),
        suggested=suggested if basis and suggested in choices else None,
        basis=basis if suggested in choices else None,
        blocking=field.blocking,
    )


def triage_questions(missing: list[str], proposals: dict[str, dict]) -> list[Question]:
    """Blocking fields first, then the order of FIELDS, at most MAX_TRIAGE_QUESTIONS."""
    order = sorted(
        (BY_KEY[key] for key in dict.fromkeys(missing) if key in BY_KEY),
        key=lambda f: (not f.blocking, FIELDS.index(f)),
    )
    return [field_question(f.key, **proposals.get(f.key, {})) for f in order[:MAX_TRIAGE_QUESTIONS]]
