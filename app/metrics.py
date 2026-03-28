import threading
from prometheus_client import start_http_server, Gauge, Counter
from app.db.connection import get_session
from app.db.models import Performance

model_accuracy = Gauge("betting_model_accuracy", "Prediction accuracy per model/bet_type",
                       ["model_name", "model_version", "bet_type"])
model_roi = Gauge("betting_model_roi", "Average ROI per model/bet_type",
                  ["model_name", "model_version", "bet_type"])
scheduler_errors = Counter("scheduler_job_errors_total", "Scheduler job error count", ["job_name"])


def update_metrics():
    session = get_session()
    try:
        from app.db.models import ModelVersion
        performances = session.query(Performance).all()
        for perf in performances:
            mv = session.query(ModelVersion).filter_by(id=perf.model_id).first()
            if not mv:
                continue
            model_accuracy.labels(model_name=mv.name, model_version=mv.version,
                                   bet_type=perf.bet_type).set(perf.accuracy or 0)
            model_roi.labels(model_name=mv.name, model_version=mv.version,
                              bet_type=perf.bet_type).set(perf.roi or 0)
    finally:
        session.close()


def start_metrics_server(port: int = 9090):
    start_http_server(port)
    timer = threading.Timer(60, _refresh_loop)
    timer.daemon = True
    timer.start()


def _refresh_loop():
    update_metrics()
    timer = threading.Timer(60, _refresh_loop)
    timer.daemon = True
    timer.start()
