import json

from stage1_factory import constraint, feedback, handoff, requirement, write_handoff

CARD = dict(requirements=[requirement("load_bearing", "ударная нагрузка")], preferences=["прочность, затем скорость"])


def test_same_card_and_feedback_give_identical_bytes(run_tuning, tmp_path):
    path = write_handoff(tmp_path / "handoff.json", handoff(**CARD))
    review = tmp_path / "feedback.json"
    review.write_text(json.dumps(feedback(constraint("C1", "infill_sparse_density", "max", 25))), encoding="utf-8")
    first = run_tuning("select", "--input", path)
    again = run_tuning("select", "--input", path)
    assert first[0] == 0 and first[1] == again[1]
    second = run_tuning("select", "--input", path, "--feedback", str(review))
    second_again = run_tuning("select", "--input", path, "--feedback", str(review))
    assert second[0] == 0 and second[1] == second_again[1]
