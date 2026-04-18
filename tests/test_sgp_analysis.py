from datetime import datetime, timezone
import importlib

from click.testing import CliRunner

from app.sgp_analysis import BullySgpReplayRow, summarize_sgp_bands, summarize_sgp_thresholds


def _row(*, fixture_id: int, sgp_lens: float, favorite_win: bool, sgp_hit: bool) -> BullySgpReplayRow:
    return BullySgpReplayRow(
        fixture_id=fixture_id,
        kickoff_at=datetime(2026, 4, fixture_id, tzinfo=timezone.utc),
        favorite_team=f"Fav {fixture_id}",
        underdog_team=f"Dog {fixture_id}",
        favorite_side="home",
        favorite_probability=0.7,
        favorite_two_plus_probability=sgp_lens / 0.7,
        sgp_lens=sgp_lens,
        favorite_win=favorite_win,
        sgp_hit=sgp_hit,
        favorite_goals=2 if sgp_hit else 1,
        underdog_goals=0,
        favorite_expected_goals=2.1,
        expected_goals_delta=1.4,
        elo_gap=160.0,
    )


def test_summarize_sgp_bands_and_thresholds():
    rows = [
        _row(fixture_id=1, sgp_lens=0.42, favorite_win=True, sgp_hit=True),
        _row(fixture_id=2, sgp_lens=0.43, favorite_win=True, sgp_hit=False),
        _row(fixture_id=3, sgp_lens=0.47, favorite_win=False, sgp_hit=False),
        _row(fixture_id=4, sgp_lens=0.56, favorite_win=True, sgp_hit=True),
    ]

    band_summaries = summarize_sgp_bands(rows, bands=((0.40, 0.45), (0.45, 0.50), (0.55, 0.60)))
    assert [(summary.low, summary.high, summary.total) for summary in band_summaries] == [
        (0.40, 0.45, 2),
        (0.45, 0.50, 1),
        (0.55, 0.60, 1),
    ]
    assert band_summaries[0].win_rate == 1.0
    assert band_summaries[0].sgp_hit_rate == 0.5
    assert band_summaries[1].win_rate == 0.0
    assert band_summaries[2].sgp_hit_rate == 1.0

    threshold_summaries = summarize_sgp_thresholds(rows, thresholds=(0.40, 0.45, 0.50, 0.60))
    assert [(summary.threshold, summary.total) for summary in threshold_summaries] == [
        (0.40, 4),
        (0.45, 2),
        (0.50, 1),
        (0.60, 0),
    ]
    assert threshold_summaries[0].win_rate == 0.75
    assert threshold_summaries[0].sgp_hit_rate == 0.5
    assert threshold_summaries[1].win_rate == 0.5
    assert threshold_summaries[2].sgp_hit_rate == 1.0
    assert threshold_summaries[3].win_rate is None


def test_cli_analyze_bully_sgp_uses_end_of_day(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ODDS_API_KEY", "testkey")

    import cli as cli_module

    cli_module = importlib.reload(cli_module)

    captured: dict[str, datetime] = {}

    class DummySession:
        def close(self):
            return None

    def fake_get_session():
        return DummySession()

    def fake_replay(session, *, date_from, date_to, limit, max_checked, enable_understat_fetch):
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        assert limit == 5
        assert max_checked == 20
        assert enable_understat_fetch is False
        return [
            _row(fixture_id=1, sgp_lens=0.42, favorite_win=True, sgp_hit=True),
            _row(fixture_id=2, sgp_lens=0.47, favorite_win=False, sgp_hit=False),
        ]

    monkeypatch.setattr(cli_module, "get_session", fake_get_session)
    monkeypatch.setattr("app.sgp_analysis.replay_bully_sgp_rows", fake_replay)

    result = CliRunner().invoke(
        cli_module.cli,
        [
            "analyze-bully-sgp",
            "--from-date",
            "2026-04-01",
            "--to-date",
            "2026-04-17",
            "--limit",
            "5",
            "--max-checked",
            "20",
        ],
    )

    assert result.exit_code == 0
    assert captured["date_from"] == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert captured["date_to"] == datetime(2026, 4, 17, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert "Replayed 2 bully spots" in result.output
    assert "Bands" in result.output
    assert "Thresholds" in result.output
