"""Tests for authentication service."""

import pytest
from sacas.fixtures.context_compiler.src.auth import AuthService, hash_password


class TestAuthService:
    def test_validate_token_empty(self):
        svc = AuthService("secret")
        assert svc.validate_token("") is False
        assert svc.validate_token(None) is False

    def test_validate_token_valid(self):
        svc = AuthService("secret")
        token = svc.login("admin", "secret")
        assert token is not None
        assert svc.validate_token(token) is True

    def test_refresh_token(self):
        svc = AuthService("secret")
        token = svc.login("admin", "secret")
        assert token is not None
        new_token = svc.refresh_token(token)
        assert new_token is not None
        assert new_token != token
        assert svc.validate_token(new_token) is True
        assert svc.validate_token(token) is False

    def test_refresh_token_invalid(self):
        svc = AuthService("secret")
        assert svc.refresh_token("invalid") is None

    def test_hash_password(self):
        h1 = hash_password("test")
        h2 = hash_password("test")
        assert h1 == h2
        assert len(h1) == 64


class TestUserService:
    def test_create_user(self):
        from sacas.fixtures.context_compiler.src.user import UserService
        svc = UserService()
        user = svc.create_user("john", "john@example.com", "password123")
        assert user.username == "john"
        assert user.email == "john@example.com"
        assert user.is_active is True

    def test_get_user(self):
        from sacas.fixtures.context_compiler.src.user import UserService
        svc = UserService()
        svc.create_user("jane", "jane@example.com", "password")
        user = svc.get_user("jane")
        assert user is not None
        assert user.username == "jane"
        assert svc.get_user("nonexistent") is None

    def test_update_email(self):
        from sacas.fixtures.context_compiler.src.user import UserService
        svc = UserService()
        svc.create_user("bob", "bob@example.com", "password")
        assert svc.update_email("bob", "bob.new@example.com") is True
        assert svc.get_user("bob").email == "bob.new@example.com"
        assert svc.update_email("nonexistent", "x@y.com") is False

    def test_deactivate(self):
        from sacas.fixtures.context_compiler.src.user import UserService
        svc = UserService()
        svc.create_user("alice", "alice@example.com", "password")
        assert svc.deactivate("alice") is True
        assert svc.get_user("alice").is_active is False
        assert svc.deactivate("nonexistent") is False
        assert svc.list_active_users() == []

    def test_list_active_users(self):
        from sacas.fixtures.context_compiler.src.user import UserService
        svc = UserService()
        svc.create_user("user1", "u1@example.com", "p1")
        svc.create_user("user2", "u2@example.com", "p2")
        svc.deactivate("user1")
        active = svc.list_active_users()
        assert len(active) == 1
        assert active[0].username == "user2"