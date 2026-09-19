"""HTTP entry point. Run with uvicorn ark_api.main:app."""

from fastapi import FastAPI

from ark_api.routes.intelligence import router as intelligence_router
from ark_api.routes.simulations import router as simulations_router

app = FastAPI(title="Ark API", version="0.1.0")
app.include_router(simulations_router)
app.include_router(intelligence_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ark-api"}
