from __future__ import annotations

import re
from typing import Any

from raven.core.monitor.models import Condition, ConditionOperator


class ConditionEvaluator:
    def evaluate(self, condition: Condition, check_result: dict[str, Any]) -> bool:
        metric_value = check_result.get(condition.metric)
        if metric_value is None:
            return False

        op = condition.operator
        target = condition.value

        try:
            if op == ConditionOperator.GT:
                return float(metric_value) > float(target)
            elif op == ConditionOperator.LT:
                return float(metric_value) < float(target)
            elif op == ConditionOperator.EQ:
                return str(metric_value) == str(target)
            elif op == ConditionOperator.NE:
                return str(metric_value) != str(target)
            elif op == ConditionOperator.CONTAINS:
                return str(target).lower() in str(metric_value).lower()
            elif op == ConditionOperator.MATCHES:
                return bool(re.search(str(target), str(metric_value)))
            elif op == ConditionOperator.CHANGED:
                return check_result.get("changed", False)
        except (ValueError, TypeError):
            return False

        return False

    def check_all(self, conditions: list[Condition], check_result: dict[str, Any]) -> bool:
        if not conditions:
            return False
        return all(self.evaluate(c, check_result) for c in conditions)
