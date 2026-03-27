# tests/test_models/test_registry.py
import pytest
from app.models.registry import ModelRegistry
from app.db.models import ModelVersion


def test_register_creates_inactive_model(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    mv = db.query(ModelVersion).first()
    assert mv.name == "my_model"
    assert mv.version == "1.0"
    assert mv.active is False


def test_activate_sets_active_flag(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    registry.activate("my_model", "1.0")
    mv = db.query(ModelVersion).first()
    assert mv.active is True


def test_deactivate_clears_active_flag(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First version")
    registry.activate("my_model", "1.0")
    registry.deactivate("my_model", "1.0")
    mv = db.query(ModelVersion).first()
    assert mv.active is False


def test_get_active_models_returns_only_active(db):
    registry = ModelRegistry(db)
    registry.register("model_a", "1.0", "active")
    registry.register("model_b", "1.0", "inactive")
    registry.activate("model_a", "1.0")
    active = registry.get_active()
    assert len(active) == 1
    assert active[0].name == "model_a"


def test_register_duplicate_raises(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "First")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("my_model", "1.0", "Duplicate")


def test_multiple_versions_can_be_active_simultaneously(db):
    registry = ModelRegistry(db)
    registry.register("my_model", "1.0", "v1")
    registry.register("my_model", "2.0", "v2")
    registry.activate("my_model", "1.0")
    registry.activate("my_model", "2.0")
    active = registry.get_active()
    assert len(active) == 2
