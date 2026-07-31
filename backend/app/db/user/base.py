from abc import ABC, abstractmethod
from typing import Dict, Optional

from app.models.user_schemas import UserProfile


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
