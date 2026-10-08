from datetime import datetime
from typing import Dict, Optional

from app.db.users.base import BaseUserRepository, UserCredentialRecord
from app.models.users.users import UserProfile


class MemoryUserRepository(BaseUserRepository):
    def __init__(self):
        self._store: Dict[str, UserProfile] = {}
        self._password_hashes: Dict[str, str] = {}

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

    def get_by_username(self, username: str) -> Optional[UserCredentialRecord]:
        profile = next((item for item in self._store.values() if item.username == username), None)
        if profile is None:
            return None
        return UserCredentialRecord(profile=profile, password_hash=self._password_hashes.get(profile.user_id))

    def create_with_credentials(self, profile: UserProfile, password_hash: str) -> bool:
        if self.get_by_username(profile.username or "") is not None:
            return False
        self._store[profile.user_id] = profile
        self._password_hashes[profile.user_id] = password_hash
        return True

    def mark_last_login(self, user_id: str, occurred_at: datetime) -> Optional[UserProfile]:
        profile = self.get(user_id)
        if profile is None:
            return None
        updated = profile.model_copy(update={"last_login_at": occurred_at})
        self.save(updated)
        return updated
