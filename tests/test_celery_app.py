def test_celery_app_imports():
    from app.celery_app import celery_app
    assert celery_app.main == "app"


def test_task_names_registered():
    from app.celery_app import celery_app
    registered = set(celery_app.tasks.keys())
    assert "app.celery_app.form_cache_task" in registered
    assert "app.celery_app.spread_predict_task" in registered
    assert "app.celery_app.ou_analyze_task" in registered
