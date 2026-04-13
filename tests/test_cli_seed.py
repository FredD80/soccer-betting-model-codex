def test_seed_includes_ligue1_and_ucl():
    import inspect
    import cli as cli_module
    source = inspect.getsource(cli_module)
    assert "fra.1" in source
    assert "uefa.champions" in source
    assert "soccer_france_ligue_one" in source
    assert "soccer_uefa_champs_league" in source
