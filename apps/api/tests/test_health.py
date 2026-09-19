import asyncio

import httpx

from ark_api.main import app


def test_health():
    async def fetch_health():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/health")

    response = asyncio.run(fetch_health())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ark-api"}
