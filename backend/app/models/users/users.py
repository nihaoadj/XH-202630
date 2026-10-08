from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    user_id: str
    username: Optional[str] = None
    is_active: bool = True
    last_login_at: Optional[datetime] = None
    display_name: str
    identity: str
    education: str
    major: str
    job_role: Optional[str] = None
    experience_years: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserProfileCreate(BaseModel):
    display_name: str
    identity: str
    education: str
    major: str
    job_role: Optional[str] = None
    experience_years: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    identity: Optional[str] = None
    education: Optional[str] = None
    major: Optional[str] = None
    job_role: Optional[str] = None
    experience_years: Optional[int] = Field(default=None, ge=0)
    metadata: Optional[Dict[str, Any]] = None
