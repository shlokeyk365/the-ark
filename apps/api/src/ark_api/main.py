"""HTTP entry point. Run with uvicorn ark_api.main:app."""

from fastapi import FastAPI

app = FastAPI(title="Ark API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ark-api"}
