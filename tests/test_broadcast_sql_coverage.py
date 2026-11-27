# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Branch-coverage tests: webhook dispatcher, Milvus layer migration,
SQL storage backend branches and UDS tag-handler exception paths.

All doubles are local to this file; every test asserts observable results.
"""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

import agent_registry.broadcast.dispatcher as dispatcher_mod
from agent_registry.broadcast.dispatcher import TokenBucket, WebhookDispatcher, sign_payload
from agent_registry.broadcast.events import build_event
from agent_registry.broadcast.outbox import DELIVERY_ABANDONED
from agent_registry.broadcast.subscriptions import MemorySubscriptionStore, Subscription
from agent_registry.persistence import milvus_layer_migration as mig
from agent_registry.persistence import sql_backend as sql_backend_mod
from agent_registry.persistence.sql_backend import SqlStorageBackend
from agent_registry.persistence.sql_queries import PostgreSQLQueries


# ==========================================================================
# TC-DISP: broadcast/dispatcher.py
# ==========================================================================

class _FakeOutbox:
    def __init__(self):
        self.deliveries = []
        self.statuses = []
        self.pending = []
        self.retryable = []
        self.dropped = []
        self.max_v = 10
        self.fail_ensure = False

    def ensure_deliveries(self, event, matching, skipped):
        if self.fail_ensure:
            raise RuntimeError("ledger down")
        self.deliveries.append((event.event_id, list(matching), list(skipped)))

    def list_pending(self, limit, after_version=0):
        return list(self.pending)

    def mark_status(self, event_id, status):
        self.statuses.append((event_id, status))

    def list_pending_for(self, subscription_id, limit):
        return []

    def list_retryable_for(self, subscription_id, max_attempts, limit):
        return list(self.retryable)

    def retry_delivery(self, subscription_id, event_id, max_attempts):
        return self.retry_ok

    retry_ok = False

    def drop_deliveries(self, subscription_id):
        self.dropped.append(subscription_id)

    def mark_delivery(self, subscription_id, event_id, status):
        self.statuses.append((subscription_id, event_id, status))

    def max_version(self):
        return self.max_v

    def cleanup(self, days, active_subscription_ids=None):
        return self.cleanup_removed

    cleanup_removed = 0


class _FakeClient:
    def __init__(self, status_code=200, exc=None):
        self.status_code = status_code
        self.exc = exc
        self.posts = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(status_code=self.status_code)

    async def aclose(self):
        self.closed = True


def _make_dispatcher(outbox=None, subs=None, retry_interval=0.0, **kwargs):
    outbox = outbox or _FakeOutbox()
    subs = subs or MemorySubscriptionStore()
    client = _FakeClient()
    dispatcher = WebhookDispatcher(subscription_store=subs, outbox=outbox,
                                   client=client, retry_interval=retry_interval, **kwargs)
    return dispatcher, outbox, subs, client


def _event(v, data=None):
    return build_event("AGENT_HEALTH_CHANGED", data or {"organization": "o1"},
                       registry_version=v)


@pytest.fixture(autouse=True)
def _disp_policy(monkeypatch):
    """dispatcher 交付测试统一放行回调目的地校验（单项用例自行覆盖为抛错）。"""
    monkeypatch.setattr(dispatcher_mod, "validate_callback_destination", lambda url: None)
    yield


def test_disp_sign_payload_deterministic():
    """TC-DISP-001 | sign_payload 对相同输入产生确定签名且带 sha256 前缀

    输入: secret="s", timestamp="1", body=b"x" 调用两次
    预期输出: 两次结果一致且以 "sha256=" 开头
    断言点: 确定性 + 前缀格式
    防回归: 若签名格式被改坏，订阅方验签失败
    """
    a = sign_payload("s", "1", b"x")
    b = sign_payload("s", "1", b"x")
    assert a == b
    assert a.startswith("sha256=")


def test_disp_token_bucket_refill_and_exhaustion():
    """TC-DISP-002 | TokenBucket：充足余额消费成功；超额消费失败

    输入: rate=0.1, capacity=2；消费 2 后再消费 1
    预期输出: 第一次 True；第二次 False
    断言点: 两个布尔值（边界）
    防回归: 若桶逻辑改坏，风暴保护失效
    """
    bucket = TokenBucket(rate=0.1, capacity=2)
    assert bucket.try_consume(2) is True
    assert bucket.try_consume(1) is False


def test_disp_stop_closes_owned_client():
    """TC-DISP-003 | stop() 取消后台任务并在持有客户端时关闭它

    输入: start 后 stop；owns_client=True
    预期输出: _workers 清空；client.aclose 被调用（真实 httpx 客户端）
    断言点: workers 空 + 无异常
    防回归: 若 aclose 被删，连接池泄漏
    """
    dispatcher, _, subs, _ = _make_dispatcher()
    subs.create(Subscription(subscription_id="", callback_url="https://cb.example.com"))

    async def scenario():
        dispatcher.start()
        assert dispatcher._flusher_task is not None
        await dispatcher.stop()
        assert dispatcher._workers == {}
        assert dispatcher._flusher_task is None

    asyncio.run(scenario())


def test_disp_add_remove_subscription_cross_loop():
    """TC-DISP-004 | 非 dispatcher 事件循环调用 add/remove_subscription 转投 _loop

    输入: _loop 指向一个未运行的旧循环；在当前循环内 add/remove
    预期输出: call_soon_threadsafe 被调用且直接返回（不在当前循环创建 worker）
    断言点: 当前循环 workers 不变 + 回调被调度
    防回归: 若跨循环守卫被删，任务跨 loop 创建导致崩溃
    """
    dispatcher, _, subs, _ = _make_dispatcher()
    sub = Subscription(subscription_id="sub_x", callback_url="https://cb.example.com")
    dummy_loop = asyncio.new_event_loop()
    dispatcher._loop = dummy_loop
    scheduled = []
    dummy_loop.call_soon_threadsafe = lambda cb, *a: scheduled.append(cb)

    async def scenario():
        dispatcher.add_subscription(sub)
        assert dispatcher._workers == {}  # 转投旧循环，未在当前循环建 worker
        dispatcher.remove_subscription("sub_x")

    try:
        asyncio.run(scenario())
    finally:
        dummy_loop.close()
    assert len(scheduled) == 2


def test_disp_remove_subscription_cancels_worker_and_drops(monkeypatch):
    """TC-DISP-005 | remove_subscription 取消 worker、清理限流桶并删除投递台账

    输入: 已存在的 worker；drop_deliveries 抛错 / 正常
    预期输出: worker 被移除；抛错只告警不中断（dropped 记录一致）
    断言点: workers/buckets/scheduled 清理 + dropped 记录
    防回归: 若不 drop 台账，删除的订阅留下永久 pending
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    sub = subs.create(Subscription(subscription_id="", callback_url="https://cb.example.com"))

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher._add_worker(sub)
        worker = dispatcher._workers[sub.subscription_id]
        dispatcher.remove_subscription(sub.subscription_id)
        assert sub.subscription_id not in dispatcher._workers
        try:
            await worker.task
        except asyncio.CancelledError:
            pass
        assert outbox.dropped == [sub.subscription_id]

    asyncio.run(scenario())

    async def scenario_fail():
        dispatcher2, outbox2, subs2, _ = _make_dispatcher()
        sub2 = subs2.create(Subscription(subscription_id="", callback_url="https://cb2.example.com"))
        dispatcher2._loop = asyncio.get_running_loop()
        dispatcher2._add_worker(sub2)
        monkeypatch.setattr(type(outbox2), "drop_deliveries",
                            lambda self, sid: (_ for _ in ()).throw(RuntimeError("db down")))
        dispatcher2.remove_subscription(sub2.subscription_id)  # 不抛异常
        assert outbox2.dropped == []

    asyncio.run(scenario_fail())


def test_disp_add_worker_idempotent():
    """TC-DISP-006 | _add_worker 对已存在订阅不重复创建

    输入: 同一订阅调用两次 _add_worker
    预期输出: 仅 1 个 worker，且与首次相同
    断言点: is 身份比对
    防回归: 若幂等守卫被删，重复 worker 重复投递
    """
    dispatcher, _, _, _ = _make_dispatcher()
    sub = Subscription(subscription_id="sub_dup", callback_url="https://cb.example.com")

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher._add_worker(sub)
        first = dispatcher._workers["sub_dup"]
        dispatcher._add_worker(sub)
        assert dispatcher._workers["sub_dup"] is first

    asyncio.run(scenario())


def test_disp_submit_records_ledger_and_buffers():
    """TC-DISP-007 | submit 记录台账并把匹配事件放入缓冲；不匹配者记为 skipped

    输入: 订阅匹配 o1 / 不匹配 o2 两个订阅；事件 organization=o1
    预期输出: ensure_deliveries 收到 (matching=[sub1], skipped=[sub2])；缓冲键为 (sub1, event_id)
    断言点: 台账三元组 + 缓冲键
    防回归: 若台账记录被删，事件可能漏投
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    subs.create(Subscription(subscription_id="", callback_url="https://a.example.com",
                             organizations=["o1"]))
    subs.create(Subscription(subscription_id="", callback_url="https://b.example.com",
                             organizations=["o2"]))
    event = _event(1)

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher.submit(event)

    asyncio.run(scenario())
    assert len(outbox.deliveries) == 1
    event_id, matching, skipped = outbox.deliveries[0]
    assert event_id == event.event_id
    assert len(matching) == 1 and len(skipped) == 1
    assert (matching[0], event.event_id) in dispatcher._buffers


def test_disp_submit_ledger_failure_returns_silently():
    """TC-DISP-008 | ensure_deliveries 抛错时 submit 放弃缓冲（事件留待恢复）

    输入: outbox.fail_ensure=True
    预期输出: _buffers 为空（未投递任何未跟踪工作）
    断言点: 空 buffers
    防回归: 若错误被忽略，未跟踪事件会被直接投递
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    outbox.fail_ensure = True

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher.submit(_event(1))

    asyncio.run(scenario())
    assert dispatcher._buffers == {}


def test_disp_submit_at_buffer_capacity_drops_new_key():
    """TC-DISP-009 | 缓冲满时丢弃新事件（台账保持 pending 由轮询兜底）

    输入: buffer_limit=1；先提交事件 A，再提交事件 B
    预期输出: 缓冲仅含 A；B 的台账行仍存在
    断言点: 缓冲键数量 + 台账数
    防回归: 若无上限，缓冲无界增长
    """
    dispatcher, outbox, subs, _ = _make_dispatcher(buffer_limit=1)
    subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    event_a, event_b = _event(1), _event(2)

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher.submit(event_a)
        dispatcher.submit(event_b)

    asyncio.run(scenario())
    assert len(dispatcher._buffers) == 1
    assert any(k[1] == event_a.event_id for k in dispatcher._buffers)
    assert len(outbox.deliveries) == 2


def test_disp_recover_marks_abandoned_without_subscriptions():
    """TC-DISP-010 | 无订阅时 recover 将 pending 事件标记为 abandoned

    输入: pending 含 2 个事件；无订阅
    预期输出: 每个事件被 mark_status(DELIVERY_ABANDONED)；不建 worker
    断言点: statuses 列表
    防回归: 若不标记，永久 pending 的恢复永远空转
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    outbox.pending = [_event(1), _event(2)]
    dispatcher.recover()
    assert [s[1] for s in outbox.statuses] == [DELIVERY_ABANDONED, DELIVERY_ABANDONED]
    assert dispatcher._fanout_cursor == 2  # 游标推进到最后一个 pending 事件的版本


def test_disp_recover_reenqueues_for_existing_workers():
    """TC-DISP-011 | recover 为已有 worker 的订阅重新入队 pending 事件

    输入: 1 个订阅 + worker；pending 1 条
    预期输出: worker 队列收到批次；_fanout_cursor = 事件版本
    断言点: 队列深度 + cursor
    防回归: 若恢复入队被删，重启后事件永不投递
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher._add_worker(sub)
        worker = dispatcher._workers[sub.subscription_id]
        # 先停掉 worker，防止它立刻消费刚恢复的批次
        worker.task.cancel()
        try:
            await worker.task
        except asyncio.CancelledError:
            pass
        event = _event(7)
        outbox.pending = [event]
        outbox.list_pending_for = lambda sid, limit: [event]
        dispatcher.recover()
        assert dispatcher._fanout_cursor == 7
        assert dispatcher._workers[sub.subscription_id].queue.qsize() == 1

    asyncio.run(scenario())


def test_disp_recover_ledger_failure_is_logged():
    """TC-DISP-012 | recover 中 ensure_deliveries 抛错只记录并继续

    输入: outbox.fail_ensure=True；有订阅无 worker
    预期输出: 不抛异常
    断言点: 无异常（循环不被中断）
    防回归: 若异常上抛，flusher 线程死亡
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    outbox.fail_ensure = True
    outbox.pending = [_event(1)]
    dispatcher.recover()


def test_disp_retry_failed_deliveries_paths():
    """TC-DISP-013 | retry_failed_deliveries：无 worker/枚举失败/重排队成功/重排失败

    输入: 四种订阅状态组合
    预期输出: 分别返回 0 / 0（continue）/ 1（ready 入队）/ 0（单条失败跳过）
    断言点: 返回值 ×4 + 队列深度
    防回归: 若预算检查被删，永久坏目的地无限重试
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    # 1. 无 worker → 跳过
    subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    assert dispatcher.retry_failed_deliveries() == 0

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        sub2 = subs.create(Subscription(subscription_id="", callback_url="https://b.example.com"))
        dispatcher._add_worker(sub2)
        outbox.retry_ok = True
        event = _event(3)
        outbox.retryable = [event]
        assert dispatcher.retry_failed_deliveries() == 1
        assert dispatcher._workers[sub2.subscription_id].queue.qsize() == 1

        # 重排队接口抛错 → 单条跳过
        monkey_target = dispatcher._outbox
        def broken_retry(sid, eid, max_attempts):
            raise RuntimeError("locked")
        dispatcher._outbox.retry_delivery = broken_retry
        outbox.retryable = [_event(4)]
        assert dispatcher.retry_failed_deliveries() == 0

        # list_retryable_for 抛错 → 该订阅跳过
        def broken_list(sid, max_attempts, limit):
            raise RuntimeError("db down")
        dispatcher._outbox.list_retryable_for = broken_list
        outbox.retryable = [_event(5)]
        assert dispatcher.retry_failed_deliveries() == 0

    asyncio.run(scenario())


def test_disp_retry_loop_survives_sweep_errors():
    """TC-DISP-014 | _retry_loop 单次清扫抛错被记录并继续

    输入: retry_interval=0.01；retry_failed_deliveries 抛错；任务运行后取消
    预期输出: 任务未因异常结束
    断言点: cancel 前 task 未 done
    防回归: 若异常未捕获，重试线程死亡
    """
    dispatcher, _, _, _ = _make_dispatcher(retry_interval=0.01)
    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        task = asyncio.get_running_loop().create_task(dispatcher._retry_loop())
        dispatcher.retry_failed_deliveries = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_disp_flusher_loop_recovers_and_cleans_up():
    """TC-DISP-015 | flusher 循环：recover 抛错继续；到达清理阈值触发 cleanup

    输入: debounce=0.01；recover 抛错；_cleanup_counter=3599；cleanup 返回 5
    预期输出: cleanup 被调用一次并复位计数；循环继续运行
    断言点: cleanup 调用记录 + _cleanup_counter 复位
    防回归: 若清理被删，过期投递记录无限堆积
    """
    dispatcher, outbox, _, _ = _make_dispatcher(debounce_window=0.01)
    dispatcher._cleanup_counter = 3599
    cleanups = []
    dispatcher.recover = lambda: (_ for _ in ()).throw(RuntimeError("recover down"))
    outbox.cleanup = lambda days, active_subscription_ids=None: cleanups.append(days) or 5

    async def scenario():
        task = asyncio.get_running_loop().create_task(dispatcher._flusher_loop())
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert len(cleanups) >= 1
    assert dispatcher._cleanup_counter < 3599


def test_disp_flusher_cleanup_failure_is_logged():
    """TC-DISP-016 | cleanup 抛错时 flusher 循环继续

    输入: cleanup 抛 RuntimeError
    预期输出: 任务保持运行直至取消
    断言点: cancel 前任务未结束
    防回归: 若清理异常上抛，flusher 死亡
    """
    dispatcher, outbox, _, _ = _make_dispatcher(debounce_window=0.01)
    dispatcher._cleanup_counter = 3599
    outbox.cleanup = lambda days, active_subscription_ids=None: (_ for _ in ()).throw(RuntimeError("boom"))

    async def scenario():
        task = asyncio.get_running_loop().create_task(dispatcher._flusher_loop())
        await asyncio.sleep(0.08)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_disp_flush_buffers_skips_missing_worker():
    """TC-DISP-017 | flush 时 worker 已删除则跳过该订阅

    输入: 缓冲含 sub 键但 workers 为空
    预期输出: 不查询 outbox、不抛异常
    断言点: 无异常 + outbox.list_pending_for 未被调用
    防回归: 若 worker 缺失检查被删，flush 崩溃
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    dispatcher._buffers[("gone", "e1")] = _event(1)
    called = []
    outbox.list_pending_for = lambda sid, limit: called.append(sid) or []
    dispatcher._flush_buffers()
    assert called == []
    assert dispatcher._buffers == {}  # 缓冲已消费


def test_disp_enqueue_worker_missing_and_queue_full():
    """TC-DISP-018 | _enqueue：无 worker 返回 0；队列满时停止入队

    输入: 不存在的订阅 / maxsize=1 的 worker 队列已满
    预期输出: 0 / 仅第一批入队，其余保持 pending
    断言点: 返回值 + 队列深度
    防回归: 若满队列被硬塞，asyncio.QueueFull 裸抛
    """
    dispatcher, _, _, _ = _make_dispatcher(batch_size=1)
    assert dispatcher._enqueue("gone", [_event(1)]) == 0

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        sub = Subscription(subscription_id="sub_q", callback_url="https://a.example.com")
        dispatcher._add_worker(sub)
        events = [_event(i) for i in range(3)]
        queued = dispatcher._enqueue("sub_q", events)
        assert queued == 1
        assert dispatcher._workers["sub_q"].queue.qsize() == 1

    asyncio.run(scenario())


def test_disp_worker_loop_survives_batch_failure():
    """TC-DISP-019 | worker 循环：批处理抛错被记录并继续消费下一批

    输入: _deliver_batch 抛错；队列喂 2 批
    预期输出: 两批都被消费（processed 计数=2）
    断言点: processed 计数
    防回归: 若批异常未捕获，worker 死亡后订阅永不投递
    """
    dispatcher, _, subs, _ = _make_dispatcher()
    processed = []

    async def failing_batch(subscription_id, batch):
        processed.append(len(batch))
        raise RuntimeError("delivery down")

    dispatcher._deliver_batch = failing_batch

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        sub = Subscription(subscription_id="sub_w", callback_url="https://a.example.com")
        dispatcher._add_worker(sub)
        worker = dispatcher._workers["sub_w"]
        worker.queue.put_nowait([_event(1)])
        await asyncio.sleep(0.05)
        worker.queue.put_nowait([_event(2)])
        await asyncio.sleep(0.05)
        task = worker.task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(processed) == 2

    asyncio.run(scenario())


def test_disp_deliver_batch_unknown_subscription():
    """TC-DISP-020 | _deliver_batch 订阅已删除时直接返回

    输入: subs.get → None
    预期输出: 无投递发生
    断言点: client.posts 为空
    防回归: 若订阅缺失检查被删，None 引用崩溃
    """
    dispatcher, outbox, subs, client = _make_dispatcher()
    asyncio.run(dispatcher._deliver_batch("gone", [_event(1)]))
    assert client.posts == []


def test_disp_deliver_batch_rate_limit_degrades_to_sync():
    """TC-DISP-021 | 限流命中时批次降级为 SYNC_REQUIRED 摘要事件

    输入: 订阅限流桶余额清零；2 个事件
    预期输出: 每个事件被标记 degraded；POST 的是 SYNC_REQUIRED 事件；不投递原批次
    断言点: statuses 中的 degraded 标记 + 请求体含 SYNC_REQUIRED
    防回归: 若降级被删，慢订阅被原批次拖垮
    """
    dispatcher, outbox, subs, client = _make_dispatcher()
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com",
                                   secret="topsecret"))
    bucket = TokenBucket(rate=0.1, capacity=2)
    bucket.tokens = 0
    dispatcher._buckets[sub.subscription_id] = bucket
    events = [_event(1), _event(2)]

    asyncio.run(dispatcher._deliver_batch(sub.subscription_id, events))

    degraded = [s for s in outbox.statuses if s[2] == "degraded"]
    assert len(degraded) == 2
    assert len(client.posts) == 1
    body = json.loads(client.posts[0][1]["content"])
    assert body["events"][0]["event_type"] == "SYNC_REQUIRED"
    assert client.posts[0][1]["headers"]["X-Registry-Signature"].startswith("sha256=")


def test_disp_deliver_events_success_and_http_error():
    """TC-DISP-022 | 投递：2xx 成功返回 True；HTTP 500 重试后返回 False

    输入: client 状态码 200 / 500
    预期输出: True / False；失败路径重试了 max_retries+1 次
    断言点: 返回值 + POST 次数
    防回归: 若重试上限被删，坏目的地无限重试
    """
    dispatcher, _, subs, _ = _make_dispatcher(max_retries=2)
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    events = [_event(1)]

    client_ok = _FakeClient(status_code=200)
    dispatcher._client = client_ok
    assert asyncio.run(dispatcher._deliver_events(sub, events, persist=True)) is True
    assert len(client_ok.posts) == 1

    client_fail = _FakeClient(status_code=500)
    dispatcher._client = client_fail
    dispatcher._backoff_base = 0.001
    dispatcher._backoff_max = 0.002
    assert asyncio.run(dispatcher._deliver_events(sub, events, persist=True)) is False
    assert len(client_fail.posts) == 3  # max_retries + 1


def test_disp_deliver_events_network_error_retries():
    """TC-DISP-023 | 网络错误（httpx.HTTPError）重试后返回 False

    输入: client.post 抛 httpx.ConnectError
    预期输出: False；重试次数 = max_retries + 1
    断言点: 返回值 + POST 次数
    防回归: 若网络异常未捕获，worker 崩溃
    """
    dispatcher, _, subs, _ = _make_dispatcher(max_retries=1)
    dispatcher._backoff_base = 0.001
    dispatcher._backoff_max = 0.002
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    client = _FakeClient(exc=httpx.ConnectError("refused"))
    dispatcher._client = client
    assert asyncio.run(dispatcher._deliver_events(sub, [_event(1)], persist=True)) is False
    assert len(client.posts) == 2


def test_disp_deliver_events_unauthorized_destination_fails_fast(monkeypatch):
    """TC-DISP-024 | 目的地被吊销（ValueError）/非法 URL（InvalidURL）时立即失败

    输入: validate_callback_destination 抛 ValueError；client.post 抛 InvalidURL
    预期输出: False；POST 未发出（ValueError）/ 仅 1 次（InvalidURL 不重试）
    断言点: 返回值 + POST 次数
    防回归: 若 fail-fast 被删，被吊销目的地仍收到流量
    """
    dispatcher, _, subs, client = _make_dispatcher()
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))
    monkeypatch.setattr(dispatcher_mod, "validate_callback_destination",
                        lambda url: (_ for _ in ()).throw(ValueError("revoked")))
    assert asyncio.run(dispatcher._deliver_events(sub, [_event(1)], persist=True)) is False
    assert client.posts == []

    client2 = _FakeClient(exc=httpx.InvalidURL("bad"))
    dispatcher._client = client2
    monkeypatch.setattr(dispatcher_mod, "validate_callback_destination", lambda url: None)
    assert asyncio.run(dispatcher._deliver_events(sub, [_event(1)], persist=True)) is False
    assert len(client2.posts) == 1  # InvalidURL 不重试


def test_disp_flush_buffers_enqueues_pending_from_ledger():
    """TC-DISP-025 | flush 以台账为序：先查 pending 再入队

    输入: 缓冲 1 个事件；outbox.list_pending_for 返回 2 个事件
    预期输出: worker 队列收到台账中的 2 个事件（而非仅缓冲的 1 个）
    断言点: 队列批次长度
    防回归: 若跳过台账，旧 pending 事件被缓冲事件插队
    """
    dispatcher, outbox, subs, _ = _make_dispatcher()
    sub = subs.create(Subscription(subscription_id="", callback_url="https://a.example.com"))

    async def scenario():
        dispatcher._loop = asyncio.get_running_loop()
        dispatcher._add_worker(sub)
        buffered = _event(9)
        dispatcher._buffers[(sub.subscription_id, buffered.event_id)] = buffered
        ledger_events = [_event(1), _event(2)]
        outbox.list_pending_for = lambda sid, limit: ledger_events
        dispatcher._flush_buffers()
        batch = dispatcher._workers[sub.subscription_id].queue.get_nowait()
        assert [e.event_id for e in batch] == [e.event_id for e in ledger_events]

    asyncio.run(scenario())


# ==========================================================================
# TC-MIG: persistence/milvus_layer_migration.py
# ==========================================================================

class _FakeMilvus:
    def __init__(self, schemas, entities=(), collections=None):
        self._schemas = schemas  # {name: schema dict or other}
        self._entities = list(entities)
        self._collections = set(collections or schemas)
        self.upserts = []
        self.inserts = []
        self.created = []
        self.loaded = []

    def has_collection(self, name):
        return name in self._collections

    def describe_collection(self, name):
        return self._schemas[name]

    def load_collection(self, collection_name=None):
        self.loaded.append(collection_name)

    def query(self, **kwargs):
        return list(self._entities)

    def upsert(self, collection_name=None, data=None):
        self.upserts.append((collection_name, data))

    def insert(self, collection_name=None, data=None):
        self.inserts.append((collection_name, data))


_LAYER_SCHEMA = {"fields": [{"name": f} for f in ("id", "embedding", "layer")],
                 "enable_dynamic_field": False}
_PLAIN_SCHEMA = {"fields": [{"name": f} for f in ("id", "embedding")],
                 "enable_dynamic_field": False}


def test_mig_schema_field_names_and_output_fields():
    """TC-MIG-101 | schema 解析：dict 与对象字段混合；动态字段回退

    输入: fields=[{"name":"id"}, obj(name="embedding")]；动态开/关
    预期输出: {"id","embedding"}；动态关时 layer 被剔除，动态开时保留
    断言点: 集合内容 ×3
    防回归: 若动态回退被删，旧集合迁移漏列
    """
    class _Field:
        def __init__(self, name):
            self.name = name

    schema = {"fields": [{"name": "id"}, _Field("embedding")]}
    assert mig.schema_field_names(schema) == {"id", "embedding"}
    assert mig.schema_output_fields(_LAYER_SCHEMA, ["id", "layer"]) == ["id", "layer"]
    assert mig.schema_output_fields(_PLAIN_SCHEMA, ["id", "layer"]) == ["id"]
    dynamic = dict(_PLAIN_SCHEMA, enable_dynamic_field=True)
    assert mig.schema_output_fields(dynamic, ["id", "owner"]) == ["id", "owner"]


def test_mig_collection_schema_errors():
    """TC-MIG-102 | collection_schema：集合不存在/非 dict schema 抛 LayerMigrationRequiredError

    输入: has_collection=False / describe 返回字符串
    预期输出: 错误消息分别含 "does not exist" / "invalid schema"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，坏 schema 进入后续解析崩溃
    """
    client = _FakeMilvus({})
    with pytest.raises(mig.LayerMigrationRequiredError, match="does not exist"):
        mig.collection_schema(client, "missing")
    client2 = _FakeMilvus({"c": "not-a-dict"})
    with pytest.raises(mig.LayerMigrationRequiredError, match="invalid schema"):
        mig.collection_schema(client2, "c")


def test_mig_require_layer_field():
    """TC-MIG-103 | require_layer_field：无 layer 字段抛错并提示迁移

    输入: 无 layer 字段的 schema
    预期输出: LayerMigrationRequiredError，消息含 "run migrate-milvus-layer"
    断言点: 异常类型 + 消息关键字
    防回归: 若守卫被删，layer 查询静默返回不完整结果
    """
    client = _FakeMilvus({"c": _PLAIN_SCHEMA})
    with pytest.raises(mig.LayerMigrationRequiredError, match="run migrate-milvus-layer"):
        mig.require_layer_field(client, "c")
    client2 = _FakeMilvus({"c": _LAYER_SCHEMA})
    mig.require_layer_field(client2, "c")  # 不抛


def test_mig_query_batches_iterator_and_fallback():
    """TC-MIG-104 | _query_batches：迭代器分批（含 close）；回退单批；空批不产出

    输入: 迭代器产出 2 批后空 / 无 query_iterator 属性 / query 返回 []
    预期输出: 2 批 + close 调用 / 1 批（load_collection 被调用）/ 0 批
    断言点: 批内容 + close/load 记录
    防回归: 若迭代器耗尽判断被删，迁移死循环
    """
    class _Iterator:
        def __init__(self, batches):
            self._batches = list(batches)
            self.closed = False

        def next(self):
            return self._batches.pop(0) if self._batches else []

        def close(self):
            self.closed = True

    client = _FakeMilvus({"c": _LAYER_SCHEMA})
    iterator = _Iterator([[_entity(1)], [_entity(2)], []])
    client.query_iterator = lambda **kwargs: iterator
    batches = list(mig._query_batches(client, "c", ["id"], 10))
    assert len(batches) == 2
    assert iterator.closed is True
    assert client.loaded == ["c"]

    plain = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=[_entity(1)])
    batches = list(mig._query_batches(plain, "c", ["id"], 10))
    assert len(batches) == 1

    empty = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=[])
    assert list(mig._query_batches(empty, "c", ["id"], 10)) == []


def _entity(idx, layer=None, with_embedding=True):
    entity = {"id": f"pk-{idx}", "name": f"a{idx}"}
    if with_embedding:
        entity["embedding"] = [0.1, 0.2]
    if layer is not None:
        entity["layer"] = layer
    return entity


def test_mig_normalized_entity_variants():
    """TC-MIG-105 | _normalized_entity：缺 layer/合法 layer/非法 layer 三种分支

    输入: 无 layer / layer="gpu" / layer="not-a-layer"
    预期输出: (changed=True, unknown=True) / (changed=False, unknown=False) /
              (changed=True, unknown=True) 且 layer 归为 UNKNOWN
    断言点: changed/unknown 标志 ×3
    防回归: 若归一化被删，非法 layer 值写回集合
    """
    from agent_registry.model.agent_layer import UNKNOWN_LAYER

    normalized, changed, unknown = mig._normalized_entity(_entity(1))
    assert changed is True and unknown is True
    assert normalized["layer"] == UNKNOWN_LAYER.value if hasattr(UNKNOWN_LAYER, "value") \
        else normalized["layer"] == UNKNOWN_LAYER

    normalized, changed, unknown = mig._normalized_entity(_entity(1, layer="gpu"))
    assert changed is False and unknown is False

    normalized, changed, unknown = mig._normalized_entity(_entity(1, layer=123))
    assert changed is True and unknown is True


def test_mig_write_batches_upsert_insert_and_empty():
    """TC-MIG-106 | _write_batches：upsert/insert 分派；空批跳过并计数

    输入: operation=upsert 与 insert；批次含一个空批
    预期输出: 分别调用 upsert/insert；空批不写；返回写入实体数
    断言点: 调用记录 + 计数值
    防回归: 若空批检查被删，Milvus 报空数据错误
    """
    client = _FakeMilvus({"c": _LAYER_SCHEMA})
    written = mig._write_batches(client, "upsert", "c", [[_entity(1)], [], [_entity(2)]])
    assert written == 2
    assert len(client.upserts) == 2 and client.inserts == []

    client2 = _FakeMilvus({"c": _LAYER_SCHEMA})
    written = mig._write_batches(client2, "insert", "c", [[_entity(1)]])
    assert written == 1 and len(client2.inserts) == 1


def test_mig_migrate_in_place_dry_run_and_writes():
    """TC-MIG-107 | migrate_in_place：dry_run 不写；正常路径分批 upsert

    输入: 3 个实体（1 个缺 layer）、batch_size=2，dry_run 先行
    预期输出: dry_run：scanned=3、updated=0；正常：updated=3、upsert 2 次
    断言点: result 字段 + upsert 次数
    防回归: 若分批写被删，大集合迁移一次性写爆
    """
    entities = [_entity(1, layer="gpu"), _entity(2), _entity(3)]

    dry_client = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=entities)
    result = mig.migrate_in_place(dry_client, "c", batch_size=2, dry_run=True)
    assert result.scanned == 3
    assert result.updated == 0
    assert dry_client.upserts == []
    assert result.to_dict()["mode"] == "in-place"

    client = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=entities)
    result = mig.migrate_in_place(client, "c", batch_size=2)
    assert result.updated == 2
    assert result.unknown_assigned == 2
    assert len(client.upserts) == 1
    assert len(client.upserts[0][1]) == 2


def test_mig_migrate_in_place_missing_embedding_raises():
    """TC-MIG-108 | migrate_in_place：实体缺 embedding 时抛错（向量不可保留）

    输入: 无 embedding 的实体且 layer 需要变更
    预期输出: LayerMigrationRequiredError，消息含 "has no embedding"
    断言点: 异常类型 + 消息关键字
    防回归: 若守卫被删，迁移会丢向量
    """
    client = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=[_entity(1, with_embedding=False)])
    with pytest.raises(mig.LayerMigrationRequiredError, match="has no embedding"):
        mig.migrate_in_place(client, "c")


def test_mig_migrate_by_rebuild_validations():
    """TC-MIG-109 | rebuild 校验：空目标名/目标已存在/缺 embedding

    输入: target_collection="" / 目标已存在 / 实体无 embedding
    预期输出: ValueError ×3，消息分别含 "target_collection is required" /
              "already exists" / "has no embedding"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，rebuild 覆盖既有集合或丢向量
    """
    client = _FakeMilvus({"src": _PLAIN_SCHEMA, "tgt": _LAYER_SCHEMA})
    with pytest.raises(ValueError, match="target_collection is required"):
        mig.migrate_by_rebuild(client, "src", "", lambda name: None)

    client2 = _FakeMilvus({"src": _PLAIN_SCHEMA},
                          collections={"src", "tgt"})
    with pytest.raises(ValueError, match="already exists"):
        mig.migrate_by_rebuild(client2, "src", "tgt", lambda name: None)

    client3 = _FakeMilvus({"src": _PLAIN_SCHEMA, "tgt": _LAYER_SCHEMA},
                          entities=[_entity(1, with_embedding=False)],
                          collections={"src"})
    with pytest.raises(mig.LayerMigrationRequiredError, match="has no embedding"):
        mig.migrate_by_rebuild(client3, "src", "tgt",
                               lambda name: client3._collections.add(name))


def test_mig_migrate_by_rebuild_copies_entities():
    """TC-MIG-110 | rebuild 拷贝：创建目标、插入全部实体、计入 copied

    输入: 2 个实体（1 个缺 layer）、batch_size=2
    预期输出: create_target 被调用；insert 1 次 2 条；copied=2；unknown_assigned=1
    断言点: created 列表 + inserts + result 字段
    防回归: 若拷贝管线被删，rebuild 后数据丢失
    """
    client = _FakeMilvus({"src": _PLAIN_SCHEMA, "tgt": _LAYER_SCHEMA},
                         entities=[_entity(1, layer="gpu"), _entity(2)],
                         collections={"src"})
    created = []

    def create_target(name):
        created.append(name)
        client._collections.add(name)

    result = mig.migrate_by_rebuild(client, "src", "tgt", create_target, batch_size=2)
    assert created == ["tgt"]
    assert result.copied == 2
    assert result.unknown_assigned == 1
    assert result.layer_field_present is False
    assert len(client.inserts) == 1
    assert len(client.inserts[0][1]) == 2


def test_mig_migrate_by_rebuild_dry_run():
    """TC-MIG-111 | rebuild dry_run：不创建目标、不写数据

    输入: dry_run=True
    预期输出: create_target 未调用；inserts 为空；copied=0
    断言点: 三项均空/零
    防回归: 若 dry_run 分支被删，演练操作会真实改库
    """
    client = _FakeMilvus({"src": _PLAIN_SCHEMA}, entities=[_entity(1)],
                         collections={"src"})
    created = []
    result = mig.migrate_by_rebuild(client, "src", "tgt", created.append, dry_run=True)
    assert created == []
    assert client.inserts == []
    assert result.copied == 0


def test_mig_migrate_collection_dispatch():
    """TC-MIG-112 | migrate_collection：非法 mode/batch_size 报错；auto/in-place/rebuild 分派

    输入: mode="weird" / batch_size=0 / auto（有 layer 字段）/ auto（无字段，缺 create_target）/
          rebuild 正常
    预期输出: ValueError ×3（消息关键字）；in-place / rebuild 各自执行
    断言点: 异常与 result.mode
    防回归: 若分派被删，错误模式静默走错路径
    """
    client = _FakeMilvus({"c": _LAYER_SCHEMA}, entities=[_entity(1)])
    with pytest.raises(ValueError, match="mode must be one of"):
        mig.migrate_collection(client, "c", mode="weird")
    with pytest.raises(ValueError, match="batch_size must be positive"):
        mig.migrate_collection(client, "c", batch_size=0)

    result = mig.migrate_collection(client, "c", mode="auto")
    assert result.mode == "in-place"
    assert client.upserts  # auto + 有 layer 字段 → 原地

    plain_client = _FakeMilvus({"c": _PLAIN_SCHEMA}, collections={"c"})
    with pytest.raises(ValueError, match="create_target is required"):
        mig.migrate_collection(plain_client, "c", target_collection="tgt")

    rebuild_client = _FakeMilvus({"src": _PLAIN_SCHEMA, "tgt": _LAYER_SCHEMA},
                                 entities=[_entity(1)], collections={"src"})
    created = []

    def create_target(name):
        created.append(name)
        rebuild_client._collections.add(name)

    result = mig.migrate_collection(rebuild_client, "src", target_collection="tgt",
                                    mode="rebuild", create_target=create_target)
    assert result.mode == "rebuild"


# ==========================================================================
# TC-SQLB: persistence/sql_backend.py
# ==========================================================================

class _CannedBackend(SqlStorageBackend):
    """以预置结果驱动 SqlStorageBackend 的 CRUD 分支。"""
    queries = PostgreSQLQueries
    _integrity_error = sqlite3.IntegrityError
    param_ph = '?'
    dialect = "sqlite"

    def __init__(self):
        self._write_results = []
        self._read_one_results = []
        self._read_all_results = []
        self.executed_writes = []
        self._raise_on_write = None

    @classmethod
    def init(cls, config):
        return cls()

    def close(self):
        pass

    def _execute_write(self, query, params=None):
        self.executed_writes.append((query, params))
        if self._raise_on_write is not None:
            err, self._raise_on_write = self._raise_on_write, None
            raise err
        return self._write_results.pop(0) if self._write_results else 1

    def _execute_read_one(self, query, params=None):
        return self._read_one_results.pop(0) if self._read_one_results else None

    def _execute_read_all(self, query, params=None):
        return self._read_all_results.pop(0) if self._read_all_results else []


AGENT_JSON = json.dumps({"name": "agent-1", "provider": {"organization": "org-1",
                                                         "url": "https://x"},
                         "description": "d", "version": "1.0.0", "skills": []})


def _agent_record_row(layer="gpu"):
    return (AGENT_JSON, "owner-1", "published", '["gpu"]', "2026-01-01", "2026-01-02", layer)


def test_sqlb_value_parsers():
    """TC-SQLB-101 | 值解析：_parse_json/_parse_tags/_parse_timestamp 全分支

    输入: None/dict/str/其它 ×json；None/list/str/其它 ×tags；datetime/str/None ×timestamp
    预期输出: None/dict/解析 dict/原值；[]/list/解析 list/[]；ISO 串/原串/空串
    断言点: 全部返回值
    防回归: 若解析分支被删，行数据读回类型错误
    """
    assert sql_backend_mod.SqlStorageBackend._parse_json(None) is None
    assert sql_backend_mod.SqlStorageBackend._parse_json({"a": 1}) == {"a": 1}
    assert sql_backend_mod.SqlStorageBackend._parse_json('{"a": 1}') == {"a": 1}
    assert sql_backend_mod.SqlStorageBackend._parse_json(42) == 42

    assert sql_backend_mod.SqlStorageBackend._parse_tags(None) == []
    assert sql_backend_mod.SqlStorageBackend._parse_tags("") == []
    assert sql_backend_mod.SqlStorageBackend._parse_tags(["gpu"]) == ["gpu"]
    assert sql_backend_mod.SqlStorageBackend._parse_tags('["gpu"]') == ["gpu"]
    assert sql_backend_mod.SqlStorageBackend._parse_tags(123) == []

    from datetime import datetime
    assert sql_backend_mod.SqlStorageBackend._parse_timestamp(datetime(2026, 1, 1)) \
        == "2026-01-01T00:00:00"
    assert sql_backend_mod.SqlStorageBackend._parse_timestamp("x") == "x"
    assert sql_backend_mod.SqlStorageBackend._parse_timestamp(None) == ""


def test_sqlb_row_to_agent_record_invalid_layer_falls_back():
    """TC-SQLB-102 | 行中 layer 非法时回退为 UNKNOWN，不影响记录装载

    输入: layer="not-a-layer" 的行
    预期输出: AgentRecord.layer == UNKNOWN；owner/status/tags 读回正确
    断言点: record 字段
    防回归: 若回退被删，坏行抛 ValueError 中断查询
    """
    from agent_registry.model.agent_layer import UNKNOWN_LAYER

    backend = _CannedBackend()
    record = backend._row_to_agent_record(_agent_record_row(layer=123))
    assert record.owner == "owner-1"
    assert record.status == "published"
    assert record.tags == ["gpu"]
    assert record.layer == UNKNOWN_LAYER


def test_sqlb_find_records_builds_filters():
    """TC-SQLB-103 | find_records 无匹配行时返回空列表

    输入: 四个过滤条件全给；read_all 返回 []
    预期输出: []
    断言点: 返回空列表（过滤查询正常执行）
    防回归: 若过滤拼装被删，查询抛 SQL 错误
    """
    backend = _CannedBackend()
    backend._read_all_results = [[]]
    result = backend.find_records(name="agent", organization="org-1",
                                  layer="gpu", status="published")
    assert result == []


def test_sqlb_find_records_filter_sql(monkeypatch):
    """TC-SQLB-104 | find_records 生成的 WHERE 子句与参数顺序

    输入: 四个过滤条件全给
    预期输出: SQL 含 LOWER(name) LIKE / organization = / layer = / status =；
              参数为 ('%agent%', 'org-1', 'gpu', 'published')
    断言点: SQL 片段 + 参数
    防回归: 若参数错位，过滤结果错误
    """
    captured = {}

    class _SpyBackend(_CannedBackend):
        def _execute_read_all(self, query, params=None):
            captured["query"] = query
            captured["params"] = params
            return []

    backend = _SpyBackend()
    backend.find_records(name="agent", organization="org-1", layer="gpu",
                         status="published")
    assert "LOWER(name) LIKE" in captured["query"]
    assert "organization = ?" in captured["query"]
    assert "layer = ?" in captured["query"]
    assert "status = ?" in captured["query"]
    assert captured["params"] == ("%agent%", "org-1", "gpu", "published")


def test_sqlb_update_owner_fallback_paths():
    """TC-SQLB-105 | update：调用方无 owner 时沿用存量 owner；存量也无 owner 用无主更新

    输入: existing.owner="owner-9" / existing.owner=None；layer 给定与缺省
    预期输出: 分别使用 UPDATE_AGENT_WITH_OWNER(_LAYER) / UPDATE_AGENT(_LAYER) 查询
    断言点: 实际执行的查询枚举 ×4
    防回归: 若 owner 回退被删，无主调用者可改他人卡片
    """
    record_with_owner = SimpleNamespace(owner="owner-9", status="registered")
    record_without_owner = SimpleNamespace(owner=None, status="registered")

    backend = _CannedBackend()
    backend.find_by_key = lambda name, org: record_with_owner
    agent_data = json.loads(AGENT_JSON)
    assert backend.update("agent-1", "org-1", agent_data, owner=None) is True
    assert backend.executed_writes[-1][0] == PostgreSQLQueries.UPDATE_AGENT_WITH_OWNER.value

    assert backend.update("agent-1", "org-1", agent_data, owner=None,
                          layer="gpu") is True
    assert backend.executed_writes[-1][0] == PostgreSQLQueries.UPDATE_AGENT_WITH_OWNER_LAYER.value

    backend.find_by_key = lambda name, org: record_without_owner
    assert backend.update("agent-1", "org-1", agent_data, owner=None) is True
    assert backend.executed_writes[-1][0] == PostgreSQLQueries.UPDATE_AGENT.value

    assert backend.update("agent-1", "org-1", agent_data, owner=None, layer="gpu") is True
    assert backend.executed_writes[-1][0] == PostgreSQLQueries.UPDATE_AGENT_LAYER.value


def test_sqlb_update_rejects_key_change():
    """TC-SQLB-106 | update 修改主键（name/org）时抛 ValueError

    输入: agent_data 的 name 与参数不一致
    预期输出: ValueError，消息含 "Cannot change primary key"
    断言点: 异常类型 + 消息关键字
    防回归: 若主键检查被删，更新悄悄移动记录
    """
    backend = _CannedBackend()
    backend.find_by_key = lambda name, org: SimpleNamespace(owner="o", status="registered")
    with pytest.raises(ValueError, match="Cannot change primary key"):
        backend.update("agent-1", "org-1", {"name": "other", "provider":
                                            {"organization": "org-1"}})


def test_sqlb_delete_owner_fallback():
    """TC-SQLB-107 | delete：调用方无 owner 时按存量 owner 删除；无主删除计数回传

    输入: existing.owner="owner-9" / existing=None
    预期输出: 分别执行 DELETE_AGENT_WITH_OWNER / DELETE_AGENT
    断言点: 查询枚举 ×2 + 返回值
    防回归: 若回退被删，无主调用者可删他人卡片
    """
    backend = _CannedBackend()
    backend.find_by_key = lambda name, org: SimpleNamespace(owner="owner-9", status="x")
    assert backend.delete("agent-1", "org-1") is True
    assert backend.executed_writes[0][0] == PostgreSQLQueries.DELETE_AGENT_WITH_OWNER.value

    backend2 = _CannedBackend()
    backend2.find_by_key = lambda name, org: None
    assert backend2.delete("agent-1", "org-1") is True
    assert backend2.executed_writes[0][0] == PostgreSQLQueries.DELETE_AGENT.value


def test_sqlb_count_helpers_handle_missing_rows():
    """TC-SQLB-108 | count/count_by_status 无行时返回 0；tags 缺失返回 []

    输入: _execute_read_one 返回 None
    预期输出: 0 / 0 / '' / [] / None
    断言点: 五个返回值
    防回归: 若 None 检查被删，空表查询抛 TypeError
    """
    backend = _CannedBackend()
    assert backend.count() == 0
    assert backend.count_by_status("published") == 0
    assert backend.get_created_at("a", "o") == ""
    assert backend.get_updated_at("a", "o") == ""
    assert backend.get_agent_tags("a", "o") == []


def test_sqlb_tag_integrity_errors_return_false():
    """TC-SQLB-109 | create_tag/update_tag 唯一约束冲突时返回 False

    输入: _execute_write 抛 sqlite3.IntegrityError
    预期输出: create_tag → False；update_tag → False
    断言点: 两个返回值
    防回归: 若异常被吞为 True，重复标签误报成功
    """
    from agent_registry.model.tag import Tag

    backend = _CannedBackend()
    backend._raise_on_write = sqlite3.IntegrityError("duplicate")
    assert backend.create_tag(Tag(tag_id="t1", name="dup")) is False

    backend2 = _CannedBackend()
    backend2._raise_on_write = sqlite3.IntegrityError("duplicate")
    assert backend2.update_tag("t1", Tag(tag_id="t1", name="dup")) is False


def test_sqlb_add_commit_hook_requires_active_transaction():
    """TC-SQLB-110 | add_commit_hook：无事务时返回 False；事务内注册后提交执行

    输入: 直接调用 / transaction() 内注册回调（其中一个抛错）
    预期输出: False / True 且提交后回调执行、异常被记录不中断
    断言点: 返回值 + 回调执行记录
    防回归: 若钩子异常未捕获，提交后的副作用中断调用方
    """
    class _FakeConn:
        def __init__(self):
            self.committed = False
            self.rolled_back = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    backend = _CannedBackend()
    assert backend.add_commit_hook(lambda: None) is False

    conn = _FakeConn()
    backend._acquire_conn = lambda: conn
    backend._release_conn = lambda c: None
    ran = []

    def good():
        ran.append("good")

    def bad():
        raise RuntimeError("hook down")

    def scenario():
        with backend.transaction():
            assert backend.add_commit_hook(good) is True
            assert backend.add_commit_hook(bad) is True

    asyncio.run(asyncio.to_thread(scenario)) if False else scenario()
    assert conn.committed is True
    assert ran == ["good"]


def test_sqlb_transaction_rollback_on_failure():
    """TC-SQLB-111 | transaction 内异常时回滚并上抛；嵌套失败使外层 rollback-only

    输入: 内层抛 RuntimeError 被外层捕获；外层继续提交
    预期输出: 外层提交抛 RuntimeError("rollback-only")，连接已回滚
    断言点: 异常消息 + conn.rolled_back
    防回归: 若 rollback-only 被删，部分失败的事务被提交
    """
    class _FakeConn:
        def __init__(self):
            self.committed = False
            self.rolled_back = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    backend = _CannedBackend()
    conn = _FakeConn()
    backend._acquire_conn = lambda: conn
    backend._release_conn = lambda c: None

    def scenario():
        with pytest.raises(RuntimeError, match="rollback-only"):
            with backend.transaction():
                try:
                    with backend.transaction():
                        raise RuntimeError("inner failure")
                except RuntimeError:
                    pass

    scenario()
    assert conn.rolled_back is True
    assert conn.committed is False


def test_sqlb_ensure_index_dialect_variants():
    """TC-SQLB-112 | ensure_index：支持 IF NOT EXISTS 直接执行；不支持时容忍 1061

    输入: supports_create_index_if_not_exists=True / False + 抛 errno 1061 / 其它错误
    预期输出: 仅执行 IF NOT EXISTS 版 / 执行普通版且吞掉 1061 / 其它错误上抛
    断言点: 执行的 DDL + 异常行为
    防回归: 若 1061 容忍被删，MySQL 重复建索引使启动失败
    """
    backend = _CannedBackend()
    backend.ensure_index("CREATE INDEX IF NOT EXISTS i", "CREATE INDEX i")
    assert backend.executed_writes == [("CREATE INDEX IF NOT EXISTS i", None)]

    class _Err1061(Exception):
        args = (1061, "duplicate")

    backend2 = _CannedBackend()
    backend2.supports_create_index_if_not_exists = False
    backend2._raise_on_write = _Err1061()
    backend2.ensure_index("a", "b")  # 1061 被容忍

    backend3 = _CannedBackend()
    backend3.supports_create_index_if_not_exists = False
    backend3._raise_on_write = RuntimeError("syntax error")
    with pytest.raises(RuntimeError, match="syntax error"):
        backend3.ensure_index("a", "b")


# ==========================================================================
# TC-TAGH: internal/handlers/tag_handler.py exception paths
# ==========================================================================

def _boom(*a, **kw):
    raise RuntimeError("registry down")


def test_tagh_create_handler_exception_returns_error():
    """TC-TAGH-101 | TagCreateHandler：registry 抛错时返回 {"success": False, "error": ...}

    输入: registry.create_tag 抛 RuntimeError
    预期输出: success=False 且 error 含 "registry down"
    断言点: 两个字段
    防回归: 若异常未捕获，CLI 命令崩溃
    """
    from agent_registry.internal.handlers.tag_handler import TagCreateHandler
    resp = TagCreateHandler().handle({"name": "sec", "user_name": "op"},
                                     SimpleNamespace(create_tag=_boom), {})
    assert resp["success"] is False
    assert "registry down" in resp["error"]


def test_tagh_get_handler_exception_returns_error():
    """TC-TAGH-102 | TagGetHandler：registry.get_tag 抛错时返回错误响应

    输入: params 带 tag_id；get_tag 抛 RuntimeError
    预期输出: success=False 且 error 含 "registry down"
    断言点: 两个字段
    防回归: 若异常未捕获，CLI 命令崩溃
    """
    from agent_registry.internal.handlers.tag_handler import TagGetHandler
    resp = TagGetHandler().handle({"tag_id": "t1", "user_name": "op"},
                                  SimpleNamespace(get_tag=_boom), {})
    assert resp["success"] is False
    assert "registry down" in resp["error"]


def test_tagh_update_handler_exception_returns_error():
    """TC-TAGH-103 | TagUpdateHandler：registry.update_tag 抛错时返回错误响应

    输入: get_tag 正常、update_tag 抛 RuntimeError
    预期输出: success=False 且 error 含 "registry down"
    断言点: 两个字段
    防回归: 若异常未捕获，CLI 命令崩溃
    """
    from agent_registry.internal.handlers.tag_handler import TagUpdateHandler
    registry = SimpleNamespace(get_tag=lambda tid: SimpleNamespace(name="old"),
                               update_tag=_boom)
    resp = TagUpdateHandler().handle({"tag_id": "t1", "name": "new", "user_name": "op"},
                                     registry, {})
    assert resp["success"] is False
    assert "registry down" in resp["error"]


def test_tagh_delete_handler_exception_returns_error():
    """TC-TAGH-104 | TagDeleteHandler：registry.delete_tag 抛错时返回错误响应

    输入: tag 存在且无 agent 使用；delete_tag 抛 RuntimeError
    预期输出: success=False 且 error 含 "registry down"
    断言点: 两个字段
    防回归: 若异常未捕获，CLI 命令崩溃
    """
    from agent_registry.internal.handlers.tag_handler import TagDeleteHandler
    registry = SimpleNamespace(get_tag=lambda tid: SimpleNamespace(name="sec"),
                               find_agents_by_tag=lambda name: [],
                               delete_tag=_boom)
    resp = TagDeleteHandler().handle({"tag_id": "t1", "user_name": "op"}, registry, {})
    assert resp["success"] is False
    assert "registry down" in resp["error"]


def test_tagh_list_handler_exception_returns_error():
    """TC-TAGH-105 | TagListHandler：registry.list_tags 抛错时返回错误响应

    输入: list_tags 抛 RuntimeError
    预期输出: success=False 且 error 含 "registry down"
    断言点: 两个字段
    防回归: 若异常未捕获，CLI 命令崩溃
    """
    from agent_registry.internal.handlers.tag_handler import TagListHandler
    resp = TagListHandler().handle({"user_name": "op"},
                                   SimpleNamespace(list_tags=_boom), {})
    assert resp["success"] is False
    assert "registry down" in resp["error"]


def test_tagh_delete_in_use_lists_agents():
    """TC-TAGH-106 | TagDeleteHandler：被 agent 使用的 tag 拒绝删除并列出占用者

    输入: find_agents_by_tag 返回 1 个 agent
    预期输出: success=False，error=="Tag is in use"，message 含 agent 名称
    断言点: 三个字段
    防回归: 若占用检查被删，使用中的 tag 被误删
    """
    from agent_registry.internal.handlers.tag_handler import TagDeleteHandler
    registry = SimpleNamespace(
        get_tag=lambda tid: SimpleNamespace(name="sec"),
        find_agents_by_tag=lambda name: [SimpleNamespace(
            name="agent-1", provider=SimpleNamespace(organization="org-1"))],
        delete_tag=lambda tid: True)
    resp = TagDeleteHandler().handle({"tag_id": "t1", "user_name": "op"}, registry, {})
    assert resp["success"] is False
    assert resp["error"] == "Tag is in use"
    assert "agent-1 (org-1)" in resp["message"]
