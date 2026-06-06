from raven.core.auth.tokens import TokenManager


class TestTokenManager:
    def setup_method(self):
        self.mgr = TokenManager()

    def test_create_and_validate(self):
        token = self.mgr.create_token("user1", "admin")
        data = self.mgr.validate_token(token)
        assert data is not None
        assert data["user_id"] == "user1"
        assert data["role"] == "admin"

    def test_validate_invalid_token(self):
        assert self.mgr.validate_token("nonexistent") is None

    def test_validate_expired_token(self):
        token = self.mgr.create_token("user1", "user", ttl_seconds=0)
        assert self.mgr.validate_token(token) is None

    def test_revoke_token(self):
        token = self.mgr.create_token("user1", "user")
        self.mgr.revoke_token(token)
        assert self.mgr.validate_token(token) is None

    def test_revoke_nonexistent(self):
        self.mgr.revoke_token("does_not_exist")

    def test_revoke_user_tokens(self):
        t1 = self.mgr.create_token("user1", "user")
        t2 = self.mgr.create_token("user1", "user")
        self.mgr.create_token("user2", "user")
        self.mgr.revoke_user_tokens("user1")
        assert self.mgr.validate_token(t1) is None
        assert self.mgr.validate_token(t2) is None
        assert self.mgr.count() == 1

    def test_count(self):
        assert self.mgr.count() == 0
        self.mgr.create_token("a", "user")
        assert self.mgr.count() == 1

    def test_clean_expired(self):
        self.mgr.create_token("a", "user", ttl_seconds=100)
        self.mgr.create_token("b", "user", ttl_seconds=0)
        self.mgr.clean_expired()
        assert self.mgr.count() == 1

    def test_clean_expired_none_expired(self):
        self.mgr.create_token("a", "user", ttl_seconds=9999)
        self.mgr.clean_expired()
        assert self.mgr.count() == 1
