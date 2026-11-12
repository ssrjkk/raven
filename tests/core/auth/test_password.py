import pytest

from raven.core.auth.password import check_password_strength, hash_password, verify_password


class TestPasswordStrength:
    """One policy, one definition: /api/auth/register and `raven security promote` both read it."""

    def test_a_credential_that_meets_every_rule_passes(self) -> None:
        check_password_strength("Sup3rSecret!")  # any rule it fails raises ValueError

    @pytest.mark.parametrize(
        "weak, fragment",
        [
            ("Ab1!", "at least 8 characters"),
            ("alllower1!", "uppercase"),
            ("ALLUPPER1!", "lowercase"),
            ("NoDigits!!", "digit"),
            ("NoSpecialAb1", "special character"),
        ],
    )
    def test_each_rule_names_itself(self, weak, fragment):
        with pytest.raises(ValueError, match=fragment):
            check_password_strength(weak)

    def test_the_registration_route_refuses_what_the_function_refuses(self):
        from pydantic import ValidationError

        from raven.core.admin.models import AuthRegisterRequest

        with pytest.raises(ValidationError, match="special character"):
            AuthRegisterRequest(username="operator", password="NoSpecialAb1")
        assert AuthRegisterRequest(username="operator", password="Sup3rSecret!").password == "Sup3rSecret!"


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
