from __future__ import annotations


import pytest

from raven.channels.base import BaseChannel


class TestBaseChannel:
    def test_abstract_methods(self):
        methods = ["connect", "disconnect", "send", "on_message", "start", "stop"]
        for m in methods:
            assert hasattr(BaseChannel, m), f"Missing method: {m}"

    def test_channel_id_not_set(self):
        with pytest.raises(TypeError):
            BaseChannel()  # type: ignore[abstract]
