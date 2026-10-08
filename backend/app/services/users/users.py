import uuid

from app.db.users.base import BaseUserRepository
from app.models.users.users import UserProfile


class UserService:
    def __init__(self, repo: BaseUserRepository):
        self.repo = repo

    def get(self, user_id: str):
        return self.repo.get(user_id)

    def save(self, profile: UserProfile):
        self.repo.save(profile)
        return profile

    def create(self, payload: dict):
        profile = UserProfile(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            **payload,
        )
        self.repo.save(profile)
        return profile

    def list_all(self):
        return list(self.repo.list_all().values())

    def update_partial(self, user_id: str, updates: dict):
        return self.repo.update_partial(user_id, updates)
