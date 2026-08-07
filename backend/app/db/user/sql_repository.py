from datetime import datetime
from typing import Callable, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import UserProfileORM
from app.db.user.base import BaseUserRepository, UserCredentialRecord
from app.models.user_schemas import UserProfile


def _orm_to_schema(orm: UserProfileORM) -> UserProfile:
    return UserProfile(
        user_id=orm.user_id,
        username=orm.username,
        is_active=orm.is_active,
        last_login_at=orm.last_login_at,
        display_name=orm.display_name,
        identity=orm.identity,
        education=orm.education,
        major=orm.major,
        job_role=orm.job_role,
        experience_years=orm.experience_years,
        metadata=orm.extra_metadata or {},
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _schema_to_orm(profile: UserProfile) -> UserProfileORM:
    return UserProfileORM(
        user_id=profile.user_id,
        username=profile.username,
        is_active=profile.is_active,
        last_login_at=profile.last_login_at,
        display_name=profile.display_name,
        identity=profile.identity,
        education=profile.education,
        major=profile.major,
        job_role=profile.job_role,
        experience_years=profile.experience_years,
        extra_metadata=profile.metadata,
    )


class SQLUserRepository(BaseUserRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, user_id: str) -> Optional[UserProfile]:
        with self.session_factory() as db:
            orm = db.query(UserProfileORM).filter_by(user_id=user_id).first()
        return _orm_to_schema(orm) if orm else None

    def save(self, profile: UserProfile) -> None:
        with self.session_factory() as db:
            orm = db.query(UserProfileORM).filter_by(user_id=profile.user_id).first()
            if orm is None:
                db.add(_schema_to_orm(profile))
            else:
                orm.username = profile.username
                orm.is_active = profile.is_active
                orm.last_login_at = profile.last_login_at
                orm.display_name = profile.display_name
                orm.identity = profile.identity
                orm.education = profile.education
                orm.major = profile.major
                orm.job_role = profile.job_role
                orm.experience_years = profile.experience_years
                orm.extra_metadata = profile.metadata
            db.commit()

    def list_all(self) -> Dict[str, UserProfile]:
        with self.session_factory() as db:
            rows = db.query(UserProfileORM).order_by(UserProfileORM.user_id).all()
        return {row.user_id: _orm_to_schema(row) for row in rows}

    def update_partial(self, user_id: str, updates: dict) -> Optional[UserProfile]:
        profile = self.get(user_id)
        if profile is None:
            return None
        updated = profile.model_copy(update=updates)
        self.save(updated)
        return updated

    def get_by_username(self, username: str) -> Optional[UserCredentialRecord]:
        with self.session_factory() as db:
            orm = db.query(UserProfileORM).filter_by(username=username).first()
            if orm is None:
                return None
            return UserCredentialRecord(profile=_orm_to_schema(orm), password_hash=orm.password_hash)

    def create_with_credentials(self, profile: UserProfile, password_hash: str) -> bool:
        with self.session_factory() as db:
            orm = _schema_to_orm(profile)
            orm.password_hash = password_hash
            db.add(orm)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
        return True

    def mark_last_login(self, user_id: str, occurred_at: datetime) -> Optional[UserProfile]:
        with self.session_factory() as db:
            orm = db.query(UserProfileORM).filter_by(user_id=user_id).first()
            if orm is None:
                return None
            orm.last_login_at = occurred_at
            db.commit()
            db.refresh(orm)
            return _orm_to_schema(orm)
