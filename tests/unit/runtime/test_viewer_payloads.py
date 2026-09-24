"""Runtime payloads per viewer, and redaction of saved payloads (Phase 38)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from arena.games import build_default_registry
from arena.match import apply_match_action, start_match
from arena.runtime.models import PlayerRecord, PolicyDecided
from arena.runtime.payloads import (
    dump_runtime_transcript,
    dump_session_status,
    redact_runtime_transcript,
    redact_session_status,
    validate_runtime_transcript,
)
from arena.runtime.session import Arena
from arena.testing.hidden_factory import SecretsPass, build_secrets_game_definition
from arena.ui import build_match_screen

SECRETS = build_secrets_game_definition()


def _session():
    arena = Arena()
    session = arena.create_session(
        SECRETS,
        SECRETS.config_type(),
        [PlayerRecord(player_id="p0", seat=0), PlayerRecord(player_id="p1", seat=1)],
        {},
    )
    match = start_match(SECRETS, SECRETS.config_type(), seed=11)
    match = apply_match_action(match, 0, SecretsPass())
    events = session.events + (
        PolicyDecided(match_id=session.match_id, seat=0, attempt=1, thought="I hold a 3"),
        PolicyDecided(match_id=session.match_id, seat=1, attempt=1, thought="I hold an 8"),
    )
    return dataclasses.replace(session, local_match=match, events=events), match


def test_the_full_transcript_is_the_default_and_replays() -> None:
    session, _ = _session()
    full = dump_runtime_transcript(session)
    assert full["view"] == "full"
    validate_runtime_transcript(SECRETS, full)


def test_a_seat_transcript_carries_only_that_seats_view() -> None:
    session, match = _session()
    secrets = match.state.secrets
    seat_0 = dump_runtime_transcript(session, viewer=0)

    assert seat_0["view"] == "seat" and seat_0["viewer_seat"] == 0
    text = json.dumps(seat_0)
    assert '"secrets"' not in text
    assert f'"my_secret": {secrets[0]}' in text
    # The other seat's reasoning could name its hand.
    thoughts = [
        e["payload"]["thought"] for e in seat_0["events"] if e["event_type"] == "PolicyDecided"
    ]
    assert thoughts == ["I hold a 3"]


def test_the_public_transcript_has_no_hands_and_no_thoughts() -> None:
    session, _ = _session()
    public = dump_runtime_transcript(session, viewer=None)
    assert public["view"] == "public"
    assert "my_secret" not in json.dumps(public["match_transcript"])
    assert not [e for e in public["events"] if e["event_type"] == "PolicyDecided"]


@pytest.mark.parametrize("viewer", [0, 1, None])
def test_redacting_a_saved_full_transcript_matches_the_live_view(viewer) -> None:
    session, _ = _session()
    full = dump_runtime_transcript(session)
    assert redact_runtime_transcript(SECRETS, full, viewer) == dump_runtime_transcript(
        session, viewer=viewer
    )
    assert redact_session_status(SECRETS, dump_session_status(session), viewer) == (
        dump_session_status(session, viewer=viewer)
    )


def test_a_redacted_payload_cannot_be_redacted_again() -> None:
    session, _ = _session()
    with pytest.raises(ValueError, match="Only a full"):
        redact_runtime_transcript(SECRETS, dump_runtime_transcript(session, viewer=0), 1)


def test_perfect_information_payloads_are_full_for_every_viewer() -> None:
    connect4 = build_default_registry().get("connect4")
    arena = Arena()
    session = arena.start_session(
        arena.create_session(
            connect4,
            connect4.config_type(),
            [PlayerRecord(player_id="p0", seat=0), PlayerRecord(player_id="p1", seat=1)],
            {},
        )
    )
    full = dump_runtime_transcript(session)
    for viewer in (0, 1, None):
        assert dump_runtime_transcript(session, viewer=viewer) == full


def test_the_ui_refuses_to_render_another_seats_view() -> None:
    session, _ = _session()
    status = dump_session_status(session, viewer=0)
    transcript = dump_runtime_transcript(session, viewer=0)

    screen = build_match_screen(status_payload=status, transcript_payload=transcript, seat=0)
    assert screen["status"]["view"] == "seat"
    with pytest.raises(ValueError, match="redacted for seat 0"):
        build_match_screen(status_payload=status, transcript_payload=transcript, seat=1)


def test_the_cli_viewer_renders_one_seats_perspective(tmp_path, monkeypatch) -> None:
    import arena.games
    from arena.cli.app import render_session_from_files

    session, match = _session()
    status_path = tmp_path / "status.json"
    transcript_path = tmp_path / "transcript.json"
    status_path.write_text(json.dumps(dump_session_status(session)), encoding="utf-8")
    transcript_path.write_text(json.dumps(dump_runtime_transcript(session)), encoding="utf-8")

    registry = build_default_registry()
    registry.register(SECRETS)
    monkeypatch.setattr(arena.games, "build_default_registry", lambda: registry)

    out = render_session_from_files(status_path, transcript_path, seat=1)
    assert "Seat 1's view" in out
    assert "I hold a 3" not in out  # seat 0's reasoning
    assert "I hold an 8" in out


# -- adversarial review of Slices 2-3 --------------------------------------


def test_the_ui_refuses_mixed_perspectives() -> None:
    session, _ = _session()
    with pytest.raises(ValueError, match="different perspectives"):
        build_match_screen(
            status_payload=dump_session_status(session),
            transcript_payload=dump_runtime_transcript(session, viewer=0),
        )
    with pytest.raises(ValueError, match="different perspectives"):
        build_match_screen(
            status_payload=dump_session_status(session, viewer=1),
            transcript_payload=dump_runtime_transcript(session, viewer=0),
        )


def test_ui_turn_events_keep_their_shape_for_public_events() -> None:
    from arena.games.connect4 import Connect4Config, DropDisc
    from arena.ui import build_match_transcript

    connect4 = build_default_registry().get("connect4")
    arena = Arena()
    session = arena.start_session(
        arena.create_session(
            connect4,
            Connect4Config(),
            [PlayerRecord(player_id="p0", seat=0), PlayerRecord(player_id="p1", seat=1)],
            {},
        )
    )
    session = dataclasses.replace(
        session, local_match=apply_match_action(session.local_match, 0, DropDisc(column=0))
    )
    ui = build_match_transcript(dump_runtime_transcript(session))
    for event in ui["turns"][0]["events"]:
        assert "is_public" not in event and "audience" not in event


def test_the_cli_redacts_a_full_status_beside_a_seat_transcript(tmp_path, monkeypatch) -> None:
    import arena.games
    from arena.cli.app import render_session_from_files

    session, match = _session()
    (tmp_path / "s.json").write_text(json.dumps(dump_session_status(session)), "utf-8")
    (tmp_path / "t.json").write_text(
        json.dumps(dump_runtime_transcript(session, viewer=0)), "utf-8"
    )
    registry = build_default_registry()
    registry.register(SECRETS)
    monkeypatch.setattr(arena.games, "build_default_registry", lambda: registry)

    out = render_session_from_files(tmp_path / "s.json", tmp_path / "t.json", seat=0)
    assert '"secrets"' not in out and "'secrets'" not in out


@pytest.mark.parametrize("seat", ["5", "-1", "x"])
def test_cli_rejects_bad_seats_with_a_usage_error(seat: str, capsys) -> None:
    from arena.cli.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["--status", "s", "--transcript", "t", "--seat", seat])
    assert exc.value.code == 2
    assert "--seat" in capsys.readouterr().err


def test_transcript_views_validate_the_viewer() -> None:
    session, _ = _session()
    with pytest.raises(ValueError):
        dump_runtime_transcript(session, viewer=7)
