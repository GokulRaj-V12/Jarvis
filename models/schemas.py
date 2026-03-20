from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DailyLog(BaseModel):
    user_id: int
    date: str  # YYYY-MM-DD
    content: str
    mood: Optional[str] = None
    blockers: Optional[str] = None
    created_at: Optional[str] = None


class Goal(BaseModel):
    user_id: int
    title: str
    description: Optional[str] = ""
    status: str = "active"  # active, completed, paused
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UserProfile(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    timezone: str = "Asia/Kolkata"
    created_at: Optional[str] = None


class PersonalityProfile(BaseModel):
    user_id: int
    motivation_style: str = ""
    thinking_style: str = ""
    weakness_patterns: str = ""
    energy_cycles: str = ""
    work_habits: str = ""
    summary: str = ""
    updated_at: Optional[str] = None


class PlanRequest(BaseModel):
    user_id: int


class ReviewRequest(BaseModel):
    user_id: int


class PersonalityUpdateRequest(BaseModel):
    user_id: int
