from __future__ import annotations

import re
from typing import Any

from raven.core.monitor.models import Condition, ConditionOperator


class ConditionEvaluator:
    def evaluate(self, condition: Condition, data: dict[str, Any]) -> bool:
        actual = data.get(condition.metric)
        if actual is None:
            return False

        if condition.operator == ConditionOperator.EQ:
            return str(actual) == str(condition.value)
        if condition.operator == ConditionOperator.NE:
            return str(actual) != str(condition.value)
        if condition.operator == ConditionOperator.GT:
            return float(actual) > float(condition.value)
        if condition.operator == ConditionOperator.LT:
            return float(actual) < float(condition.value)
        if condition.operator == ConditionOperator.CONTAINS:
            return str(condition.value) in str(actual)
        if condition.operator == ConditionOperator.MATCHES:
            return bool(re.search(str(condition.value), str(actual)))
        if condition.operator == ConditionOperator.CHANGED:
            return bool(data.get("changed", False))
        return False

    def check_all(self, conditions: list[Condition], data: dict[str, Any]) -> bool:
        if not conditions:
            return False
        return all(self.evaluate(c, data) for c in conditions)
