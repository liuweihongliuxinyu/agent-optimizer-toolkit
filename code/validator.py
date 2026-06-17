"""
Pre-call Validator — 工具调用前参数校验框架

功能：
1. 加载 YAML 校验规则
2. 在工具调用前检查参数合法性
3. 不合规参数拒绝调用并返回详细错误信息

用法:
    from validator import Validator

    v = Validator("validation-rules.yaml")
    result = v.check("get_order", {"order_id": "12345678", "user_id": "u_001"})

    if result.valid:
        proceed_with_tool_call()
    else:
        return result.errors  # 返回给 Agent 让它修正参数
"""

import re
import yaml
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class ValidationResult:
    valid: bool
    tool_name: str
    params: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Validator:
    def __init__(self, rules_path: str):
        with open(rules_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.tool_rules = config.get("tools", {})
        self.global_rules = config.get("global_rules", [])
        self.failure_policy = config.get("failure_policy", {})
        self.call_counts: dict[str, list[float]] = {}

    def check(self, tool_name: str, params: dict) -> ValidationResult:
        """校验一次工具调用的所有参数"""
        result = ValidationResult(
            valid=True,
            tool_name=tool_name,
            params=params,
        )

        # 1. 全局规则检查
        self._check_global(params, result)

        # 2. 工具特定规则
        tool_config = self.tool_rules.get(tool_name)
        if tool_config is None:
            result.warnings.append(f"工具 '{tool_name}' 未配置校验规则（建议补充）")
            return result

        for rule in tool_config.get("rules", []):
            self._apply_rule(rule, params, result)

        # 3. 交叉校验
        self._cross_validate(tool_config, params, result)

        return result

    # ─── 全局规则 ──────────────────────────────

    def _check_global(self, params: dict, result: ValidationResult):
        for rule in self.global_rules:
            check = rule.get("check", "")
            msg = rule.get("message", check)
            severity = rule.get("severity", "block")

            if check == "no_sql_injection":
                self._check_sql_injection(params, result, msg, severity)
            elif check == "no_xss":
                self._check_xss(params, result, msg, severity)
            elif check == "rate_limit":
                self._check_rate_limit(result, msg, severity, rule.get("config", {}))

    def _check_sql_injection(self, params, result, msg, severity):
        sql_patterns = [
            r"(?i)(\bSELECT\b.*\bFROM\b|\bDROP\b|\bDELETE\b|\bINSERT\b|\bUPDATE\b)",
            r"(?i)(--|;|/\*|\*/)",
            r"(?i)(\bUNION\b.*\bSELECT\b)",
            r"(?i)(\bEXEC\b|\bEXECUTE\b)",
        ]
        for key, value in params.items():
            if isinstance(value, str):
                for pattern in sql_patterns:
                    if re.search(pattern, value):
                        self._add_issue(result, msg, severity, key)
                        return

    def _check_xss(self, params, result, msg, severity):
        xss_patterns = [
            r"<script.*?>",
            r"javascript:",
            r"on\w+\s*=",
        ]
        for key, value in params.items():
            if isinstance(value, str):
                for pattern in xss_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        self._add_issue(result, msg, severity, key)
                        return

    def _check_rate_limit(self, result, msg, severity, config):
        now = datetime.now().timestamp()
        minute_ago = now - 60
        hour_ago = now - 3600

        # 清理过期记录
        for tool in self.call_counts:
            self.call_counts[tool] = [
                t for t in self.call_counts[tool] if t > hour_ago
            ]

        all_calls = []
        for times in self.call_counts.values():
            all_calls.extend(times)

        max_per_min = config.get("max_calls_per_minute", 60)
        max_per_hour = config.get("max_calls_per_hour", 1000)

        calls_last_min = sum(1 for t in all_calls if t > minute_ago)
        calls_last_hour = len(all_calls)

        if calls_last_min > max_per_min or calls_last_hour > max_per_hour:
            self._add_issue(result, msg, severity)

    # ─── 单规则应用 ───────────────────────────

    def _apply_rule(self, rule: dict, params: dict, result: ValidationResult):
        field = rule.get("field")
        value = params.get(field)

        # 获取错误消息
        msg = lambda default: rule.get(
            f"{rule.get('check', 'required')}_message",
            rule.get("pattern_message",
            rule.get("max_message",
            rule.get("min_message",
            rule.get("message", default))))
        )

        # Required check
        if rule.get("required") and (value is None or value == ""):
            self._add_issue(result, msg(f"参数 '{field}' 是必填项"), "block", field)
            return

        if value is None:
            # 选填且未提供 → 设默认值
            if "default" in rule:
                params[field] = rule["default"]
            return

        # Type check
        expected_type = rule.get("type")
        if expected_type and not self._check_type(value, expected_type):
            self._add_issue(result, msg(f"参数 '{field}' 类型错误，期望 {expected_type}"), "block", field)
            return

        # Pattern check
        pattern = rule.get("pattern")
        if pattern and isinstance(value, str) and not re.match(pattern, value):
            self._add_issue(result, msg(f"参数 '{field}' 格式不正确"), "block", field)
            return

        # Enum check
        enum_values = rule.get("enum")
        if enum_values and value not in enum_values:
            self._add_issue(result, msg(f"参数 '{field}' 值无效"), "block", field)
            return

        # Min/Max check (numbers)
        if isinstance(value, (int, float)):
            if "min" in rule and value < rule["min"]:
                self._add_issue(result, msg(f"参数 '{field}' 值不能小于 {rule['min']}"), "block", field)
                return
            if "max" in rule and value > rule["max"]:
                self._add_issue(result, msg(f"参数 '{field}' 值不能大于 {rule['max']}"), "block", field)
                return

        # Min/Max length (strings)
        if isinstance(value, str):
            if "min_length" in rule and len(value) < rule["min_length"]:
                self._add_issue(result, msg(f"参数 '{field}' 长度不能少于 {rule['min_length']}"), "block", field)
                return
            if "max_length" in rule and len(value) > rule["max_length"]:
                self._add_issue(result, msg(f"参数 '{field}' 长度不能超过 {rule['max_length']}"), "block", field)
                return

        # Custom checks
        check = rule.get("check")
        if check == "authenticated":
            # 接入你的认证系统
            if not self._is_authenticated(params):
                self._add_issue(result, msg("用户必须已登录"), "block", field)
        elif check == "future_datetime":
            if not self._is_future(value):
                self._add_issue(result, msg("时间必须是未来时间"), "block", field)

        # Sanitize
        if rule.get("sanitize") and isinstance(value, str):
            sanitized = self._sanitize(value)
            if sanitized != value:
                self._add_issue(result, msg(f"参数 '{field}' 包含非法字符"), "block", field)
                return
            params[field] = sanitized

        # Depends on
        depends = rule.get("depends_on")
        if depends and params.get(depends) and value is None:
            self._add_issue(
                result,
                rule.get("depends_message", f"'{field}' 和 '{depends}' 必须同时提供"),
                "block", field
            )

    def _cross_validate(self, tool_config: dict, params: dict, result: ValidationResult):
        """跨字段联合校验"""
        for rule in tool_config.get("rules", []):
            cross = rule.get("cross_validate")
            if cross and "price_max >= price_min" in cross:
                price_min = params.get("price_min")
                price_max = params.get("price_max")
                if price_min is not None and price_max is not None:
                    if price_max < price_min:
                        self._add_issue(
                            result,
                            rule.get("cross_message", "交叉校验失败"),
                            "block",
                            "price_max"
                        )

    # ─── 辅助方法 ──────────────────────────────

    def _check_type(self, value, expected: str) -> bool:
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected_types = type_map.get(expected)
        if expected_types is None:
            return True
        return isinstance(value, expected_types)

    def _is_authenticated(self, params: dict) -> bool:
        # TODO: 接入实际认证系统
        return bool(params.get("user_id"))

    def _is_future(self, value) -> bool:
        try:
            dt = datetime.fromisoformat(str(value))
            return dt > datetime.now()
        except (ValueError, TypeError):
            return False

    def _sanitize(self, value: str) -> str:
        # 基础清理：去除控制字符和危险标签
        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)
        value = re.sub(r'<script.*?>.*?</script>', '', value, flags=re.IGNORECASE)
        return value

    def _add_issue(self, result: ValidationResult, msg: str, severity: str, field: str = None):
        prefix = f"[{field}] " if field else ""
        full_msg = f"{prefix}{msg}"
        if severity == "block":
            result.errors.append(full_msg)
            result.valid = False
        else:
            result.warnings.append(full_msg)

    def record_call(self, tool_name: str):
        """记录一次成功的工具调用（用于频率限制）"""
        now = datetime.now().timestamp()
        if tool_name not in self.call_counts:
            self.call_counts[tool_name] = []
        self.call_counts[tool_name].append(now)


# ─── 使用示例 ────────────────────────────────

if __name__ == "__main__":
    v = Validator("validation-rules.yaml")

    # ✅ 正确调用
    r = v.check("get_order", {"order_id": "12345678", "user_id": "u_001"})
    print(f"正确调用: valid={r.valid}, errors={r.errors}")

    # ❌ 错误调用：订单号格式不对
    r = v.check("get_order", {"order_id": "abc", "user_id": "u_001"})
    print(f"错误调用: valid={r.valid}, errors={r.errors}")

    # ❌ 错误调用：金额为负
    r = v.check("create_order", {
        "product_id": "P001",
        "quantity": 2,
        "amount": -100
    })
    print(f"金额错误: valid={r.valid}, errors={r.errors}")

    # ❌ 错误调用：SQL注入
    r = v.check("search_products", {"query": "'; DROP TABLE users; --"})
    print(f"SQL注入: valid={r.valid}, errors={r.errors}")

    # ⚠️ 未配置规则的工具
    r = v.check("unknown_tool", {"x": 1})
    print(f"未配置规则: valid={r.valid}, warnings={r.warnings}")
