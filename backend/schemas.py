"""Pydantic request/response models for the API."""
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class PropertyUpdate(BaseModel):
    notes: Optional[str] = None
    flag_status: Optional[str] = None
    rehab_estimate_user_input: Optional[float] = None
    owner_name: Optional[str] = None
    occupancy_status: Optional[str] = None


class WeightUpdate(BaseModel):
    key: str
    weight: float


class WeightsUpdateRequest(BaseModel):
    weights: Dict[str, float]
