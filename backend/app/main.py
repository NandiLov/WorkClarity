from fastapi import FastAPI

from backend.app.api.shifts import router as shifts_router


app = FastAPI(
    title="WorkClarity API",
    description="Backend API for managing work schedules, shift validation, and earnings estimates.",
    version="0.1.0",
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
