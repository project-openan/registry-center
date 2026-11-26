# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""用例集：持久化抽象层（base.py / persistence/__init__.py）。

覆盖三块此前几乎无断言保护的行为：
- 文件落盘的安全语义（0600 权限、超限拒绝、损坏文件不炸进程）
- StorageRegistry 的模式分派（未知模式必须报错，不能静默降级）
- StorageBackend 的默认实现（find_records 四种入参组合、状态历史默认值）
"""

import json
import os
import stat

import sys

import pytest

_WIN_SKIP = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX 0600 file permissions cannot be reproduced on Windows")
from a2a.types import AgentCard

from agent_registry.persistence import StorageRegistry, load_from_file, save_to_file
from agent_registry.persistence import base as persistence_base
from agent_registry.persistence.base import AgentRecord, StorageBackend


def _card(name="agent-a", org="org-a"):
    return AgentCard(
        name=name,
        provider={"organization": org, "url": "https://example.invalid"},
        description="d",
        version="1.0.0",
        skills=[],
    )


class TestSaveToFile:
    """TC-STORE-001..004：落盘。"""

    @_WIN_SKIP
    def test_writes_utf8_json_and_locks_down_permissions(self, tmp_path):
        """TC-STORE-001 | 保存后内容可读、且文件权限为 0600

        输入: 两个含中文的 agent 字典
        预期输出: 文件存在、内容等价、权限 0o600
        断言点: 解析后数据 + os.stat 权限位
        防回归: 若 chmod 被删或编码被改成 ascii，本用例失败
        """
        target = tmp_path / "nested" / "agents.json"
        payload = [{"name": "智能体", "organization": "组织"}, {"name": "b"}]

        save_to_file(str(target), payload)

        assert json.loads(target.read_text(encoding="utf-8")) == payload
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    def test_oversized_payload_raises(self, tmp_path, monkeypatch):
        """TC-STORE-002 | 超过大小上限必须抛 ValueError 且不落盘

        输入: MAX_FILE_SIZE_BYTES 临时改为 16，写入较长内容
        预期输出: ValueError，消息含 "exceeds maximum"
        断言点: 异常类型 + 消息 + 目标文件不存在
        防回归: 若上限检查被删，本用例失败（会静默写出超大文件）
        """
        monkeypatch.setattr(
            "agent_registry.persistence.MAX_FILE_SIZE_BYTES", 16, raising=True)
        target = tmp_path / "big.json"

        with pytest.raises(ValueError, match="exceeds maximum"):
            save_to_file(str(target), [{"name": "x" * 200}])

        assert not target.exists()

    def test_serialisation_failure_propagates(self, tmp_path):
        """TC-STORE-003 | 不可序列化对象必须抛出而不是吞掉

        输入: 含 set() 的对象列表（json 无法编码）
        预期输出: TypeError
        断言点: 异常类型
        防回归: 若 except 分支把异常吞掉，本用例失败
        """
        with pytest.raises(TypeError):
            save_to_file(str(tmp_path / "bad.json"), [{"tags": {"a", "b"}}])


class TestLoadFromFile:
    """TC-STORE-004..009：加载与容错。"""

    def test_missing_file_returns_empty(self, tmp_path):
        """TC-STORE-004 | 文件不存在返回空列表而不是抛异常

        输入: 不存在的路径
        预期输出: []
        断言点: 返回值 == []
        防回归: 若改为抛 FileNotFoundError，启动流程会被打断
        """
        assert load_from_file(str(tmp_path / "absent.json")) == []

    def test_roundtrip(self, tmp_path):
        """TC-STORE-005 | 写入后读回内容一致

        输入: 两个字典
        预期输出: 读回等值列表
        断言点: 内容相等
        防回归: 若编码/缩进处理破坏内容，本用例失败
        """
        target = tmp_path / "roundtrip.json"
        payload = [{"name": "a"}, {"name": "中文"}]
        save_to_file(str(target), payload)
        assert load_from_file(str(target)) == payload

    def test_oversized_file_returns_empty(self, tmp_path, monkeypatch):
        """TC-STORE-006 | 超大文件拒绝加载（防内存打爆）

        输入: 文件大小 > 上限
        预期输出: []
        断言点: 返回值 == []（不抛异常）
        防回归: 若大小检查被删，本用例失败
        """
        target = tmp_path / "huge.json"
        target.write_text("[" + "0," * 100 + "0]", encoding="utf-8")
        monkeypatch.setattr(
            "agent_registry.persistence.MAX_FILE_SIZE_BYTES", 8, raising=True)

        assert load_from_file(str(target)) == []

    def test_corrupted_json_returns_empty(self, tmp_path):
        """TC-STORE-007 | 损坏的 JSON 不应让服务启动失败

        输入: "{not json"
        预期输出: []
        断言点: 返回值 == []
        防回归: 若异常未被捕获，启动流程崩溃
        """
        target = tmp_path / "broken.json"
        target.write_text("{not json", encoding="utf-8")
        assert load_from_file(str(target)) == []

    def test_non_list_json_returns_empty(self, tmp_path):
        """TC-STORE-008 | 结构不是列表时拒绝加载

        输入: {"agents": []}
        预期输出: []
        断言点: 返回值 == []
        防回归: 若缺类型检查，后续代码会在 dict 上迭代出错
        """
        target = tmp_path / "dict.json"
        target.write_text('{"agents": []}', encoding="utf-8")
        assert load_from_file(str(target)) == []


class TestStorageRegistry:
    """TC-STORE-009..015：后端分派。"""

    def test_unknown_mode_raises(self):
        """TC-STORE-009 | 未知存储模式必须报错，不能静默降级

        输入: mode="mongodb"
        预期输出: ValueError，消息含 "Unknown storage mode"
        断言点: 异常类型 + 消息
        防回归: 若缺 else 分支，会返回 None 并在运行期炸
        """
        with pytest.raises(ValueError, match="Unknown storage mode"):
            StorageRegistry.get_backend("mongodb", {})

    @pytest.mark.parametrize("mode,patch_target", [
        ("file", "agent_registry.persistence.FileStorage"),
        ("sqlite", "agent_registry.persistence.sqlite_storage.SQLiteStorage"),
        ("postgresql", "agent_registry.persistence.postgresql_storage.PostgreSQLStorage"),
        ("gauss", "agent_registry.persistence.gaussdb_storage.GaussDBStorage"),
        ("mysql", "agent_registry.persistence.mysql_storage.MySQLStorage"),
    ])
    def test_mode_dispatch_reaches_expected_backend(self, mode, patch_target, monkeypatch):
        """TC-STORE-010..014 | 每种模式分派到对应后端（以桩替换构造）

        输入: mode ∈ {file, sqlite, postgresql, gauss, mysql}
        预期输出: 调用目标后端的 init，并原样返回其实例
        断言点: init 收到的 config 一致 + 返回对象是桩实例
        防回归: 若某分支指向错误后端，本用例失败
        """
        sentinel = object()
        captured = {}

        class _Stub:
            @classmethod
            def init(cls, config):
                captured["config"] = config
                return sentinel

        monkeypatch.setattr(patch_target, _Stub, raising=True)

        result = StorageRegistry.get_backend(mode, {"k": "v"})

        assert result is sentinel
        assert captured["config"] == {"k": "v"}


class _FakeBackend(StorageBackend):
    """最小可用后端：只实现抽象方法，用于验证基类默认行为。"""

    def __init__(self, records):
        self._records = records

    @classmethod
    def init(cls, config):
        return cls([])

    def create(self, agent, owner=None, status="published", layer="unknown"):
        return True

    def find_by_key(self, name, organization, owner=None):
        for record in self._records:
            card = record.agent_card
            if card.name == name and card.provider.organization == organization:
                return record
        return None

    def find_by_name(self, name):
        return [r.agent_card for r in self._records if r.agent_card.name == name]

    def find_by_organization(self, organization):
        return [r.agent_card for r in self._records
                if r.agent_card.provider.organization == organization]

    def find_all(self, status=None):
        return [r.agent_card for r in self._records]

    def find_by_owner(self, owner):
        return [r for r in self._records if r.owner == owner]

    def find_by_status(self, status):
        return [r.agent_card for r in self._records if r.status == status]

    def find_by_tag(self, tag):
        return []

    def update(self, name, organization, agent_data, owner=None, layer=None):
        return True

    def update_status(self, name, organization, new_status):
        return True

    def delete(self, name, organization, owner=None):
        return True

    def count(self):
        return len(self._records)

    def get_created_at(self, name, organization):
        return ""

    def get_updated_at(self, name, organization):
        return ""

    def get_agent_tags(self, name, organization):
        return []

    def update_agent_tags(self, name, organization, tags):
        return True

    def create_tag(self, tag):
        return True

    def get_tag(self, tag_id):
        return None

    def get_tag_by_name(self, name):
        return None

    def update_tag(self, tag_id, tag):
        return True

    def delete_tag(self, tag_id):
        return True

    def list_tags(self):
        return []

    def close(self):
        return None


class TestStorageBackendDefaults:
    """TC-STORE-015..021：基类默认实现（自定义后端依赖这些语义）。"""

    def _backend(self):
        records = [
            AgentRecord(agent_card=_card("a1", "o1"), status="published", layer="app"),
            AgentRecord(agent_card=_card("a2", "o1"), status="draft", layer="app"),
            AgentRecord(agent_card=_card("b1", "o2"), status="published", layer="infra"),
        ]
        return _FakeBackend(records)

    def test_find_records_by_name_and_organization(self):
        """TC-STORE-015 | 名字+组织精确命中一条

        输入: name="a1", organization="o1"
        预期输出: 只返回 a1
        断言点: 结果长度与卡片名字
        防回归: 若组合分支退化为全量扫描，本用例失败
        """
        records = self._backend().find_records(name="a1", organization="o1")
        assert [r.agent_card.name for r in records] == ["a1"]

    def test_find_records_by_name_only(self):
        """TC-STORE-016 | 只给 name 时返回同名全部记录

        输入: name="a1"
        预期输出: 1 条
        断言点: 名字集合
        防回归: 若按 name 分支丢了组织信息，会漏记录
        """
        records = self._backend().find_records(name="a1")
        assert {r.agent_card.name for r in records} == {"a1"}

    def test_find_records_by_organization_only(self):
        """TC-STORE-017 | 只给 organization 时返回该组织全部记录

        输入: organization="o1"
        预期输出: a1、a2 两条
        断言点: 名字集合
        防回归: 若分支错误，会混入 o2
        """
        records = self._backend().find_records(organization="o1")
        assert {r.agent_card.name for r in records} == {"a1", "a2"}

    def test_find_records_without_filters_returns_all(self):
        """TC-STORE-018 | 无过滤条件时返回全部

        输入: 无
        预期输出: 3 条
        断言点: 数量
        防回归: 若空参分支返回空列表，本用例失败
        """
        assert len(self._backend().find_records()) == 3

    def test_find_records_filters_by_layer_and_status(self):
        """TC-STORE-019 | layer 与 status 过滤可叠加

        输入: layer="app", status="published"
        预期输出: 仅 a1
        断言点: 名字元组
        防回归: 若过滤条件被 and/or 写反，本用例失败
        """
        records = self._backend().find_records(layer="app", status="published")
        assert [r.agent_card.name for r in records] == ["a1"]

    def test_default_status_history_is_inert(self):
        """TC-STORE-020 | 基类状态历史默认实现不写不报错

        输入: append/get/delete 三种调用
        预期输出: append False、get []、delete None
        断言点: 三个返回值
        防回归: 若默认实现改为抛 NotImplementedError，自定义后端会崩
        """
        backend = self._backend()
        assert backend.append_status_history("a1", "o1", None, "draft") is False
        assert backend.get_status_history("a1", "o1") == []
        assert backend.delete_status_history("a1", "o1") is None
        assert backend.check_connection() is None
        assert backend.supports_transactions is False

    def test_agent_record_to_dict(self):
        """TC-STORE-021 | AgentRecord.to_dict 字段完整且值正确

        输入: 带 tags/layer 的记录
        预期输出: 7 个键齐全，值原样
        断言点: 键集合 + 抽查值
        防回归: 若字段被漏掉，序列化后数据丢失
        """
        record = AgentRecord(agent_card=_card(), owner="u1", status="draft",
                             created_at="t0", updated_at="t1", tags=["x"], layer="app")
        data = record.to_dict()

        assert set(data) == {"agent_card", "owner", "status", "created_at",
                             "updated_at", "tags", "layer"}
        assert data["owner"] == "u1"
        assert data["tags"] == ["x"]
        assert data["layer"] == "app"
        assert persistence_base.UNKNOWN_LAYER == AgentRecord(agent_card=_card()).layer
