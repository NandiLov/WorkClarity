
from pathlib import Path

from fastapi import APIRouter

from backend.app.schemas.shift import ShiftCalculationRequest
from backend.app.services.shift_calculations import (
    calculate_shifts,
    load_flag_messages,
    load_known_locations,
    load_rules,
)


router = APIRouter(
    prefix="/shifts",
    tags=["Shifts"],
)

# Locate the backend configuration directory independently
# of the directory from which the application is started.
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Load trusted, server-controlled configuration.
PAY_RULES = load_rules(CONFIG_DIR / "pay_rules.csv")
KNOWN_LOCATIONS = load_known_locations(CONFIG_DIR / "locations.csv")
FLAG_MESSAGES = load_flag_messages()


@router.post("/calculate")
async def calculate_shift_endpoint(request: ShiftCalculationRequest):
    """Validate submitted shifts and calculate weekly gross earnings."""

    payload = request.model_dump(
        exclude={"include_unconfirmed"}
    )

    result = calculate_shifts(
        payload,
        flag_messages=FLAG_MESSAGES,
        known_locations=KNOWN_LOCATIONS,
        include_unconfirmed=request.include_unconfirmed,
        rules=PAY_RULES,
    )

    return result
