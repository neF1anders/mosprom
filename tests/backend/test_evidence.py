import pytest

from src.backend.domain.evidence import merge_cards, validate_evidence
from src.backend.domain.models import Evidence, Requirement, TaskCard
from src.backend.domain.rules import assess

pytestmark = pytest.mark.unit

@pytest.mark.parametrize('value', ['80', '100,5', '0', '-10', '15'])
def test_user_correction_replaces_unverified_value(value):
    from src.backend.domain.evidence import apply_answers
    card = validate_evidence(TaskCard(requirements=[Requirement(key='size', label='Размер', value='100')]), {})
    question = card.questions[0]
    apply_answers(card, {question.id: value}, {}, 'answer-source')
    assert card.requirements[0].value == value
    assert card.requirements[0].verified
    assert card.requirements[0].sources[0].source_id == 'answer-source'

@pytest.mark.parametrize('answer', ['да', 'готово', 'mm', 'любое', '100'])
def test_model_cannot_supply_its_own_answers(answer):
    from src.backend.domain.models import Geometry, Question
    card = TaskCard(purpose='gear', geometry=Geometry(readable=True, units='mm'), questions=[Question(id='load',title='Load',reason='Required',answer=answer,affected_actions=[])])
    assert assess(card).readiness == 'blocked'

@pytest.mark.parametrize('count', [1, 2, 5, 10, 50])
def test_conflicts_group_values_without_pairwise_explosion(count):
    cards = [TaskCard(requirements=[Requirement(key='size',value=str(i))]) for i in range(count)]
    result = merge_cards(cards)
    assert len(result.conflicts) == (1 if count > 1 else 0)
