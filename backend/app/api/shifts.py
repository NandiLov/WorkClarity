from fastapi import APIRouter
#keeps shift-related endpoints separate from the main application.
from backend.app.schemas.shift import ShiftCalculationRequest
#ShiftCalculationRequest validates the incoming request.
from backend.app.services.shift_calculations import calculate_shifts


router = APIRouter(
    prefix="/shifts",
    tags=["Shifts"],
)


@router.post("/calculate")
async def calculate_shift_endpoint(request: ShiftCalculationRequest):
    """Validate submitted shifts and calculate weekly gross earnings."""

    payload = request.model_dump(
        exclude={"include_unconfirmed"}
    ) #model_dump() converts the validated request into a Python dictionary.

    result = calculate_shifts(
        payload,
        include_unconfirmed=request.include_unconfirmed,
    ) #delegates the actual calculations to Ololade's service.

    return result
#http://127.0.0.1:8000/api/v1/shifts/calculate