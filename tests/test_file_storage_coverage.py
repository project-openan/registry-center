# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""FileStorage coverage tests (agent_registry/persistence/file_storage.py).

Every test owns a tmp_path directory and a freshly constructed ``FileStorage``;
nothing is shared between tests and no global/singleton state is touched. Where a
mock is unavoidable (an OSError from ``os.path.getsize``) the double is scoped by
``monkeypatch``. Persistence assertions read the JSON files back from disk so a
silently dropped write is caught.
"""

import json
import os

import pytest
from a2a.types import AgentCard

from agent_registry.model.agent_layer import UNKNOWN_LAYER
from agent_registry.model.tag import Tag
from agent_registry.persistence.file_storage import FileStorage


def _agent(name="A", org="O", desc="d"):
    return AgentCard(
        name=name,
        provider={"organization": org, "url": "https://example.test"},
        description=desc,
        version="1.0.0",
        skills=[],
    )


def _paths(tmp_path):
    return (str(tmp_path / "agentcard.json"),
            str(tmp_path / "agentregistry.json"),
            str(tmp_path / "tags.json"))


@pytest.fixture
def paths(tmp_path):
    return _paths(tmp_path)


@pytest.fixture
def fs(paths):
    return FileStorage(*paths)


def _read_json(path):
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)


class TestOwnerScope:
    def test_find_by_key_owner_mismatch_returns_none(self, fs):
        """TC-STORE-101 | 查询时 owner 与会话 owner 不一致则不返回记录

        输入: 创建 agent A（owner="alice"），分别以 owner="bob"、"alice"、None 查询
        预期输出: owner="bob" -> None；owner="alice" -> 记录；owner=None -> 记录（不校验）
        断言点: 三种 owner 入参的返回对象（None / 记录 owner 字段 / 记录 owner 字段）
        防回归: 若 owner 隔离条件被删除，跨租户可读到他人 AgentCard，本用例失败
        """
        fs.create(_agent(), owner="alice")

        assert fs.find_by_key("A", "O", owner="bob") is None
        assert fs.find_by_key("A", "O", owner="alice").owner == "alice"
        assert fs.find_by_key("A", "O").owner == "alice"

    def test_find_by_owner_returns_only_that_owner(self, fs):
        """TC-STORE-102 | find_by_owner 只返回属于该 owner 的记录

        输入: alice 建 A、bob 建 B（同组织），查询 alice
        预期输出: 仅 A 一条，且 status/tags/layer/created_at 均来自存储
        断言点: 返回列表长度 1、名称、owner、默认 status 'published'、layer unknown、created_at 非空
        防回归: 若遍历 _owner_map 时未回查 _agents（返回已被删除的 owner 键），本用例失败
        """
        fs.create(_agent("A", "O"), owner="alice")
        fs.create(_agent("B", "O"), owner="bob")

        records = fs.find_by_owner("alice")

        assert [record.agent_card.name for record in records] == ["A"]
        assert records[0].owner == "alice"
        assert records[0].status == "published"
        assert records[0].layer == UNKNOWN_LAYER
        assert records[0].created_at


class TestFindRecords:
    def test_find_records_filters_name_organization_layer_status(self, fs):
        """TC-STORE-103 | find_records 支持 name/org/layer/status 组合过滤

        输入: 建 (Alpha, o1, layer=cloud, status=published)、(beta, o2, layer=edge),
              按 name="alp"、organization="o2"、layer="cloud"、status="registered" 分别查询
        预期输出: name="alp" -> Alpha（子串、大小写不敏感）；organization="o2" -> beta；
              layer="cloud" -> Alpha；status="registered" -> 空列表
        断言点: 每类过滤的返回名称列表；layer 归一化后存 "cloud"；status 不匹配时返回 []
        防回归: 若某个过滤条件被 continue 前的短路逻辑吞掉（例如 layer 未归一化），本用例失败
        """
        fs.create(_agent("Alpha", "o1"), status="published", layer="cloud")
        fs.create(_agent("beta", "o2"), status="published", layer="edge")

        assert [r.agent_card.name for r in fs.find_records(name="alp")] == ["Alpha"]
        assert [r.agent_card.name for r in fs.find_records(organization="o2")] == ["beta"]
        assert [r.agent_card.name for r in fs.find_records(layer="  cloud  ")] == ["Alpha"]
        assert fs.find_records(status="registered") == []

    def test_find_records_rejects_invalid_layer(self, fs):
        """TC-STORE-104 | find_records 对非法 layer 入参抛 ValueError

        输入: find_records(layer="") 与 find_records(layer=123)
        预期输出: ValueError，消息分别含 "non-empty" 与 "must be a string"
        断言点: 异常类型 + 消息关键字（两次调用各一）
        防回归: 若非法 layer 被静默当作 None 处理，会返回全量记录误导调用方，本用例失败
        """
        fs.create(_agent())

        with pytest.raises(ValueError, match="non-empty"):
            fs.find_records(layer="")
        with pytest.raises(ValueError, match="must be a string"):
            fs.find_records(layer=123)

    def test_find_by_status_keeps_legacy_records_without_status(self, paths):
        """TC-STORE-105 | 无状态元数据的旧记录仍出现在 published 结果中

        输入: 只有 agentcard.json（无元数据文件），find_by_status("published") 与 ("registered")
        预期输出: published -> [A]；registered -> []
        断言点: 两个状态的返回名称列表（存量为 None 时只有可发现状态才兜底）
        防回归: 若 None 状态对任意过滤器都兜底，pending 卡片会泄漏到发现接口，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A",
                "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert [agent.name for agent in storage.find_by_status("published")] == ["A"]
        assert storage.find_by_status("registered") == []
        assert storage._status_map[("A", "O")] == "published"


class TestStatusHistory:
    def test_append_history_for_unknown_agent_returns_false(self, fs):
        """TC-STORE-106 | 未注册 Agent 追加状态历史返回 False 且不落盘

        输入: append_status_history("ghost", "O", None, "published")
        预期输出: False；不创建元数据文件，也不产生历史条目
        断言点: 返回值为 False；元数据文件不存在；内存历史表为空
        防回归: 若历史写入不校验主键，会出现指向不存在卡片的历史行，本用例失败
        """
        assert fs.append_status_history("ghost", "O", None, "published") is False

        assert not os.path.exists(fs.metadata_file)
        assert fs._status_history_map == {}
        assert fs.get_status_history("ghost", "O") == []

    def test_history_is_recorded_capped_and_newest_first(self, fs):
        """TC-STORE-107 | 状态历史落盘、按 50 条上限截断、查询最新在前且支持 limit

        输入: 创建 A 后连续追加 55 条历史（to_status 依次为 s0..s54）
        预期输出: 落盘历史 50 条，首条为 s5、末条为 s54；
              get_status_history(limit=3) 返回 [s54, s53, s52]；limit=0 返回 []
        断言点: 元数据文件中 status_history 长度与首末 to_status；查询顺序与条数
        防回归: 若 del history[:-MAX] 写错方向（保留最旧 50 条）或无界增长，本用例失败
        """
        fs.create(_agent())
        for index in range(55):
            assert fs.append_status_history("A", "O", None, f"s{index}",
                                            reason=f"r{index}", operator="ci") is True

        registry = _read_json(fs.metadata_file)
        history = registry[0]["status_history"]
        assert len(history) == FileStorage.MAX_STATUS_HISTORY == 50
        assert history[0]["to_status"] == "s5"
        assert history[-1]["to_status"] == "s54"
        assert history[-1] == {
            "from_status": None, "to_status": "s54", "reason": "r54",
            "operator": "ci", "at": history[-1]["at"],
        }
        assert [entry["to_status"] for entry in fs.get_status_history("A", "O", limit=3)] == [
            "s54", "s53", "s52"]
        assert fs.get_status_history("A", "O", limit=0) == []

    def test_delete_status_history_is_idempotent(self, fs):
        """TC-STORE-108 | 删除状态历史后不可再查，重复删除不报错

        输入: 追加一条历史后 delete_status_history("A", "O") 两次
        预期输出: get_status_history 返回 []；二次删除无异常
        断言点: 首次与二次删除后的查询结果均为 []
        防回归: 若删除未清理 _status_history_map，卡片删除后历史会滞留，本用例失败
        """
        fs.create(_agent())
        fs.append_status_history("A", "O", None, "published")
        assert len(fs.get_status_history("A", "O")) == 1

        fs.delete_status_history("A", "O")
        fs.delete_status_history("A", "O")

        assert fs.get_status_history("A", "O") == []


class TestUpdateAndDelete:
    def test_update_rejects_invalid_agent_data(self, fs):
        """TC-STORE-109 | update 对非法 AgentCard 数据抛 ValueError 且不破坏原记录

        输入: 创建 A 后 update 传入 skills 为非列表的卡数据（主键不变）
        预期输出: ValueError，消息以 "Invalid agent data" 开头
        断言点: 异常类型 + 消息前缀；原记录仍可读且 description 未变
        防回归: 若异常被吞掉后继续赋值，内存与磁盘会出现半更新的卡片，本用例失败
        """
        fs.create(_agent(desc="original"))

        with pytest.raises(ValueError, match="Invalid agent data"):
            fs.update("A", "O", {
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "broken", "version": "2.0.0", "skills": "not-a-list",
            })

        assert fs.find_by_key("A", "O").agent_card.description == "original"

    def test_update_applies_layer(self, fs):
        """TC-STORE-110 | update 在显式 layer 时更新 layer 并落盘

        输入: 创建 A（layer unknown），update 同一张卡并传 layer="cloud"
        预期输出: 返回 True；读回 layer="cloud"，updated_at 刷新，元数据文件同步
        断言点: 返回值；find_by_key 的 layer 与 card 字段；元数据文件 layer/updated_at
        防回归: 若 layer 参数被 LAYER_UNSET 判断误挡（总是保留旧值），本用例失败
        """
        fs.create(_agent())
        before = fs.get_updated_at("A", "O")

        assert fs.update("A", "O", {
            "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
            "description": "d2", "version": "1.0.0", "skills": [],
        }, layer="cloud") is True

        record = fs.find_by_key("A", "O")
        registry = _read_json(fs.metadata_file)
        assert record.layer == "cloud"
        assert record.agent_card.description == "d2"
        assert registry[0]["layer"] == "cloud"
        assert registry[0]["updated_at"] == fs.get_updated_at("A", "O")
        assert record.updated_at >= before

    def test_delete_requires_matching_owner(self, fs):
        """TC-STORE-111 | 注销时 owner 不匹配则拒绝，记录与元数据都保留

        输入: alice 创建 A 后 delete("A", "O", owner="bob")，再用 owner="alice" 删除
        预期输出: 第一次 False 且记录仍在；第二次 True 且记录消失、元数据清空
        断言点: 两次返回值；第一次后 find_by_key 非空；第二次后为 None 且元数据文件为 []
        防回归: 若 owner 校验被删除，任意用户可注销他人 Agent，本用例失败
        """
        fs.create(_agent(), owner="alice")

        assert fs.delete("A", "O", owner="bob") is False
        assert fs.find_by_key("A", "O") is not None

        assert fs.delete("A", "O", owner="alice") is True
        assert fs.find_by_key("A", "O") is None
        assert _read_json(fs.metadata_file) == []


class TestSizeLimits:
    def test_save_rejects_oversized_payload(self, tmp_path):
        """TC-STORE-112 | 写入超过 max_file_size 时抛 ValueError 且不产生半截文件

        输入: max_file_size=10 的 FileStorage，create 一张 AgentCard
        预期输出: ValueError，消息含 "exceeds maximum allowed"
        断言点: 异常类型 + 消息；agentcard.json 不存在（校验先于写盘）；内存计数仍为 1
        防回归: 若大小校验放在写盘之后，超大文件已落地才报错，本用例失败
        """
        agent_file, metadata_file, tags_file = _paths(tmp_path)
        storage = FileStorage(agent_file, metadata_file, tags_file, max_file_size=10)

        with pytest.raises(ValueError, match="exceeds maximum allowed"):
            storage.create(_agent())

        assert not os.path.exists(agent_file)
        assert storage.count() == 1

    def test_load_skips_oversized_agents_file(self, tmp_path):
        """TC-STORE-113 | 启动加载时跳过超过 max_file_size 的持久化文件

        输入: agentcard.json 内容长度 > 5 字节，max_file_size=5
        预期输出: 不抛异常，registry 为空
        断言点: count() == 0 且 find_all() == []
        防回归: 若加载路径缺少大小上限，超大文件会把内存打满，本用例失败
        """
        agent_file, metadata_file, tags_file = _paths(tmp_path)
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{"name": "A"}], stream)
        storage = FileStorage(agent_file, metadata_file, tags_file, max_file_size=5)

        assert storage.count() == 0
        assert storage.find_all() == []

    def test_load_survives_stat_error(self, tmp_path, monkeypatch):
        """TC-STORE-114 | 读取文件大小时 OSError 只记录日志，不阻止服务启动

        输入: agentcard.json 存在但 os.path.getsize 抛 PermissionError
        预期输出: 构造成功，registry 为空
        断言点: count() == 0；构造未抛异常
        防回归: 若 OSError 未被捕获，权限异常的部署目录会让进程启动即崩，本用例失败
        """
        agent_file, metadata_file, tags_file = _paths(tmp_path)
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([], stream)

        def _raise(path):
            raise PermissionError("denied")

        monkeypatch.setattr(os.path, "getsize", _raise)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.count() == 0


class TestLoadDefensivePaths:
    def test_load_agents_rejects_non_list_document(self, paths):
        """TC-STORE-115 | agentcard.json 是对象而非数组时拒绝加载

        输入: agentcard.json 内容为 {"name": "A"}
        预期输出: registry 为空，无异常
        断言点: count() == 0；find_all() == []
        防回归: 若把 dict 当 list 迭代，会加载出伪卡片（遍历键名），本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump({"name": "A"}, stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.count() == 0
        assert storage.find_all() == []

    def test_load_agents_skips_bad_entries_and_keeps_good(self, paths):
        """TC-STORE-116 | 单条坏卡片被跳过，其余卡片正常加载

        输入: agentcard.json = [合法 A, {"nope": 1}]
        预期输出: 只有 A 进入 registry
        断言点: find_all 名称列表 == ["A"]；find_by_key("A","O") 非空
        防回归: 若单条解析异常向上冒泡，一条坏数据会让整个注册表无法加载，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }, {"nope": 1}], stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert [agent.name for agent in storage.find_all()] == ["A"]
        assert storage.find_by_key("A", "O") is not None

    def test_load_agents_survives_corrupt_json(self, paths):
        """TC-STORE-117 | agentcard.json 语法损坏时以空注册表启动

        输入: agentcard.json 内容为 "{not json"
        预期输出: 构造成功，registry 为空
        断言点: count() == 0
        防回归: 若 JSONDecodeError 未捕获，损坏文件会阻止服务启动，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            stream.write("{not json")

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.count() == 0

    def test_missing_registry_file_defaults_all_agents(self, paths):
        """TC-STORE-118 | 缺少元数据文件时所有卡片按 published/unknown 默认值接管

        输入: 只有 agentcard.json（含 A），无 agentregistry.json
        预期输出: A 的 status="published"、owner=None、tags=[]、layer=unknown、时间戳为空串
        断言点: AgentRecord 六个字段逐一断言
        防回归: 若默认值分支不写 _owner_map，find_by_owner(None) 行为会漂移，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        record = storage.find_by_key("A", "O")
        assert record.status == "published"
        assert record.owner is None
        assert record.tags == []
        assert record.layer == UNKNOWN_LAYER
        assert record.created_at == ""
        assert record.updated_at == ""

    def test_registry_non_list_document_is_ignored(self, paths):
        """TC-STORE-119 | agentregistry.json 为对象时忽略，且不写状态映射

        输入: 合法 agentcard.json + 内容为 {} 的 agentregistry.json
        预期输出: 卡片可读，find_by_key 返回默认 published，但 _status_map 为空
        断言点: 记录 status == "published"；len(_status_map) == 0
        防回归: 若把 dict 当列表迭代，键名会被当作 item['agent_name'] 触发 TypeError 洪泛，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            json.dump({}, stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.find_by_key("A", "O").status == "published"
        assert storage._status_map == {}
        assert [agent.name for agent in storage.find_by_status("published")] == ["A"]
        assert storage.find_by_status("registered") == []
        assert [agent.name for agent in storage.find_all(status="published")] == ["A"]

    def test_registry_corrupt_json_keeps_startup_alive(self, paths):
        """TC-STORE-120 | agentregistry.json 语法损坏时以空元数据启动

        输入: 合法 agentcard.json + 内容为 "[{oops" 的 agentregistry.json
        预期输出: 构造成功，_status_map 为空，卡片仍可读（status 默认 published）
        断言点: _status_map == {}；find_by_key 非空且 status == "published"
        防回归: 若元数据解析异常向上冒泡，元数据文件损坏会阻止服务启动，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            stream.write("[{oops")

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage._status_map == {}
        assert storage.find_by_key("A", "O").status == "published"

    def test_registry_entry_without_agent_name_is_skipped(self, paths):
        """TC-STORE-121 | 元数据条目缺少 agent_name 时跳过该条，其它条目照常加载

        输入: agentregistry.json = [{"organization": "O", "status": "registered"}, 合法 B 条目]
        预期输出: 只加载 B，且 B 的 status 为 "registered"
        断言点: len(_status_map) == 1；B 的 status == "registered"
        防回归: 若缺键条目被当作 ("", "") 键写入，会污染空名键位，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "B", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            json.dump([
                {"organization": "O", "status": "registered"},
                {"agent_name": "B", "organization": "O", "status": "registered", "layer": "edge"},
            ], stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert len(storage._status_map) == 1
        assert storage.find_by_key("B", "O").status == "registered"
        assert storage.find_by_key("B", "O").layer == "edge"

    def test_invalid_layer_is_normalized_and_rewritten(self, paths):
        """TC-STORE-122 | 元数据中的非法 layer 归一化为 unknown 并回写文件

        输入: agentregistry.json 中 layer 为 42（非字符串）
        预期输出: 读回 layer == "unknown"，且文件被重写为 layer "unknown"
        断言点: find_by_key 的 layer；重写后的元数据文件内容
        防回归: 若非法 layer 直接进入内存，后续 filter 比较会与存储值不一致，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            json.dump([{"agent_name": "A", "organization": "O", "status": "published", "layer": 42}],
                      stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.find_by_key("A", "O").layer == UNKNOWN_LAYER
        assert _read_json(metadata_file)[0]["layer"] == UNKNOWN_LAYER

    def test_missing_layer_field_triggers_migration(self, paths):
        """TC-STORE-123 | 元数据缺少 layer 字段时补齐并回写

        输入: agentregistry.json 条目不含 layer（历史格式）
        预期输出: 内存 layer 为 unknown，文件被重写为含 "layer": "unknown"
        断言点: find_by_key 的 layer；重写文件里出现了 layer 键且值为 unknown
        防回归: 若迁移写回被删除，每次启动都会重复迁移，且 layer 过滤结果不稳定，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump([{
                "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                "description": "d", "version": "1.0.0", "skills": [],
            }], stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            json.dump([{"agent_name": "A", "organization": "O", "status": "published"}], stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.find_by_key("A", "O").layer == UNKNOWN_LAYER
        assert _read_json(metadata_file)[0]["layer"] == UNKNOWN_LAYER


class TestTagEntities:
    def test_tag_list_rejects_non_list_document(self, paths):
        """TC-STORE-124 | tags.json 为对象时忽略标签列表

        输入: tags.json 内容为 {"tag_id": "x"}
        预期输出: 标签列表为空
        断言点: list_tags() == []；get_tag("x") is None
        防回归: 若 dict 被当作列表迭代，标签实体无法加载且键名会被当 item 传入 Tag，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(tags_file, 'w', encoding='utf-8') as stream:
            json.dump({"tag_id": "x"}, stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.list_tags() == []
        assert storage.get_tag("x") is None

    def test_tag_list_skips_bad_entries(self, paths):
        """TC-STORE-125 | 单条非法标签被跳过，合法标签正常加载

        输入: tags.json = [合法 tag t1, {"name": 123}（非法）]
        预期输出: 只加载 t1
        断言点: get_tag("t1") 的 name；len(list_tags()) == 1
        防回归: 若非法条目中断加载循环，后续合法标签会丢失，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(tags_file, 'w', encoding='utf-8') as stream:
            json.dump([{"tag_id": "t1", "name": "prod", "created_at": "c", "updated_at": "u"},
                       {"name": 123}], stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert len(storage.list_tags()) == 1
        assert storage.get_tag("t1").name == "prod"

    def test_tag_list_survives_corrupt_json(self, paths):
        """TC-STORE-126 | tags.json 语法损坏时以空标签列表启动

        输入: tags.json 内容为 "not json"
        预期输出: 标签列表为空，无异常
        断言点: list_tags() == []
        防回归: 若解析异常未捕获，标签文件损坏会阻止服务启动，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        with open(tags_file, 'w', encoding='utf-8') as stream:
            stream.write("not json")

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.list_tags() == []

    def test_create_tag_persists_and_rejects_duplicates(self, fs):
        """TC-STORE-127 | 创建标签落盘 tags.json，重复 id 与重复 name 均被拒绝

        输入: create_tag(t1/name=prod)；再 create_tag(同 id)；再 create_tag(t2/name=prod)
        预期输出: 第一次 True；后两次 False
        断言点: 三次返回值；tags.json 中仅 1 条且四字段与内存一致；get_tag_by_name("prod") 命中 t1
        防回归: 若名称唯一性检查被删除，两个 id 可注册同名标签，本用例失败
        """
        tag = Tag(tag_id="t1", name="prod", created_at="c", updated_at="u")

        assert fs.create_tag(tag) is True
        assert fs.create_tag(Tag(tag_id="t1", name="other")) is False
        assert fs.create_tag(Tag(tag_id="t2", name="prod")) is False

        on_disk = _read_json(fs.tags_file)
        assert on_disk == [{"tag_id": "t1", "name": "prod", "created_at": "c", "updated_at": "u"}]
        assert fs.get_tag("t1") is tag
        assert fs.get_tag_by_name("prod") is tag
        assert fs.get_tag_by_name("missing") is None

    def test_update_tag_rejects_missing_and_conflicting(self, fs):
        """TC-STORE-128 | 更新标签：不存在返回 False，改名冲突返回 False

        输入: 建 t1/prod、t2/edge；update_tag("nope", ...)；update_tag("t2", name="prod")；
              update_tag("t2", name="staging")
        预期输出: False、False、True；成功后 updated_at 被刷新且落盘
        断言点: 三次返回值；读取 t2 的 name 与 updated_at（较原值变化）；tags.json 同步
        防回归: 若冲突检查条件写成 `existing_tag_id == tag_id`，同名校验失效，本用例失败
        """
        fs.create_tag(Tag(tag_id="t1", name="prod", created_at="c", updated_at="u"))
        fs.create_tag(Tag(tag_id="t2", name="edge", created_at="c", updated_at="u"))

        assert fs.update_tag("nope", Tag(tag_id="nope", name="x")) is False
        assert fs.update_tag("t2", Tag(tag_id="t2", name="prod")) is False
        assert fs.update_tag("t2", Tag(tag_id="t2", name="staging",
                                      created_at="c", updated_at="u")) is True

        updated = fs.get_tag("t2")
        assert updated.name == "staging"
        assert updated.updated_at != "u"
        assert {entry["name"] for entry in _read_json(fs.tags_file)} == {"prod", "staging"}

    def test_delete_tag_persists_removal(self, fs):
        """TC-STORE-129 | 删除标签：不存在返回 False，存在则从内存与文件中移除

        输入: 建 t1/prod 后 delete_tag("t1")、再次 delete_tag("t1")
        预期输出: 第一次 True，第二次 False；tags.json 变为 []
        断言点: 两次返回值；list_tags() == []；tags.json 内容 == []
        防回归: 若删除后未调用 _save_tag_list，重启会复活已删除标签，本用例失败
        """
        fs.create_tag(Tag(tag_id="t1", name="prod", created_at="c", updated_at="u"))

        assert fs.delete_tag("t1") is True
        assert fs.delete_tag("t1") is False

        assert fs.list_tags() == []
        assert _read_json(fs.tags_file) == []

    def test_agent_tags_binding_and_lookup(self, fs):
        """TC-STORE-130 | 标签绑定：写入后可按标签反查，未注册 Agent 更新返回 False

        输入: 建 A，update_agent_tags("A","O",["prod"])，update_agent_tags("ghost",...)；
              find_by_tag("prod")、get_agent_tags("A","O")
        预期输出: 前者 True、后者 False；find_by_tag 返回 [A]；get_agent_tags == ["prod"]
        断言点: 两次返回值；反查名称列表；标签列表；元数据文件中的 tags 字段
        防回归: 若标签绑定写入 _agents 之外的结构而未落盘，重启后标签丢失，本用例失败
        """
        fs.create(_agent("A", "O"))

        assert fs.update_agent_tags("A", "O", ["prod"]) is True
        assert fs.update_agent_tags("ghost", "O", ["prod"]) is False

        assert [agent.name for agent in fs.find_by_tag("prod")] == ["A"]
        assert fs.get_agent_tags("A", "O") == ["prod"]
        assert fs.get_agent_tags("ghost", "O") == []
        assert _read_json(fs.metadata_file)[0]["tags"] == ["prod"]


class TestLookupLifecycle:
    def test_find_by_name_is_case_insensitive_substring(self, fs):
        """TC-STORE-131 | find_by_name 按大小写不敏感子串匹配，空串不匹配任何卡片

        输入: 建 Alpha_Agent / beta；依次查询 "alpha"、"AGENT"、""、"zzz"
        预期输出: ["Alpha_Agent"]、["Alpha_Agent"]、[]、[]
        断言点: 四次查询的名称列表
        防回归: 若 lower() 被去掉，大写改名后按小写搜索会漏召，本用例失败
        """
        fs.create(_agent("Alpha_Agent", "o1"))
        fs.create(_agent("beta", "o2"))

        assert [agent.name for agent in fs.find_by_name("alpha")] == ["Alpha_Agent"]
        assert [agent.name for agent in fs.find_by_name("AGENT")] == ["Alpha_Agent"]
        assert fs.find_by_name("") == []
        assert fs.find_by_name("zzz") == []

    def test_find_by_organization_requires_non_empty_match(self, fs):
        """TC-STORE-132 | find_by_organization 精确匹配组织，空串不返回任何卡片

        输入: 建 (A, o1)、(B, o2)；查询 "o1"、"O1"、""
        预期输出: ["A"]、[]、[]
        断言点: 三次查询的名称列表（大小写敏感、空串短路）
        防回归: 若空串条件被删除，空组织查询会返回全量卡片，本用例失败
        """
        fs.create(_agent("A", "o1"))
        fs.create(_agent("B", "o2"))

        assert [agent.name for agent in fs.find_by_organization("o1")] == ["A"]
        assert fs.find_by_organization("O1") == []
        assert fs.find_by_organization("") == []

    def test_update_status_persists_and_reports_unknown_agent(self, fs):
        """TC-STORE-133 | update_status 落盘新状态；未注册 Agent 返回 False

        输入: 建 A（published），update_status("A","O","registered")、update_status("X","O",...)
        预期输出: True 与 False；元数据文件中 A 的 status 变为 registered
        断言点: 两次返回值；find_by_key.status；落盘 status
        防回归: 若状态更新只改内存不落盘，重启后审核状态回退，本用例失败
        """
        fs.create(_agent())

        assert fs.update_status("A", "O", "registered") is True
        assert fs.update_status("X", "O", "registered") is False

        assert fs.find_by_key("A", "O").status == "registered"
        assert _read_json(fs.metadata_file)[0]["status"] == "registered"

    def test_update_rejects_unknown_agent_and_primary_key_change(self, fs):
        """TC-STORE-134 | update 对不存在的卡片返回 False，对改主键抛 ValueError

        输入: update("ghost", "O", 合法卡)；再建 A 后 update 载荷 name="B"
        预期输出: False；ValueError（消息含 "Cannot change primary key"）
        断言点: 第一次返回值；异常类型 + 消息；A 的 description 未被改动
        防回归: 若主键变更校验被删除，改名会静默生成"幽灵主键"记录，本用例失败
        """
        payload = {"name": "A", "provider": {"organization": "O", "url": "https://example.test"},
                   "description": "d", "version": "1.0.0", "skills": []}

        assert fs.update("ghost", "O", payload) is False

        fs.create(_agent(desc="original"))
        with pytest.raises(ValueError, match="Cannot change primary key"):
            fs.update("A", "O", {**payload, "name": "B", "description": "renamed"})

        assert fs.find_by_key("A", "O").agent_card.description == "original"

    def test_delete_unknown_agent_returns_false(self, fs):
        """TC-STORE-135 | 注销不存在的 Agent 返回 False 且不改动任何映射

        输入: delete("ghost", "O")
        预期输出: False；不产生落盘文件
        断言点: 返回值为 False；metadata 文件不存在
        防回归: 若 delete 对未知键继续走 _save 流程，会写出空元数据覆盖其他组件，本用例失败
        """
        assert fs.delete("ghost", "O") is False
        assert not os.path.exists(fs.metadata_file)

    def test_created_and_updated_at_accessors(self, fs):
        """TC-STORE-136 | get_created_at / get_updated_at 返回落盘时间戳，未知键返回空串

        输入: 建 A 后读取两个时间戳；再读未知键
        预期输出: 已存在时为非空 ISO 字符串且与元数据文件一致；未知键为 ""
        断言点: 与落盘值逐字段相等；未知键空串
        防回归: 若键未 strip（空格导致查不到），时间戳恒为空，本用例失败
        """
        fs.create(_agent())
        registry = _read_json(fs.metadata_file)[0]

        assert fs.get_created_at("A", "O") == registry["created_at"]
        assert fs.get_updated_at("A", "O") == registry["updated_at"]
        assert fs.get_created_at(" A ", " O ") == registry["created_at"]
        assert fs.get_created_at("ghost", "O") == ""
        assert fs.get_updated_at("ghost", "O") == ""

    def test_init_creates_parent_directory_and_defaults_files(self, tmp_path):
        """TC-STORE-137 | init 建立数据目录并按默认命名派生元数据/标签文件

        输入: FileStorage.init({"file.path": <tmp>/nested/data/agentcard.json})
        预期输出: 目录被创建；metadata_file=同目录 agentregistry.json，tags_file=同目录 tags.json
        断言点: 目录存在；两个派生路径的 basename；max_file_size 默认 100MiB
        防回归: 若 init 不再建目录，首次创建卡片会因目录缺失失败，本用例失败
        """
        target = tmp_path / "nested" / "data" / "agentcard.json"

        storage = FileStorage.init({"file.path": str(target)})

        assert target.parent.is_dir()
        assert storage.file_path == str(target)
        assert os.path.basename(storage.metadata_file) == "agentregistry.json"
        assert os.path.basename(storage.tags_file) == "tags.json"
        assert os.path.dirname(storage.metadata_file) == str(target.parent)
        assert storage.max_file_size == 100 * 1024 * 1024

    def test_create_duplicate_is_rejected_without_extra_write(self, fs):
        """TC-STORE-138 | 重复创建同一主键返回 False，不产生第二条记录

        输入: create(A/O) 两次
        预期输出: True 后 False；agentcard.json 中只有 1 条
        断言点: 两次返回值；落盘条数；count() == 1
        防回归: 若重复创建覆盖已有卡片，owner/created_at 会被重置，本用例失败
        """
        assert fs.create(_agent()) is True
        assert fs.create(_agent(desc="different")) is False

        assert fs.count() == 1
        assert len(_read_json(fs.file_path)) == 1
        assert fs.find_by_key("A", "O").agent_card.description == "d"

    def test_check_connection_leaves_no_probe_file(self, tmp_path):
        """TC-STORE-139 | 启动预检写入探针文件后清理，不残留临时文件

        输入: 对空目录下的 FileStorage 调用 check_connection()
        预期输出: 无异常；目录中不存在 .precheck-* 文件
        断言点: 返回 None；glob(".precheck-*") 为空；目录存在
        防回归: 若 finally 中的 unlink 被删除，每次启动都会留下探针文件，本用例失败
        """
        target = tmp_path / "fresh" / "agentcard.json"
        storage = FileStorage(str(target), str(tmp_path / "fresh" / "meta.json"),
                              str(tmp_path / "fresh" / "tags.json"))

        assert storage.check_connection() is None
        assert list((tmp_path / "fresh").glob(".precheck-*")) == []
        assert target.parent.is_dir()

    def test_close_flushes_state_to_disk(self, fs):
        """TC-STORE-140 | close 把内存状态刷盘，磁盘内容与内存一致

        输入: 建 A 并绑定标签后调用 close()
        预期输出: 返回 None；agentcard.json / 元数据文件可读且与内存一致
        断言点: close 返回值；落盘卡片名与标签
        防回归: 若 close 不再 _save，批量修改后直接停机将丢失最后一批写入，本用例失败
        """
        fs.create(_agent("A", "O"))
        fs.update_agent_tags("A", "O", ["prod"])

        assert fs.close() is None

        assert [card["name"] for card in _read_json(fs.file_path)] == ["A"]
        assert _read_json(fs.metadata_file)[0]["tags"] == ["prod"]

    def test_agent_missing_from_metadata_gets_layer_backfilled(self, paths):
        """TC-STORE-141 | 卡片存在但元数据无对应条目时补齐 layer 并回写

        输入: agentcard.json 含 A、B；agentregistry.json 只有 A 的条目
        预期输出: B 的 layer 归一化为 unknown，元数据文件被重写并包含 B 条目
        断言点: B 的 status 与 layer；重写文件中出现 B 且 layer 为 unknown
        防回归: 若缺失键的 layer 补丁被删除，按 layer 过滤时 B 永远查不到，本用例失败
        """
        agent_file, metadata_file, tags_file = paths
        cards = [{
            "name": name, "provider": {"organization": "O", "url": "https://example.test"},
            "description": "d", "version": "1.0.0", "skills": [],
        } for name in ("A", "B")]
        with open(agent_file, 'w', encoding='utf-8') as stream:
            json.dump(cards, stream)
        with open(metadata_file, 'w', encoding='utf-8') as stream:
            json.dump([{"agent_name": "A", "organization": "O", "status": "published", "layer": "edge"}],
                      stream)

        storage = FileStorage(agent_file, metadata_file, tags_file)

        assert storage.find_by_key("B", "O").layer == UNKNOWN_LAYER
        rewritten = {entry["agent_name"]: entry for entry in _read_json(metadata_file)}
        assert rewritten["A"]["layer"] == "edge"
        assert rewritten["B"]["layer"] == UNKNOWN_LAYER
        assert rewritten["B"]["status"] == "published"

    def test_update_applies_status_from_payload(self, fs):
        """TC-STORE-142 | update 载荷中的 status 应被采用

        输入: 创建 A 后 update 同一张卡，载荷含 status="registered"
        预期输出: 返回 True，且 find_by_key 的 status 变为 "registered"
        断言点: 返回值；读回 status（对应 file_storage.update 中的 status 分支）
        防回归: 若实现又回到"先 Parse 整个载荷"，带 status 的更新会抛
               ParseError（proto 无 status 字段），本用例失败
        """
        fs.create(_agent())

        assert fs.update("A", "O", {
            "name": "A", "provider": {"organization": "O", "url": "https://example.test"},
            "description": "d", "version": "1.0.0", "skills": [], "status": "registered",
        }) is True
        assert fs.find_by_key("A", "O").status == "registered"
