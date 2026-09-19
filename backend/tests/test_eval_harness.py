"""Phase 4: calibration-harness metrics + discovery (pure, no model call)."""

from __future__ import annotations

from eval.harness import Counts, discover, format_report, score_one


def test_score_one_maps_outcomes_to_confusion_matrix():
    c = Counts()
    score_one("pass", expected_pass=True, counts=c)  # tp
    score_one("pass", expected_pass=False, counts=c)  # fp
    score_one("fail", expected_pass=False, counts=c)  # tn
    score_one("fail", expected_pass=True, counts=c)  # fn
    score_one("needs_review", expected_pass=True, counts=c)
    score_one("error", expected_pass=False, counts=c)

    assert (c.tp, c.fp, c.tn, c.fn, c.review, c.error) == (1, 1, 1, 1, 1, 1)
    assert c.precision() == 0.5
    assert c.recall() == 0.5
    assert c.accuracy() == 0.5
    assert c.total == 6


def test_metrics_are_none_when_undefined():
    c = Counts()
    assert c.precision() is None and c.recall() is None and c.accuracy() is None
    assert c.mean_latency_ms() is None


def test_discover_reads_pass_and_fail_folders(tmp_path):
    for chore, label, name in [
        ("sink", "pass", "a.jpg"),
        ("sink", "fail", "b.jpeg"),
        ("room", "pass", "c.jpg"),
    ]:
        d = tmp_path / chore / label
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"x")
    (tmp_path / "empty").mkdir()

    found = discover(tmp_path)
    assert set(found) == {"sink", "room"}  # "empty" has no images
    assert sorted(exp for _, exp in found["sink"]) == [False, True]


def test_format_report_has_a_header_and_row():
    c = Counts()
    score_one("pass", True, c)
    out = format_report({"sink": c})
    assert out.splitlines()[0].startswith("chore")
    assert "sink" in out


# --- the harness itself has to build a prompt that the app accepts -----------


def test_run_builds_a_prompt_the_current_signature_accepts():
    """`just eval` was dead: run() still called build_task_prompt(photo_label=…) with bare
    strings for checks, long after the signature grew photo_labels and (id, text) pairs.
    Nothing noticed because every eval test covered the pure helpers and none covered run().
    """
    import inspect

    from eval.harness import DEFAULT_CHECKLISTS, run, specs_for

    from app.services.verification import build_task_prompt

    src = inspect.getsource(run)
    assert "photo_label=" not in src, "singular kwarg no longer exists"

    # The real proof: the call the harness makes must actually type-check at runtime.
    prompt = build_task_prompt(
        chore_title="sink",
        photo_labels=None,
        checks=specs_for(DEFAULT_CHECKLISTS["sink"]),
    )
    assert "1. Are there dirty dishes" in prompt
    assert "Do not count these as a problem: sponge, dish brush, drain strainer." in prompt


def test_specs_for_accepts_both_checklist_shapes():
    from eval.harness import specs_for

    old = specs_for({"checks": ["Is the bed made?"]})
    assert (old[0].id, old[0].expect, old[0].ignore) == (1, "yes", ())

    new = specs_for({"checks": [{"text": "Are there clothes on the floor?", "expect": "no"}]})
    assert (new[0].id, new[0].expect) == (1, "no")


# --- replaying stored verifications ------------------------------------------


def _envelope(checks: list[dict], overall: float = 0.9) -> dict:
    import json as _json

    body = {
        "checks": checks,
        "overall_confidence": overall,
        "child_message": "ok",
        "image_quality_issue": "none",
    }
    return {"choices": [{"message": {"content": _json.dumps(body)}}]}


def test_replay_reads_the_model_back_out_of_a_stored_envelope():
    from eval.replay import _model_response

    parsed = _model_response(
        _envelope([{"id": 1, "evidence": "empty", "answer": "yes", "confidence": 0.9}])
    )
    assert parsed is not None and parsed.checks[0].answer == "yes"


def test_replay_skips_a_row_it_cannot_parse_instead_of_dying():
    # Rows predate the settled schema, and a repair retry can store something that never
    # parsed. One bad row must not cost the whole replay.
    from eval.replay import _model_response

    assert _model_response(None) is None
    assert _model_response({"choices": []}) is None
    assert _model_response({"choices": [{"message": {"content": "not json"}}]}) is None


def test_replay_report_names_what_moved():
    from eval.replay import Replayed, format_report

    rows = [
        Replayed("v1", "Kitchen", "fail", "needs_review", "needs_review"),
        Replayed("v2", "Kitchen", "fail", "needs_review", "needs_review"),
        Replayed("v3", "Tidy room", "pass", "pass", "pass"),
    ]
    out = format_report(rows, skipped=1)
    assert "replayed 3 verifications, 2 would be decided differently" in out
    assert "2  fail -> needs_review" in out
    assert "skipped 1" in out


def test_a_retake_is_not_a_change_from_needs_review():
    """The worker maps several outcomes onto one Verdict, so the replay has to compare
    verdicts, not outcomes. Comparing raw outcomes flagged the first real row replayed as
    a difference when nothing had changed at all."""
    from eval.replay import Replayed

    assert not Replayed("v1", "Kitchen", "needs_review", "retake", "needs_review").changed
    assert Replayed("v2", "Kitchen", "fail", "needs_review", "needs_review").changed
