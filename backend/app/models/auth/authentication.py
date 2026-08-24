from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.users.users import UserProfile


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    identity: Optional[str] = Field(default=None, max_length=64)
    education: Optional[str] = Field(default=None, max_length=64)
    major: Optional[str] = Field(default=None, max_length=128)
    job_role: Optional[str] = Field(default=None, max_length=128)
    experience_years: Optional[int] = Field(default=None, ge=0, le=50)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("identity", "education", "major", "job_role", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_password_confirmation(self):
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return str(value).strip().lower()


class AuthResponse(BaseModel):
    user: UserProfile


class LogoutResponse(BaseModel):
    status: str = "success"
    message: str = "已退出登录"
