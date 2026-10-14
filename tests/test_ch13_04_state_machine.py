"""
test_ch13_04_state_machine.py —— chapter13 / 04 子状态管理与任务调度

【TDD 定位】被测文件：chapter13/04_子状态管理与任务调度.py
【测试策略】状态机 = 全章最适合 TDD 的模块（纯状态迁移，零成本穷举）；
            任务派发真实调用 = @pytest.mark.live

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - VALID_STATUSES = ("idle", "running", "success", "failed")
  - STATUS_TRANSITIONS 迁移白名单：idle→running；running→{success,failed}；
    success→running；failed→running
  - AgentState.update 非法状态值 / 非法迁移 均抛 ValueError（教材无约束）
  - AgentState.to_dict 结果超 80 字符截断，含 name/status/last_result/last_error
  - TASK_REGISTRY 四类任务：intent/qa/tool/dialog
  - AgentController 状态单元与注册表同键
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_04")


# ============================================================
# 1. 状态机常量契约
# ============================================================

def test_valid_statuses(ch13_04):
    """合法状态集合必须恰为四个"""
    assert set(ch13_04.VALID_STATUSES) == {"idle", "running", "success", "failed"}


def test_transition_whitelist_shape(ch13_04):
    """迁移表必须覆盖所有合法状态（无遗漏键）"""
    assert set(ch13_04.STATUS_TRANSITIONS.keys()) == set(ch13_04.VALID_STATUSES)


def test_transition_targets_are_valid(ch13_04):
    """迁移表中的目标状态必须也在合法状态集合内（自洽性）"""
    for src, targets in ch13_04.STATUS_TRANSITIONS.items():
        for t in targets:
            assert t in ch13_04.VALID_STATUSES, f"{src} → {t} 目标非法"


def test_idle_cannot_jump_to_success(ch13_04):
    """idle 不能直接跳到 success —— 必须经 running（教材任何跳转都放行）"""
    assert "success" not in ch13_04.STATUS_TRANSITIONS["idle"]


def test_retry_paths_exist(ch13_04):
    """success/failed → running 存在，语义为允许重试/重派发"""
    assert "running" in ch13_04.STATUS_TRANSITIONS["success"]
    assert "running" in ch13_04.STATUS_TRANSITIONS["failed"]


def test_task_registry_four_types(ch13_04):
    """任务注册表必须含教材四类任务"""
    assert set(ch13_04.TASK_REGISTRY.keys()) == {"intent", "qa", "tool", "dialog"}
    for spec in ch13_04.TASK_REGISTRY.values():
        assert "name" in spec and "prompt" in spec
        assert "{input}" in spec["prompt"]


# ============================================================
# 2. AgentState —— 迁移校验（穷举全部状态对）
# ============================================================

def test_initial_state_is_idle(ch13_04):
    """新建状态单元初始应为 idle，且无结果无错误"""
    st = ch13_04.AgentState("测试Agent")
    assert st.status == "idle"
    assert st.last_result is None
    assert st.last_error is None


@pytest.mark.parametrize("target", ["idle", "running", "success", "failed"])
def test_illegal_transition_from_idle_raises(ch13_04, target):
    """idle 下只有 running 合法，其余（含 idle 自身）全部拒绝"""
    st = ch13_04.AgentState("A")
    if target == "running":
        st.update(target)               # 合法
        assert st.status == "running"
    else:
        with pytest.raises(ValueError):
            st.update(target)


def test_full_legal_lifecycle(ch13_04):
    """完整合法生命周期：idle→running→success→running→failed"""
    st = ch13_04.AgentState("A")
    st.update("running")
    st.update("success", result="ok")
    assert st.status == "success" and st.last_result == "ok"
    st.update("running")                # 重试
    st.update("failed", error="超时")
    assert st.status == "failed" and st.last_error == "超时"


@pytest.mark.parametrize("bad_status", ["", "RUNNING", "done", "pending", None, 123])
def test_invalid_status_value_raises(ch13_04, bad_status):
    """非白名单状态值一律 ValueError"""
    st = ch13_04.AgentState("A")
    with pytest.raises(ValueError):
        st.update(bad_status)


def test_running_to_running_illegal(ch13_04):
    """running → running 不在白名单（防重复置位）"""
    st = ch13_04.AgentState("A")
    st.update("running")
    with pytest.raises(ValueError):
        st.update("running")


def test_invalid_transition_leaves_state_unchanged(ch13_04):
    """非法迁移被拒后，状态不应被污染（fail fast 的数据完整性）"""
    st = ch13_04.AgentState("A")
    with pytest.raises(ValueError):
        st.update("success")
    assert st.status == "idle"


# ============================================================
# 3. to_dict 快照契约
# ============================================================

def test_snapshot_fields(ch13_04):
    """快照必须含四字段"""
    st = ch13_04.AgentState("AgentX")
    snap = st.to_dict()
    assert set(snap.keys()) == {"name", "status", "last_result", "last_error"}
    assert snap["name"] == "AgentX"
    assert snap["status"] == "idle"


def test_snapshot_truncates_long_result(ch13_04):
    """超 80 字符的结果应被截断并加省略号"""
    st = ch13_04.AgentState("A")
    st.update("running")
    st.update("success", result="x" * 200)
    snap = st.to_dict()
    assert len(snap["last_result"]) == 83        # 80 + "..."
    assert snap["last_result"].endswith("...")


def test_snapshot_short_result_untouched(ch13_04):
    """短结果不应被截断"""
    st = ch13_04.AgentState("A")
    st.update("running")
    st.update("success", result="短的")
    assert st.to_dict()["last_result"] == "短的"


# ============================================================
# 4. AgentController 结构契约
# ============================================================

def test_controller_agents_keys_match_registry(ch13_04):
    """控制器状态单元必须与任务注册表同键（消灭平行维护）"""
    ctrl = ch13_04.AgentController()
    assert set(ctrl.agents.keys()) == set(ch13_04.TASK_REGISTRY.keys())


def test_controller_session_id_is_uuid(ch13_04):
    """控制器 session_id 应为 uuid"""
    ctrl = ch13_04.AgentController()
    assert len(ctrl.session_id) == 36


def test_status_snapshot_shape(ch13_04):
    """get_status_snapshot 应返回所有子 Agent 的快照"""
    ctrl = ch13_04.AgentController()
    snap = ctrl.get_status_snapshot()
    assert set(snap.keys()) == set(ch13_04.TASK_REGISTRY.keys())


# ============================================================
# 5. 真实任务派发
# ============================================================

@pytest.mark.live
def test_dispatch_task_contract(ch13_04):
    """派发任务后对应子 Agent 状态应迁移到 success"""
    ctrl = ch13_04.AgentController()
    result = ctrl.dispatch_task("qa", "什么是机器学习")
    assert isinstance(result, str) and result.strip()
    assert ctrl.agents["qa"].status == "success"
