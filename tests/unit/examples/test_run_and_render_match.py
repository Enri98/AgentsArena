"""Smoke tests for the examples/run_and_render_match.py script."""

from __future__ import annotations

from pathlib import Path

from examples.run_and_render_match import run_and_render


def test_run_and_render_produces_files(tmp_path: Path) -> None:
    rendered = run_and_render(tmp_path)

    assert (tmp_path / "status.json").exists()
    assert (tmp_path / "transcript.json").exists()
    assert isinstance(rendered, str)
    assert len(rendered) > 0


def test_run_and_render_status_is_valid_json(tmp_path: Path) -> None:
    import json

    run_and_render(tmp_path)

    status_data = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status_data["schema_version"] == 1
    assert status_data["lifecycle"] == "finished"


def test_run_and_render_transcript_is_valid_json(tmp_path: Path) -> None:
    import json

    run_and_render(tmp_path)

    transcript_data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert transcript_data["schema_version"] == 1
    assert "match_transcript" in transcript_data


def test_run_and_render_output_is_non_empty(tmp_path: Path) -> None:
    rendered = run_and_render(tmp_path)

    assert "connect4" in rendered
    assert len(rendered.strip()) > 0
