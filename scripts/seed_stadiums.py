"""One-time script to seed stadium_profiles from data/stadium_profiles.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.db.connection import get_engine
from app.db.models import StadiumProfile, Team


def seed():
    data = json.loads((Path(__file__).parent.parent / "data" / "stadium_profiles.json").read_text())
    engine = get_engine()
    with Session(engine) as session:
        for item in data:
            existing = session.query(StadiumProfile).filter_by(name=item["name"]).first()
            if existing:
                continue
            team = session.query(Team).filter(
                Team.name.ilike(f"%{item['team']}%")
            ).first()
            sp = StadiumProfile(
                name=item["name"],
                team_id=team.id if team else None,
                enclosure_rating=item["enclosure_rating"],
                latitude=item["latitude"],
                longitude=item["longitude"],
            )
            session.add(sp)
        session.commit()
        print(f"Seeded {len(data)} stadium profiles")


if __name__ == "__main__":
    seed()
