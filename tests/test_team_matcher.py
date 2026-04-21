from app.db.models import League, Team, TeamAlias
from app.team_matcher import resolve_team


def _lg(db):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg); db.flush()
    return lg


def test_exact_match(db):
    lg = _lg(db)
    t = Team(name="Manchester United", league_id=lg.id)
    db.add(t); db.flush()
    assert resolve_team(db, lg.id, "Manchester United", "odds_api").id == t.id


def test_fuzzy_match_creates_alias(db):
    lg = _lg(db)
    t = Team(name="Manchester United", league_id=lg.id)
    db.add(t); db.flush()
    out = resolve_team(db, lg.id, "Man Utd", "odds_api")
    # "Man Utd" -> "Manchester United" is below 0.85 — rightly rejected
    assert out is None


def test_fuzzy_close_match(db):
    lg = _lg(db)
    t = Team(name="Manchester United FC", league_id=lg.id)
    db.add(t); db.flush()
    out = resolve_team(db, lg.id, "Manchester United", "odds_api")
    assert out is not None
    assert out.id == t.id
    aliases = db.query(TeamAlias).filter_by(team_id=t.id).all()
    assert len(aliases) == 1


def test_normalized_exact_match_creates_alias(db):
    lg = _lg(db)
    t = Team(name="AS Monaco", league_id=lg.id)
    db.add(t); db.flush()

    out = resolve_team(db, lg.id, "Monaco", "oddalerts")

    assert out is not None
    assert out.id == t.id
    aliases = db.query(TeamAlias).filter_by(team_id=t.id, source="oddalerts").all()
    assert len(aliases) == 1
    assert aliases[0].alias == "Monaco"


def test_collapsed_name_match_creates_alias(db):
    lg = _lg(db)
    t = Team(name="Lyon", league_id=lg.id)
    db.add(t); db.flush()

    out = resolve_team(db, lg.id, "Olympique Lyonnais", "oddalerts")

    assert out is not None
    assert out.id == t.id
    aliases = db.query(TeamAlias).filter_by(team_id=t.id, source="oddalerts").all()
    assert len(aliases) == 1
    assert aliases[0].alias == "Olympique Lyonnais"


def test_normalized_fuzzy_match_creates_alias(db):
    lg = _lg(db)
    t = Team(name="Stade Rennais", league_id=lg.id)
    db.add(t); db.flush()

    out = resolve_team(db, lg.id, "Rennes", "oddalerts")

    assert out is not None
    assert out.id == t.id
    aliases = db.query(TeamAlias).filter_by(team_id=t.id, source="oddalerts").all()
    assert len(aliases) == 1
    assert aliases[0].alias == "Rennes"


def test_translated_name_match_creates_alias(db):
    lg = _lg(db)
    t = Team(name="FC Cologne", league_id=lg.id)
    db.add(t); db.flush()

    out = resolve_team(db, lg.id, "FC Köln", "oddalerts")

    assert out is not None
    assert out.id == t.id
    aliases = db.query(TeamAlias).filter_by(team_id=t.id, source="oddalerts").all()
    assert len(aliases) == 1
    assert aliases[0].alias == "FC Köln"


def test_alias_hit_short_circuits_fuzzy(db):
    lg = _lg(db)
    t = Team(name="Manchester United", league_id=lg.id)
    db.add(t); db.flush()
    db.add(TeamAlias(team_id=t.id, alias="Man Utd", source="odds_api"))
    db.flush()
    assert resolve_team(db, lg.id, "Man Utd", "odds_api").id == t.id


def test_alias_source_scoped(db):
    lg = _lg(db)
    t = Team(name="Manchester United", league_id=lg.id)
    db.add(t); db.flush()
    db.add(TeamAlias(team_id=t.id, alias="Man Utd", source="espn"))
    db.flush()
    # different source, and Man Utd is too distant for fuzzy → None
    assert resolve_team(db, lg.id, "Man Utd", "odds_api") is None


def test_no_match_returns_none(db):
    lg = _lg(db)
    t = Team(name="Arsenal", league_id=lg.id)
    db.add(t); db.flush()
    assert resolve_team(db, lg.id, "Totally Different FC", "odds_api") is None


def test_league_scoped(db):
    lg1 = _lg(db)
    lg2 = League(name="La Liga", country="Spain", espn_id="esp.1", odds_api_key="x")
    db.add(lg2); db.flush()
    t = Team(name="Arsenal", league_id=lg1.id)
    db.add(t); db.flush()
    assert resolve_team(db, lg2.id, "Arsenal", "odds_api") is None
