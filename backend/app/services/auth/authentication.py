from datetime import datetime, timezone
import uuid

from app.core.security.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.users.base import BaseUserRepository
from app.models.auth.authentication import RegisterRequest
from app.models.users.users import UserProfile


class UsernameAlreadyExistsError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    pass


class InactiveUserError(ValueError):
    pass


class AuthService:
    def __init__(self, repo: BaseUserRepository):
        self.repo = repo

    def register(self, payload: RegisterRequest) -> UserProfile:
        if self.repo.get_by_username(payload.username) is not None:
            raise UsernameAlreadyExistsError(payload.username)

        profile = UserProfile(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            username=payload.username,
            display_name=payload.username,
            identity=payload.identity or "其他",
            education=payload.education or "未填写",
            major=payload.major or "未填写",
            job_role=payload.job_role,
            experience_years=payload.experience_years,
            metadata={},
            is_active=True,
        )
        if not self.repo.create_with_credentials(profile, hash_password(payload.password)):
            raise UsernameAlreadyExistsError(payload.username)
        return profile

    def authenticate(self, username: str, password: str) -> UserProfile:
        record = self.repo.get_by_username(username)
        if record is None or not record.password_hash or not verify_password(password, record.password_hash):
            raise InvalidCredentialsError(username)
        if not record.profile.is_active:
            raise InactiveUserError(username)
        return self.repo.mark_last_login(record.profile.user_id, datetime.now(timezone.utc)) or record.profile

    def create_token(self, user_id: str) -> str:
        return create_access_token(user_id)

    def resolve_token(self, token: str) -> UserProfile | None:
        user_id = decode_access_token(token)
        if not user_id:
            return None
        profile = self.repo.get(user_id)
        if profile is None or not profile.is_active:
            return None
        return profile
