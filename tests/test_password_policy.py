# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""用例集：密码复杂度策略（common/util/password_util.py）。

这些用例存在的意义：变异测试（tests/mutation_check.py MUT-005）证明，
把最小长度判断改坏后，原有用例全绿 —— 即"密码策略"此前形同裸奔。
本文件为每条策略各钉一条断言，改坏任意一条规则都会立刻变红。
"""

from common.util.password_util import (
    input_password_with_validation,
    validate_password_complexity,
)


class TestValidatePasswordComplexity:
    """TC-PWD-001..010：复杂度规则逐条钉死。"""

    def test_empty_password_rejected(self):
        """TC-PWD-001 | 空密码必须拒绝

        输入: ""
        预期输出: (False, "Password is empty")
        断言点: 布尔结果 + 消息关键字 "empty"
        防回归: 若空值判断被删，本用例失败
        """
        ok, message = validate_password_complexity("")
        assert ok is False
        assert "empty" in message.lower()

    def test_too_short_rejected_at_boundary_minus_one(self):
        """TC-PWD-002 | 7 位（下限 8）必须拒绝

        输入: "Abc1234"（7 位，含大小写+数字，字符类型达标）
        预期输出: (False, 含 "8")
        断言点: 结果 False + 消息中出现最小长度 8
        防回归: 若 `< min_length` 被改成 `< 0` 或下限被调小，本用例失败
        """
        ok, message = validate_password_complexity("Abc1234")
        assert ok is False
        assert "8" in message

    def test_exactly_min_length_accepted(self):
        """TC-PWD-003 | 恰好 8 位且字符类型达标必须通过

        输入: "Abc12345"
        预期输出: (True, "")
        断言点: 结果为 True（边界不应被误拒）
        防回归: 若比较符被写成 `<=`，本用例失败
        """
        assert validate_password_complexity("Abc12345") == (True, "")

    def test_single_character_type_rejected(self):
        """TC-PWD-004 | 只有一种字符类型必须拒绝

        输入: "abcdefgh"（仅小写）
        预期输出: (False, 含 "two character types")
        断言点: 结果 False + 消息体现字符类型要求
        防回归: 若 char_types 阈值被改小，本用例失败
        """
        ok, message = validate_password_complexity("abcdefgh")
        assert ok is False
        assert "two character types" in message

    def test_digits_only_rejected(self):
        """TC-PWD-005 | 纯数字必须拒绝

        输入: "1234567890"
        预期输出: (False, 字符类型不足)
        断言点: 结果 False
        防回归: 若数字被单独视为足够复杂，本用例失败
        """
        ok, _ = validate_password_complexity("1234567890")
        assert ok is False

    def test_upper_and_digit_accepted(self):
        """TC-PWD-006 | 大写+数字（两种类型）应当通过

        输入: "ABCDE12345"
        预期输出: (True, "")
        断言点: 结果为 True
        防回归: 若类型统计只认小写，本用例失败
        """
        assert validate_password_complexity("ABCDE12345") == (True, "")

    def test_special_character_counts_as_type(self):
        """TC-PWD-007 | 特殊字符应与数字一起构成两种类型

        输入: "@@@@@@@1"
        预期输出: (True, "")
        断言点: 结果为 True
        防回归: 若特殊字符正则失配，本用例失败
        """
        assert validate_password_complexity("@@@@@@@1") == (True, "")

    def test_unicode_password_rejected(self):
        """TC-PWD-008 | 纯中文+数字不满足"两种类型"

        输入: "密码密码密码1"（中文字符不匹配大小写/特殊字符正则）
        预期输出: (False, 字符类型不足)
        断言点: 结果 False，避免把中文误算成大小写类型
        防回归: 若正则被放宽到任意非 ASCII，本用例失败
        """
        ok, _ = validate_password_complexity("密码密码密码1")
        assert ok is False

    def test_spaces_only_rejected(self):
        """TC-PWD-009 | 纯空格必须拒绝

        输入: "        "（8 个空格）
        预期输出: (False, 字符类型不足)
        断言点: 结果 False
        防回归: 若空格被当作两类字符，本用例失败
        """
        ok, _ = validate_password_complexity("        ")
        assert ok is False

    def test_long_password_accepted(self):
        """TC-PWD-010 | 长密码不受上限误伤

        输入: "Aa1" * 100（300 位，三种类型）
        预期输出: (True, "")
        断言点: 结果为 True
        防回归: 若实现被加上不该有的长度上限，本用例失败
        """
        assert validate_password_complexity("Aa1" * 100) == (True, "")


class TestInputPasswordWithValidation:
    """TC-PWD-011..013：交互式输入在弱口令时的三条分支。"""

    def test_returns_strong_password_immediately(self, monkeypatch):
        """TC-PWD-011 | 强口令直接返回，不触发确认提示

        输入: getpass 返回 "Abc12345"
        预期输出: 返回该口令；input() 不应被调用
        断言点: 返回值正确 + 未进入确认分支
        防回归: 若校验被跳过或提示逻辑前置，本用例失败
        """
        monkeypatch.setattr('getpass.getpass', lambda prompt='': 'Abc12345')

        def _boom():
            raise AssertionError('confirmation prompt must not appear for a strong password')

        monkeypatch.setattr('builtins.input', _boom)
        assert input_password_with_validation('pwd') == 'Abc12345'

    def test_weak_password_rejected_then_accepts_retry(self, monkeypatch):
        """TC-PWD-012 | 弱口令被拒后继续询问，直到输入强口令

        输入: 第一次 "short"，确认提示回答 "n"，第二次 "Abc12345"
        预期输出: 返回 "Abc12345"
        断言点: 返回值 + getpass 被调用两次
        防回归: 若拒绝后直接返回弱口令，本用例失败
        """
        passwords = iter(['short', 'Abc12345'])
        calls = []

        def fake_getpass(prompt=''):
            calls.append(prompt)
            return next(passwords)

        monkeypatch.setattr('getpass.getpass', fake_getpass)
        monkeypatch.setattr('builtins.input', lambda: 'n')

        assert input_password_with_validation('pwd') == 'Abc12345'
        assert len(calls) == 2

    def test_weak_password_forced_with_confirmation(self, monkeypatch):
        """TC-PWD-013 | 弱口令经用户确认 "y" 后仍然采用

        输入: "short"，确认回答 "y"
        预期输出: 返回 "short"
        断言点: 返回值是弱口令（显式确认路径生效）
        防回归: 若确认分支被删，本用例失败
        """
        monkeypatch.setattr('getpass.getpass', lambda prompt='': 'short')
        monkeypatch.setattr('builtins.input', lambda: 'y')

        assert input_password_with_validation('pwd') == 'short'
