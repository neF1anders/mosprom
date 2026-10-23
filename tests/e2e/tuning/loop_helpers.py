import json


def start(run_tuning, tmp_path, card, stl, *extra):
    state_path = tmp_path / "state0.json"
    code, out, err = run_tuning("select", "--card", card, "--stl", stl, "--state-out", str(state_path), *extra)
    assert code == 0, err
    return json.loads(out), str(state_path)


def advance(run_tuning, tmp_path, card, stl, state_path, verdict, number, *extra):
    verdict_path = tmp_path / ("verdict%d.json" % number)
    verdict_path.write_text(json.dumps(dict(verdict, schema="verdict/0")), encoding="utf-8")
    next_state = tmp_path / ("state%d.json" % number)
    code, out, err = run_tuning("select", "--card", card, "--stl", stl, "--state", state_path,
                                "--verdict", str(verdict_path), "--state-out", str(next_state), *extra)
    assert code == 0, err
    return json.loads(out), str(next_state)


def setting(param_set, key):
    return {item["key"]: item for item in param_set["settings"]}[key]


def issue(key, signal, number=1, requirement_id="R1", severity=None):
    found = {"id": "V%d" % number, "key": key, "signal": signal, "requirement_id": requirement_id, "message": "validator: " + signal}
    if severity is not None:
        found["severity"] = severity
    return found
