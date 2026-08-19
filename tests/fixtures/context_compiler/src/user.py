"""User service module."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """User entity."""
    id: str
    username: str
    email: str
    password_hash: str
    is_active: bool = True


class UserService:
    """Service for managing users."""

    def __init__(self):
        self._users: dict[str, User] = {}

    def create_user(self, username: str, email: str, password: str) -> User:
        """Create a new user."""
        from sacas.fixtures.context_compiler.src.auth import hash_password
        user = User(
            id=f"user_{len(self._users) + 1}",
            username=username,
            email=email,
            password_hash=hash_password(password)
        )
        self._users[username] = user
        return user

    def get_user(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self._users.get(username)

    def update_email(self, username: str, new_email: str) -> bool:
        """Update user's email."""
        user = self._users.get(username)
        if user:
            user.email = new_email
            return True
        return False

    def deactivate(self, username: str) -> bool:
        """Deactivate a user."""
        user = self._users.get(username)
        if user:
            user.is_active = False
            return True
        return False

    def list_active_users(self) -> list[User]:
        """List all active users."""
        return [u for u in self._users.values() if u.is_active]