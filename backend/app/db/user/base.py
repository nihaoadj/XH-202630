from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from app.models.user_schemas import UserProfile


@dataclass
class UserCredentialRecord:
    profile: UserProfile
    password_hash: Optional[str]


class BaseUserRepository(ABC):
    @abstractmethod
    def get(self, user_id: str) -> Optional[UserProfile]:
        pass

    @abstractmethod
    def save(self, profile: UserProfile) -> None:
        pass

    @abstractmethod
    def list_all(self) -> Dict[str, UserProfile]:
        pass

    @abstractmethod
    def update_partial(self, user_id: str, updates: dict) -> Optional[UserProfile]:
        pass

    @abstractmethod
    def get_by_username(self, username: str) -> Optional[UserCredentialRecord]:
        pass

    @abstractmethod
    def create_with_credentials(self, profile: UserProfile, password_hash: str) -> bool:
        pass

    @abstractmethod
    def mark_last_login(self, user_id: str, occurred_at: datetime) -> Optional[UserProfile]:
        pass
