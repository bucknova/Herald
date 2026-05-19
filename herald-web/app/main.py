"""
main.py — FastAPI entry point for Herald Web.

Phase 0 scaffold: serves a single placeholder route so we can verify the
container builds and runs alongside the bot. Real routes (auth, dashboard,
schedule, etc.) land in Phase 1.
"""

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI(
    title="Herald Web",
    description="Web companion portal to the Herald Discord bot.",
    version="0.0.1",
)


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    return "Herald Web"


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    """Liveness probe for the reverse proxy / Docker healthcheck."""
    return "ok"
