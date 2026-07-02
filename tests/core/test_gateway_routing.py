from __future__ import annotations

import pytest

from raven.gateway.routing import RoutingEngine, RouteRule


class TestRouteRule:
    def test_basic_match(self):
        rule = RouteRule(pattern="channel:telegram", agent_id="agent-1")
        assert rule.matches("telegram") is True

    def test_pattern_no_match(self):
        rule = RouteRule(pattern="channel:telegram", agent_id="agent-1")
        assert rule.matches("discord") is False

    def test_wildcard_pattern(self):
        rule = RouteRule(pattern="*", agent_id="agent-1")
        assert rule.matches("anything") is True

    def test_account_match(self):
        rule = RouteRule(pattern="account:company", agent_id="agent-1")
        assert rule.matches("telegram", account="company") is True


class TestRoutingEngine:
    def setup_method(self):
        self.engine = RoutingEngine()

    def test_empty_route_returns_default(self):
        result = self.engine.route("telegram")
        assert result == "default"

    def test_add_and_route(self):
        self.engine.add_rule("channel:telegram", "tg-agent")
        result = self.engine.route("telegram")
        assert result == "tg-agent"

    def test_fallback_for_unmatched(self):
        self.engine.add_rule("*", "fallback")
        result = self.engine.route("unknown")
        assert result == "fallback"

    def test_list_rules(self):
        self.engine.add_rule("channel:telegram", "tg-agent")
        rules = self.engine.list_rules()
        assert len(rules) >= 1
