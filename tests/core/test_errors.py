import pytest

from raven.core.errors import (
    AppError,
    AuthError,
    ChannelError,
    ConfigError,
    ErrorCode,
    LLMError,
    classify_error,
)


class TestAppError:
    def test_default_message(self):
        err = AppError(ErrorCode.CONFIG_MISSING)
        assert err.message == "config.missing"

    def test_custom_message(self):
        err = AppError(ErrorCode.AUTH_DENIED, "Custom message")
        assert str(err) == "Custom message"
        assert err.message == "Custom message"

    def test_detail_and_retryable(self):
        err = AppError(ErrorCode.LLM_ERROR, detail={"model": "gpt-4"}, retryable=True)
        assert err.detail == {"model": "gpt-4"}
        assert err.retryable is True

    def test_to_dict(self):
        err = AppError(ErrorCode.RATE_LIMITED, "Too fast", retryable=True)
        d = err.to_dict()
        assert d["code"] == "rate.limited"
        assert d["message"] == "Too fast"
        assert d["retryable"] is True

    def test_is_exception(self):
        with pytest.raises(AppError):
            raise AppError(ErrorCode.INTERNAL)


class TestConfigError:
    def test_message_format(self):
        err = ConfigError("MY_KEY")
        assert "MY_KEY" in err.message
        assert err.code == ErrorCode.CONFIG_MISSING
        assert err.detail == {"key": "MY_KEY"}


class TestAuthError:
    def test_default_message(self):
        err = AuthError()
        assert err.message == "Access denied"
        assert err.code == ErrorCode.AUTH_DENIED

    def test_custom_message(self):
        err = AuthError("Not allowed", {"user": "test"})
        assert err.message == "Not allowed"
        assert err.detail == {"user": "test"}


class TestLLMError:
    def test_defaults(self):
        err = LLMError()
        assert err.code == ErrorCode.LLM_ERROR
        assert err.retryable is True

    def test_not_retryable(self):
        err = LLMError("Bad request", retryable=False)
        assert err.retryable is False


class TestChannelError:
    def test_message(self):
        err = ChannelError("telegram")
        assert "telegram" in err.message
        assert err.detail == {"channel": "telegram"}

    def test_custom_message(self):
        err = ChannelError("discord", "Custom")
        assert err.message == "Custom"


class TestClassifyError:
    def test_already_app_error(self):
        err = AppError(ErrorCode.INTERNAL)
        assert classify_error(err) is err

    def test_timeout(self):
        err = classify_error(TimeoutError("Connection timeout"))
        assert err.code == ErrorCode.TIMEOUT
        assert err.retryable is True

    def test_rate_limit(self):
        err = classify_error(Exception("rate limit exceeded"))
        assert err.code == ErrorCode.RATE_LIMITED
        assert err.retryable is True

    def test_rate_limit_429(self):
        err = classify_error(Exception("HTTP 429 Too Many Requests"))
        assert err.code == ErrorCode.RATE_LIMITED

    def test_not_found(self):
        err = classify_error(Exception("resource not found"))
        assert err.code == ErrorCode.NOT_FOUND

    def test_auth_denied(self):
        err = classify_error(Exception("Unauthorized"))
        assert err.code == ErrorCode.AUTH_DENIED

    def test_connection_refused(self):
        err = classify_error(ConnectionRefusedError("connection refused"))
        assert err.code == ErrorCode.UPSTREAM_ERROR
        assert err.retryable is True

    def test_generic_internal(self):
        err = classify_error(ValueError("something broke"))
        assert err.code == ErrorCode.INTERNAL
