from raven.core.auth.password import hash_password, verify_password


class TestHashPassword:
    def test_hash_is_deterministic_with_salt(self):
        h1 = hash_password("hello")
        h2 = hash_password("hello")
        assert h1 != h2
        assert ":" in h1
        assert ":" in h2

    def test_verify_correct(self):
        h = hash_password("my_password")
        assert verify_password("my_password", h) is True

    def test_verify_wrong(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_verify_empty_password(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("x", h) is False

    def test_verify_invalid_hash(self):
        assert verify_password("x", "") is False
        assert verify_password("x", "not:a:valid:hash") is False
        assert verify_password("x", "abc") is False
