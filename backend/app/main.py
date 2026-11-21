import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.shifts import router as shifts_router

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def get_cors_origins() -> list[str]:
    """Retrieve explicit CORS allowed origins from environment.

    Rejects wildcard '*' to enforce strict explicit origin allowlisting.
    """
    raw = os.environ.get("WORKCLARITY_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    origins = [orig.strip() for orig in raw.split(",") if orig.strip()]
    filtered = [orig for orig in origins if orig != "*"]
    return filtered or list(DEFAULT_CORS_ORIGINS)


app = FastAPI(
    title="WorkClarity API",
    description="Backend API for managing work schedules, shift validation, and earnings estimates.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check():
    """Check whether the WorkClarity API is running."""
    return {
        "status": "healthy",
        "service": "WorkClarity API",
        "version": "0.1.0",
    }


app.include_router(shifts_router, prefix="/api/v1")
