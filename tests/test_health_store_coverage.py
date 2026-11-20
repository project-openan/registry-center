# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Heartbeat storage coverage tests (agent_registry/health/store.py).

Two backends are covered:

* ``MemoryHeartbeatStore`` — real in-process instance, no doubles.
* ``SqlHeartbeatStore`` — driven through a throw-away in-memory SQLite backend that
  implements the two-method contract the store relies on (``_execute_write`` /
  ``_execute_read_one`` / ``_execute_read_all`` / ``ensure_index`` / ``param_ph``).
  Real SQL runs, so the assertions read the persisted rows back instead of trusting
  a mock's call log.

No network, no sleep, no shared global state: every instance is created inside the
test that uses it and thrown away afterwards.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agent_registry.health.state import HealthState, HealthStatus
from agent_registry.health.store import (
    HISTORY_MEMORY_MAXLEN,
    MemoryHeartbeatStore,
    SqlHeartbeatStore,
    _from_iso,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# SQLite-backed stand-in for the main storage backend
# --------------------------------------------------------------------------

class _SqliteBackend:
    """Minimal StorageBackend surface used by SqlHeartbeatStore, backed by SQLite.

    ``param_ph`` is ``?`` so the store's own SQL strings are executed verbatim by
    sqlite3 — an assertion that reads rows back therefore proves the store really
    persisted what it claims.
    """

    param_ph = '?'

    def __init__(self):
        self.conn = sqlite3.connect(':memory:')

    def _execute_write(self, sql, params=()):
        cursor = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cursor.rowcount

    def _execute_read_one(self, sql, params=()):
        return self.conn.execute(sql, tuple(params)).fetchone()

    def _execute_read_all(self, sql, params=()):
        return self.conn.execute(sql, tuple(params)).fetchall()

    def ensure_index(self, create_sql, fallback_sql):
        try:
            self.conn.execute(create_sql)
        except sqlite3.Error:  # pragma: no cover - sqlite accepts both forms
            self.conn.execute(fallback_sql)
        self.conn.commit()

    def close(self):
        self.conn.close()


class _RecordingBackend:
    """Backend without ``param_ph`` that records the SQL it is handed."""

    def __init__(self):
        self.writes = []
        self.reads = []

    def _execute_write(self, sql, params=()):
        self.writes.append((' '.join(sql.split()), tuple(params)))
        return 1

    def _execute_read_one(self, sql, params=()):
        self.reads.append((' '.join(sql.split()), tuple(params)))
        return None

    def _execute_read_all(self, sql, params=()):
        self.reads.append((' '.join(sql.split()), tuple(params)))
        return []

    def ensure_index(self, create_sql, fallback_sql):
        return None


@pytest.fixture
def sqlite_backend():
    backend = _SqliteBackend()
    yield backend
    backend.close()


@pytest.fixture
def sql_store(sqlite_backend):
    return SqlHeartbeatStore(sqlite_backend)


# --------------------------------------------------------------------------
# MemoryHeartbeatStore
# --------------------------------------------------------------------------

class TestMemoryHeartbeatStore:
    def test_first_heartbeat_creates_healthy_state(self):
        """TC-STORE-001 | 首次心跳创建 HEALTHY 记录且无前态

        输入: record_heartbeat("agent-a", "org-1", T0)
        预期输出: (None, HealthState(name=agent-a, org=org-1, status=HEALTHY,
                                   last_heartbeat_at=T0, status_changed_at=T0))
        断言点: 前态为 None；get() 读回状态对象且四个字段逐一相等；list_monitored 长度为 1
        防回归: 若首次心跳误报前态、或漏写 _states，本用例失败
        """
        store = MemoryHeartbeatStore()

        previous, state = store.record_heartbeat("agent-a", "org-1", T0)

        assert previous is None
        assert state == HealthState(name="agent-a", organization="org-1",
                                    last_heartbeat_at=T0, status=HealthStatus.HEALTHY,
                                    status_changed_at=T0)
        assert store.get("agent-a", "org-1") is state
        assert store.list_monitored() == [state]

    def test_repeat_heartbeat_keeps_status_changed_at(self):
        """TC-STORE-002 | 健康态重复心跳只刷新 last_heartbeat_at

        输入: 先 record_heartbeat(..., T0)，再 record_heartbeat(..., T0+30s)
        预期输出: 第二次前态为 HEALTHY；status_changed_at 仍为 T0，last_heartbeat_at 为 T0+30s
        断言点: 前态 == HEALTHY；两个时间戳字段分别取自"上次变更时刻"与"本次心跳时刻"
        防回归: 若收到心跳就重置 status_changed_at，健康时长统计被清空，本用例失败
        """
        store = MemoryHeartbeatStore()
        store.record_heartbeat("agent-a", "org-1", T0)
        later = T0 + timedelta(seconds=30)

        previous, state = store.record_heartbeat("agent-a", "org-1", later)

        assert previous is HealthStatus.HEALTHY
        assert state.last_heartbeat_at == later
        assert state.status_changed_at == T0
        assert state.status is HealthStatus.HEALTHY

    def test_recovery_transition_records_change_time(self):
        """TC-STORE-003 | 从 OFFLINE 恢复为 HEALTHY 时更新 status_changed_at

        输入: 心跳 -> update_status(OFFLINE, T0) -> record_heartbeat(T0+90s)
        预期输出: 前态 OFFLINE，新状态 HEALTHY，status_changed_at == T0+90s
        断言点: 前态等于被置入的 OFFLINE；新状态 HEALTHY；变更时刻等于本次心跳时刻
        防回归: 若恢复路径忘记改写 status_changed_at，恢复耗时会算错，本用例失败
        """
        store = MemoryHeartbeatStore()
        store.record_heartbeat("agent-a", "org-1", T0)
        assert store.update_status("agent-a", "org-1", HealthStatus.OFFLINE, T0 + timedelta(seconds=60)) is True
        recovered = T0 + timedelta(seconds=90)

        previous, state = store.record_heartbeat("agent-a", "org-1", recovered)

        assert previous is HealthStatus.OFFLINE
        assert state.status is HealthStatus.HEALTHY
        assert state.status_changed_at == recovered
        assert store.get("agent-a", "org-1").status is HealthStatus.HEALTHY

    def test_update_status_unknown_agent_returns_false(self):
        """TC-STORE-004 | 更新未监控 Agent 的状态返回 False 且不建记录

        输入: update_status("ghost", "org-1", OFFLINE, T0)（该键从未心跳）
        预期输出: False；get("ghost", "org-1") 仍为 None
        断言点: 返回值为 False（而非抛异常/None）；未产生幽灵状态记录
        防回归: 若 update_status 用 setdefault 建条目，会凭空监控未注册 Agent，本用例失败
        """
        store = MemoryHeartbeatStore()

        assert store.update_status("ghost", "org-1", HealthStatus.OFFLINE, T0) is False
        assert store.get("ghost", "org-1") is None
        assert store.list_monitored() == []

    def test_update_status_known_agent_sets_status_and_time(self):
        """TC-STORE-005 | 已监控 Agent 的状态更新写入状态与变更时刻

        输入: 心跳建立记录后 update_status("agent-a", "org-1", SUSPECT, T0+70s)
        预期输出: True；读回状态 SUSPECT，status_changed_at == T0+70s，last_heartbeat_at 不变
        断言点: 返回值 True；状态枚举、变更时刻、未受影响的心跳时刻逐一断言
        防回归: 若更新只改状态不改时刻（或反之），阈值判定会漂移，本用例失败
        """
        store = MemoryHeartbeatStore()
        store.record_heartbeat("agent-a", "org-1", T0)
        changed_at = T0 + timedelta(seconds=70)

        assert store.update_status("agent-a", "org-1", HealthStatus.SUSPECT, changed_at) is True

        state = store.get("agent-a", "org-1")
        assert state.status is HealthStatus.SUSPECT
        assert state.status_changed_at == changed_at
        assert state.last_heartbeat_at == T0

    def test_remove_is_scoped_and_idempotent(self):
        """TC-STORE-006 | remove 只删除指定组织下的记录，重复调用不报错

        输入: 建立 (agent-a, org-1) 与 (agent-a, org-2) 两条记录，remove(agent-a, org-1) 两次
        预期输出: org-1 记录消失，org-2 记录保留；第二次 remove 无异常
        断言点: get(org-1) 为 None；get(org-2) 仍返回原状态；list_monitored 只剩 1 条
        防回归: 若 remove 丢掉 organization（按 name 单键删除/误删同名的其他组织），本用例失败
        """
        store = MemoryHeartbeatStore()
        store.record_heartbeat("agent-a", "org-1", T0)
        store.record_heartbeat("agent-a", "org-2", T0)

        store.remove("agent-a", "org-1")
        store.remove("agent-a", "org-1")

        assert store.get("agent-a", "org-1") is None
        assert store.get("agent-a", "org-2") is not None
        assert len(store.list_monitored()) == 1

    def test_list_history_filters_and_orders_newest_first(self):
        """TC-STORE-007 | 历史按最新在前返回，并支持 name/organization/limit 过滤

        输入: 依次追加 4 条历史：
              (a, o1, HEALTHY->SUSPECT 于 T0), (b, o1, HEALTHY->OFFLINE 于 T0+1s),
              (a, o2, ... 于 T0+2s), (a, o1, SUSPECT->OFFLINE 于 T0+3s)
        预期输出: 全量历史 = [a/o1 T0+3s, a/o2 T0+2s, b/o1 T0+1s, a/o1 T0]
              过滤 name="a" = 上述第 1、2、4 条（新→旧）
              过滤 organization="o1" = 上述第 1、3、4 条
              过滤 name="a" 且 limit=1 = 仅 [a/o1 T0+3s]
        断言点: 每条历史的 name/organization/previous_health_status/health_status/changed_at 全字段断言，
                顺序、过滤与截断逐一比对
        防回归: 若 appendleft 改成 append（顺序反了）、或过滤条件被短路（只按 name 过滤），本用例失败
        """
        store = MemoryHeartbeatStore()
        store.append_history("a", "o1", HealthStatus.HEALTHY, HealthStatus.SUSPECT, T0)
        store.append_history("b", "o1", HealthStatus.HEALTHY, HealthStatus.OFFLINE, T0 + timedelta(seconds=1))
        store.append_history("a", "o2", HealthStatus.HEALTHY, HealthStatus.SUSPECT, T0 + timedelta(seconds=2))
        store.append_history("a", "o1", HealthStatus.SUSPECT, HealthStatus.OFFLINE, T0 + timedelta(seconds=3))

        everything = store.list_history()
        assert [(e["name"], e["organization"], e["health_status"]) for e in everything] == [
            ("a", "o1", "offline"), ("a", "o2", "suspect"), ("b", "o1", "offline"), ("a", "o1", "suspect"),
        ]
        assert everything[0] == {
            "name": "a", "organization": "o1",
            "previous_health_status": "suspect", "health_status": "offline",
            "changed_at": (T0 + timedelta(seconds=3)).isoformat(),
        }
        assert [(e["name"], e["organization"]) for e in store.list_history(name="a")] == [
            ("a", "o1"), ("a", "o2"), ("a", "o1"),
        ]
        assert [(e["name"], e["organization"]) for e in store.list_history(organization="o1")] == [
            ("a", "o1"), ("b", "o1"), ("a", "o1"),
        ]
        assert len(store.list_history(name="a", organization="o1", limit=1)) == 1
        assert store.list_history(name="a", organization="o1", limit=1)[0]["changed_at"] == (
            T0 + timedelta(seconds=3)).isoformat()

    def test_list_history_returns_copies(self):
        """TC-STORE-008 | list_history 返回副本，调用方修改不污染内部历史

        输入: 追加 1 条历史后读取，修改返回 dict 的 health_status 字段
        预期输出: 再次读取仍是 'suspect'（原始值）
        断言点: 二次读取的 health_status 与首次读取的原始值一致
        防回归: 若返回 dict 引用而非常量副本，审计历史可被调用方篡改，本用例失败
        """
        store = MemoryHeartbeatStore()
        store.append_history("a", "o1", HealthStatus.HEALTHY, HealthStatus.SUSPECT, T0)

        first = store.list_history()[0]
        first["health_status"] = "tampered"

        assert store.list_history()[0]["health_status"] == "suspect"

    def test_history_ring_buffer_is_bounded(self):
        """TC-STORE-009 | 内存历史受 HISTORY_MEMORY_MAXLEN 限制，最旧记录被淘汰

        输入: 连续追加 HISTORY_MEMORY_MAXLEN + 5 条历史（第 i 条 changed_at=T0+i 秒）
        预期输出: 可查询历史恰好 HISTORY_MEMORY_MAXLEN 条，最新一条为第 505 条，第 1..5 条被淘汰
        断言点: 长度等于上限；首位是最后追加的 changed_at；末位是第 6 条而非第 1 条
        防回归: 若 deque 的 maxlen 被移除（无界增长导致内存泄漏），本用例失败
        """
        store = MemoryHeartbeatStore()
        total = HISTORY_MEMORY_MAXLEN + 5
        for index in range(total):
            store.append_history("a", "o1", HealthStatus.HEALTHY, HealthStatus.SUSPECT,
                                 T0 + timedelta(seconds=index))

        history = store.list_history(limit=total)

        assert len(history) == HISTORY_MEMORY_MAXLEN
        assert history[0]["changed_at"] == (T0 + timedelta(seconds=total - 1)).isoformat()
        assert history[-1]["changed_at"] == (T0 + timedelta(seconds=5)).isoformat()

    def test_close_is_noop_and_keeps_state(self):
        """TC-STORE-010 | 内存后端的 close 不销毁状态（重启前仍可读）

        输入: 建立记录后调用 close()
        预期输出: close 返回 None，get 仍返回原状态
        断言点: 返回值为 None；关闭后状态与历史仍可读
        防回归: 若 close 清空 _states，优雅停机前的最后一次查询会丢状态，本用例失败
        """
        store = MemoryHeartbeatStore()
        store.record_heartbeat("agent-a", "org-1", T0)
        store.append_history("agent-a", "org-1", HealthStatus.HEALTHY, HealthStatus.SUSPECT, T0)

        assert store.close() is None
        assert store.get("agent-a", "org-1").status is HealthStatus.HEALTHY
        assert len(store.list_history()) == 1


# --------------------------------------------------------------------------
# SqlHeartbeatStore
# --------------------------------------------------------------------------

class TestSqlHeartbeatStore:
    def test_ensure_table_creates_tables_and_index(self, sqlite_backend):
        """TC-STORE-020 | 初始化建表：agent_health / agent_health_history + 状态索引

        输入: SqlHeartbeatStore(sqlite_backend)，backend 为内存 SQLite
        预期输出: 两张表存在；agent_health 主键为 (agent_name, organization)；
              idx_agent_health_status 与 idx_agent_health_history_agent 索引存在
        断言点: sqlite_master 查得的表名集合、agent_health 的列序、索引名集合逐一断言
        防回归: 若表名/列序被改动（SELECT 按下标取值会错位）或漏建索引，本用例失败
        """
        SqlHeartbeatStore(sqlite_backend)

        tables = {row[0] for row in sqlite_backend._execute_read_all(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {row[0] for row in sqlite_backend._execute_read_all(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        columns = [row[1] for row in sqlite_backend._execute_read_all(
            'PRAGMA table_info(agent_health)')]

        assert tables == {'agent_health', 'agent_health_history'}
        assert columns == ['agent_name', 'organization', 'last_heartbeat_at', 'status', 'status_changed_at']
        assert 'idx_agent_health_status' in indexes
        assert 'idx_agent_health_history_agent' in indexes

    def test_first_heartbeat_inserts_row(self, sql_store, sqlite_backend):
        """TC-STORE-021 | SQL 后端首次心跳写入 HEALTHY 行，读回时间戳一致

        输入: record_heartbeat("agent-a", "org-1", T0)
        预期输出: 返回 (None, HEALTHY 状态)；agent_health 恰好 1 行，时间戳为 T0 的 ISO 串
        断言点: 前态 None；状态对象字段；直接查表得到的 5 列与原值逐列相等
        防回归: 若 INSERT 列序与 VALUES 错位（organization/时间戳互换），查表断言失败
        """
        previous, state = sql_store.record_heartbeat("agent-a", "org-1", T0)

        row = sqlite_backend._execute_read_one(
            "SELECT agent_name, organization, last_heartbeat_at, status, status_changed_at FROM agent_health")
        assert previous is None
        assert state == HealthState("agent-a", "org-1", T0, HealthStatus.HEALTHY, T0)
        assert row == ("agent-a", "org-1", T0.isoformat(), "healthy", T0.isoformat())

    def test_repeat_heartbeat_keeps_previous_change_time(self, sql_store, sqlite_backend):
        """TC-STORE-022 | SQL 后端健康态重复心跳保留原 status_changed_at

        输入: 心跳 T0 后再次 record_heartbeat(..., T0+30s)
        预期输出: 前态 HEALTHY；status_changed_at 仍为 T0；库中该行的两个时间戳分别为 T0+30s / T0
        断言点: 前态枚举；返回对象字段；查表得到的 last_heartbeat_at 与 status_changed_at
        防回归: 若重复心跳把 status_changed_at 覆盖成当前时间，健康时长被清零，本用例失败
        """
        sql_store.record_heartbeat("agent-a", "org-1", T0)
        later = T0 + timedelta(seconds=30)

        previous, state = sql_store.record_heartbeat("agent-a", "org-1", later)

        row = sqlite_backend._execute_read_one(
            "SELECT last_heartbeat_at, status, status_changed_at FROM agent_health")
        assert previous is HealthStatus.HEALTHY
        assert state.status_changed_at == T0
        assert row == (later.isoformat(), "healthy", T0.isoformat())

    def test_offline_agent_recovering_is_persisted(self, sql_store, sqlite_backend):
        """TC-STORE-023 | SQL 后端 OFFLINE 恢复：状态与变更时刻同时落库

        输入: 心跳 T0 -> update_status(OFFLINE, T0+60s) -> record_heartbeat(T0+90s)
        预期输出: 前态 OFFLINE，新状态 HEALTHY，status_changed_at == T0+90s
        断言点: update_status 返回 True；前态枚举；查表得到的 status 与 status_changed_at
        防回归: 若恢复路径只更新 last_heartbeat_at 而不改 status，Agent 会永远离线，本用例失败
        """
        sql_store.record_heartbeat("agent-a", "org-1", T0)
        assert sql_store.update_status("agent-a", "org-1", HealthStatus.OFFLINE,
                                       T0 + timedelta(seconds=60)) is True
        recovered = T0 + timedelta(seconds=90)

        previous, state = sql_store.record_heartbeat("agent-a", "org-1", recovered)

        row = sqlite_backend._execute_read_one(
            "SELECT status, status_changed_at FROM agent_health")
        assert previous is HealthStatus.OFFLINE
        assert state.status is HealthStatus.HEALTHY
        assert row == ("healthy", recovered.isoformat())

    def test_get_returns_none_for_unknown_and_state_for_known(self, sql_store):
        """TC-STORE-024 | SQL 后端 get：未知返回 None，已存在时按行还原状态

        输入: 空库调用 get("ghost","org-1")；写入 (agent-a, org-1) 后再 get
        预期输出: 先 None；后返回 HealthState，时间戳由 ISO 串还原为带时区 datetime
        断言点: 未知为 None；已知状态的 name/org/status 与两个时间戳逐一相等
        防回归: 若 _row_to_state 不解析时间戳（返回 str）或列下标错位，本用例失败
        """
        assert sql_store.get("ghost", "org-1") is None
        sql_store.record_heartbeat("agent-a", "org-1", T0)

        state = sql_store.get("agent-a", "org-1")

        assert state == HealthState("agent-a", "org-1", T0, HealthStatus.HEALTHY, T0)
        assert state.last_heartbeat_at == _from_iso(T0.isoformat())

    def test_list_monitored_returns_all_rows(self, sql_store):
        """TC-STORE-025 | SQL 后端 list_monitored 返回全部被监控 Agent

        输入: 写入 (a, o1) 与 (b, o2) 两条心跳
        预期输出: 两条 HealthState，名称集合 {a, b}，状态均为 HEALTHY
        断言点: 长度；名称集合；每条状态枚举
        防回归: 若查询漏掉 organization 列或多表连接错误导致漏行，本用例失败
        """
        sql_store.record_heartbeat("a", "o1", T0)
        sql_store.record_heartbeat("b", "o2", T0 + timedelta(seconds=1))

        states = sql_store.list_monitored()

        assert len(states) == 2
        assert {state.name for state in states} == {"a", "b"}
        assert {state.organization for state in states} == {"o1", "o2"}
        assert all(state.status is HealthStatus.HEALTHY for state in states)

    def test_update_status_uses_rowcount(self, sql_store, sqlite_backend):
        """TC-STORE-026 | SQL 后端 update_status 以 UPDATE 影响行数判定成功

        输入: 先对未记录 Agent 调用 update_status；写入后再次调用
        预期输出: 第一次 False（0 行受影响），第二次 True（1 行受影响）
        断言点: 两次返回值；查得的 status 与 status_changed_at 为新值
        防回归: 若实现写成恒返回 True（不比较 rowcount），未监控 Agent 会被误判为已更新，本用例失败
        """
        assert sql_store.update_status("ghost", "o1", HealthStatus.OFFLINE, T0) is False

        sql_store.record_heartbeat("agent-a", "o1", T0)
        changed_at = T0 + timedelta(seconds=120)
        assert sql_store.update_status("agent-a", "o1", HealthStatus.SUSPECT, changed_at) is True

        assert sqlite_backend._execute_read_one(
            "SELECT status, status_changed_at FROM agent_health") == ("suspect", changed_at.isoformat())

    def test_remove_deletes_only_matching_row(self, sql_store, sqlite_backend):
        """TC-STORE-027 | SQL 后端 remove 只删除 (agent_name, organization) 匹配的行

        输入: 写入 (a, o1)、(a, o2) 后 remove("a", "o1")
        预期输出: (a, o1) 行消失，(a, o2) 行保留
        断言点: 查表得到的剩余行集合为 {(a, o2)}；get(a, o1) 为 None
        防回归: 若 DELETE 只按 agent_name 过滤，会误删同名不同组织的记录，本用例失败
        """
        sql_store.record_heartbeat("a", "o1", T0)
        sql_store.record_heartbeat("a", "o2", T0)

        sql_store.remove("a", "o1")

        assert sqlite_backend._execute_read_all(
            "SELECT agent_name, organization FROM agent_health") == [("a", "o2")]
        assert sql_store.get("a", "o1") is None

    def test_history_round_trip_with_filters(self, sql_store, sqlite_backend):
        """TC-STORE-028 | SQL 后端历史写入使用 uuid 主键，查询按过滤条件+倒序+limit

        输入: 追加 (a/o1)、 (b/o1)、 (a/o1 第二条)；分别按全量/name/name+org/limit 查询
        预期输出: 每条历史 event_id 唯一（长度 36）；全量按 changed_at 倒序；
              name 过滤只剩 a 的两条；name+limit=1 只剩最新一条
        断言点: 表中 event_id 去重后数量；返回字典的五个键与值；顺序与条数
        防回归: 若 event_id 用固定串（主键冲突）、ORDER BY 方向反了、或 WHERE 条件拼接错误，本用例失败
        """
        sql_store.append_history("a", "o1", HealthStatus.HEALTHY, HealthStatus.SUSPECT, T0)
        sql_store.append_history("b", "o1", HealthStatus.HEALTHY, HealthStatus.OFFLINE,
                                 T0 + timedelta(seconds=10))
        sql_store.append_history("a", "o1", HealthStatus.SUSPECT, HealthStatus.OFFLINE,
                                 T0 + timedelta(seconds=20))

        event_ids = [row[0] for row in sqlite_backend._execute_read_all(
            "SELECT event_id FROM agent_health_history")]
        assert len(set(event_ids)) == 3
        assert all(len(event_id) == 36 for event_id in event_ids)

        everything = sql_store.list_history()
        assert [entry["changed_at"] for entry in everything] == [
            (T0 + timedelta(seconds=20)).isoformat(),
            (T0 + timedelta(seconds=10)).isoformat(),
            T0.isoformat(),
        ]
        assert everything[0] == {
            "name": "a", "organization": "o1",
            "previous_health_status": "suspect", "health_status": "offline",
            "changed_at": (T0 + timedelta(seconds=20)).isoformat(),
        }
        assert [entry["name"] for entry in sql_store.list_history(name="a")] == ["a", "a"]
        assert [entry["name"] for entry in sql_store.list_history(organization="o1")] == ["a", "b", "a"]
        assert [entry["changed_at"] for entry in sql_store.list_history(name="a", limit=1)] == [
            (T0 + timedelta(seconds=20)).isoformat()]

    def test_close_is_noop(self, sql_store):
        """TC-STORE-029 | SQL 后端 close 不关闭共享后端连接池

        输入: 构造后调用 close()
        预期输出: 返回 None，且之后仍可读写（连接池归主存储所有）
        断言点: 返回值为 None；close 后 record_heartbeat/get 仍成功
        防回归: 若 close 误关主存储连接池，服务停机顺序变化时会破坏其他组件写入，本用例失败
        """
        assert sql_store.close() is None
        sql_store.record_heartbeat("a", "o1", T0)
        assert sql_store.get("a", "o1") is not None

    def test_placeholder_falls_back_to_percent_s(self):
        """TC-STORE-030 | 后端未声明 param_ph 时使用 '%s' 占位符

        输入: 构造 SqlHeartbeatStore 传入不带 param_ph 的 recording 后端，调用 get/list_monitored
        预期输出: SELECT 语句中的占位符为 '%s'
        断言点: 记录的读 SQL 含 "agent_name = %s"；list_history 无过滤条件时不含 WHERE
        防回归: 若占位符被硬编码成 '?' 或 '{}'，PG/MySQL 驱动会解析失败，本用例失败
        """
        backend = _RecordingBackend()
        store = SqlHeartbeatStore(backend)

        store.get("a", "o1")
        store.list_history()

        select_sql = [sql for sql, _ in backend.reads if "FROM agent_health WHERE" in sql]
        assert select_sql == [
            "SELECT agent_name, organization, last_heartbeat_at, status, status_changed_at "
            "FROM agent_health WHERE agent_name = %s AND organization = %s",
        ]
        assert backend.reads[0][1] == ("a", "o1")
        history_sql = backend.reads[-1][0]
        assert "FROM agent_health_history " in history_sql
        assert "WHERE" not in history_sql
        assert history_sql.endswith("ORDER BY changed_at DESC LIMIT 50")
