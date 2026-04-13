from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Soccer Prediction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened in prod via K8s NetworkPolicy
    allow_methods=["GET"],
    allow_headers=["*"],
)

from api.routers import picks, fixtures, performance  # noqa: E402
app.include_router(picks.router, prefix="/picks", tags=["picks"])
app.include_router(fixtures.router, prefix="/fixture", tags=["fixtures"])
app.include_router(performance.router, prefix="/performance", tags=["performance"])


@app.get("/health")
def health():
    return {"status": "ok"}
