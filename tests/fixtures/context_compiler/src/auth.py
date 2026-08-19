"""Authentication service module."""

class AuthService:
    """Service for handling authentication."""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._sessions = {}

    def validate_token(self, token: str) -> bool:
        """Validate an authentication token."""
        if not token:
            return False
        return token in self._sessions

    def refresh_token(self, old_token: str) -> str | None:
        """Refresh an expired token."""
        if old_token not in self._sessions:
            return None
        new_token = self._generate_token()
        self._sessions[new_token] = self._sessions.pop(old_token)
        return new_token

    def _generate_token(self) -> str:
        """Generate a new secure token."""
        import secrets
        return secrets.token_urlsafe(32)

    def login(self, username: str, password: str) -> str | None:
        """Authenticate user and return token."""
        if username == "admin" and password == "secret":
            token = self._generate_token()
            self._sessions[token] = {"user": username}
            return token
        return None

    def logout(self, token: str) -> bool:
        """Invalidate a token."""
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()