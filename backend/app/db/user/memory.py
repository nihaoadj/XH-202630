from typing import Dict, Optional

from app.db.user.base import BaseUserRepository
from app.models.user_schemas import UserProfile


class MemoryUserRepository(BaseUserRepository):
    def __init__(self):
        self._store: Dict[str, UserProfile] = {}

    def get(self, user_id: str) -> Optional[UserProfile]:
        return self._store.get(user_id)

    def save(self, profile: UserProfile) -> None:
        self._store[profile.user_id] = profile

    def list_all(self) -> Dict[str, UserProfile]:
        return self._store.copy()

    def update_partial(self, user_id: str, updates: dict) -> Optional[UserProfile]:
        profile = self.get(user_id)
        if profile is None:
            return None
        updated = profile.model_copy(update=updates)
        self.save(updated)
        return updated
