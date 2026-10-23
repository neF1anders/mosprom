"""Validator loop helpers: verdict -> per-parameter feedback, history records, best-so-far choice."""

TOLERANCE = 1e-9


def key_index(space):
    # type: (dict) -> dict
    """Map every slicer key to ("param", id) or ("discrete", id)."""
    index = {}
    for param in space["params"]:
        for keys in param.get("keys", {}).values():
            for key in keys:
                index[key] = ("param", param["id"])
        for key in param.get("emit", {}).get("keys", []):
            index[key] = ("param", param["id"])
    for item in space["discrete"]:
        if "candidates" in item:
            for keys in item["keys"].values():
                for key in keys:
                    index[key] = ("discrete", item["id"])
    return index


def build_feedback(verdict, index):
    # type: (dict, dict) -> dict
    """Group issues by continuous parameter; discrete findings become banned values."""
    signals = {}  # type: dict
    banned = {}  # type: dict
    ignored = []
    for issue in verdict.get("issues", []):
        target = index.get(issue.get("key"))
        if target is None:
            ignored.append(issue.get("id"))
        elif target[0] == "param":
            signals.setdefault(target[1], []).append(
                {"signal": issue["signal"], "severity": issue.get("severity"), "issue_id": issue.get("id")}
            )
    for veto in verdict.get("vetoes", []):
        target = index.get(veto.get("key"))
        if target is not None and target[0] == "discrete":
            banned.setdefault(target[1], []).append(veto["value"])
    return {
        "ok": bool(verdict["ok"]),
        "score": verdict.get("score"),
        "signals": signals,
        "banned": banned,
        "ignored_issues": ignored,
    }


def history_record(iteration, points, verdict):
    # type: (int, dict, dict) -> dict
    issues = verdict.get("issues", [])
    severities = [issue.get("severity") or 0.0 for issue in issues]
    return {
        "iteration": iteration,
        "points": dict(points),
        "ok": bool(verdict["ok"]),
        "score": verdict.get("score"),
        "issue_count": len(issues),
        "severity_sum": round(sum(severities), 4),
        "issues": [
            {
                "id": i.get("id"),
                "key": i.get("key"),
                "requirement_id": i.get("requirement_id"),
                "message": i.get("message", ""),
            }
            for i in issues
        ],
    }


def best_record(history):
    # type: (list) -> dict
    """Highest score; without scores fewest issues, then smallest severity; later iteration wins ties."""

    def rank(record):
        score = record["score"] if record["score"] is not None else float("-inf")
        return (score, -record["issue_count"], -record["severity_sum"], record["iteration"])

    return max(history, key=rank)


def searched_iterations(history, points, iteration):
    # type: (list, dict, int) -> dict
    """For each parameter, the latest iteration <= `iteration` at which the search changed its t."""
    sequence = {record["iteration"]: record["points"] for record in history}
    sequence[iteration] = points
    changed = {}
    for step in range(1, iteration + 1):
        if step in sequence and step - 1 in sequence:
            for pid, t in sequence[step].items():
                if abs(t - sequence[step - 1][pid]) > TOLERANCE:
                    changed[pid] = step
    return changed
