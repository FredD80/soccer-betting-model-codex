from app.db.models import (
    LineMovement, PlayerImpact, DrawPropensity,
    ManagerProfile, RefereeProfile, TacticalProfile,
    StadiumProfile, RotationFlag
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.models import Base
import pytest


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_line_movement_columns(session):
    from datetime import datetime
    lm = LineMovement(
        fixture_id=1, book="pinnacle", market="spread",
        line=-0.5, odds=-110, recorded_at=datetime.utcnow()
    )
    session.add(lm)
    session.commit()
    assert session.query(LineMovement).count() == 1


def test_referee_profile_columns(session):
    rp = RefereeProfile(name="Mike Dean", league="eng.1",
                        fouls_per_tackle=0.42, penalty_rate=0.08, cards_per_game=3.1)
    session.add(rp)
    session.commit()
    assert rp.id is not None


def test_stadium_profile_enclosure(session):
    sp = StadiumProfile(name="Tottenham Hotspur Stadium",
                        team_id=None, enclosure_rating="Closed",
                        latitude=51.604, longitude=-0.066)
    session.add(sp)
    session.commit()
    assert sp.enclosure_rating == "Closed"


def test_tactical_profile_ppda(session):
    tp = TacticalProfile(team_id=1, season="2025-26",
                         archetype="High Press", ppda=8.3, press_resistance=62.1)
    session.add(tp)
    session.commit()
    assert tp.ppda == pytest.approx(8.3)


def test_rotation_flag_columns(session):
    rf = RotationFlag(fixture_id=1, team_id=1,
                      rotation_probability=0.72, ucl_fixture_id=99)
    session.add(rf)
    session.commit()
    assert rf.rotation_probability == pytest.approx(0.72)
