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
