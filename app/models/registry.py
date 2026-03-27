from datetime import datetime, timezone
from app.db.models import ModelVersion


class ModelRegistry:
    def __init__(self, session):
        self.session = session

    def register(self, name: str, version: str, description: str = "") -> ModelVersion:
        existing = self.session.query(ModelVersion).filter_by(name=name, version=version).first()
        if existing:
            raise ValueError(f"Model {name}@{version} already registered")
        mv = ModelVersion(name=name, version=version, description=description,
                          active=False, created_at=datetime.now(timezone.utc))
        self.session.add(mv)
        self.session.commit()
        return mv

    def activate(self, name: str, version: str):
        mv = self._get_or_raise(name, version)
        mv.active = True
        self.session.commit()

    def deactivate(self, name: str, version: str):
        mv = self._get_or_raise(name, version)
        mv.active = False
        self.session.commit()

    def get_active(self) -> list[ModelVersion]:
        return self.session.query(ModelVersion).filter_by(active=True).all()

    def list_all(self) -> list[ModelVersion]:
        return self.session.query(ModelVersion).order_by(ModelVersion.created_at).all()

    def _get_or_raise(self, name: str, version: str) -> ModelVersion:
        mv = self.session.query(ModelVersion).filter_by(name=name, version=version).first()
        if not mv:
            raise ValueError(f"Model {name}@{version} not found")
        return mv
