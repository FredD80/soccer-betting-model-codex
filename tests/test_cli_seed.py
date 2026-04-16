def test_seed_includes_ligue1_and_ucl(monkeypatch):
    import inspect
    import importlib

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ODDS_API_KEY", "testkey")
    import cli as cli_module
    cli_module = importlib.reload(cli_module)
    source = inspect.getsource(cli_module)
    assert "fra.1" in source
    assert "por.1" in source
    assert "usa.1" in source
    assert "uefa.champions" in source
    assert "soccer_france_ligue_one" in source
    assert "soccer_portugal_primeira_liga" in source
    assert "soccer_usa_mls" in source
    assert "soccer_uefa_champs_league" in source
