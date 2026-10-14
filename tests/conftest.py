"""
conftest.py —— TDD 测试基础设施（全书共用）

【为什么需要这个文件】
本项目的源码文件命名形如 `01_先定义标准的Agent接口层和数据结构.py`：
  ① 以数字开头 —— 不是合法 Python 标识符，`import 01_xxx` 直接 SyntaxError
  ② 含中文 —— 常规 import 机制无法处理
  ③ 各章大量重名（13 章几乎每章都有 `01_xxx.py`）—— 放进同一 package 会冲突

因此所有测试必须通过 **文件路径动态加载**（importlib.util），而非 import 语句。
本文件提供 `load_module()` / `load_chapter_module()` 两个工具函数统一处理。

【使用方式】
    from conftest import load_chapter_module
    mod = load_chapter_module(13, "01")          # 加载 chapter13/01_*.py
    mod = load_chapter_module(13, "08")          # 加载 chapter13/08_*.py

【设计约束】
- 加载的模块会在 `sys.modules` 注册一个稳定的合成名（如 `ch13_01`），
  避免重复加载（源码模块级有 `logging.basicConfig` 等副作用）。
- 所有源码文件在 `if __name__ == "__main__"` 下才执行 self-test，
  因此动态加载不会触发真实 LLM 调用 —— 安全。
- 真实 API 调用由各测试文件显式触发（本项目的 TDD 采用"全部真实调用"策略）。
"""

import os
import re
import sys
import glob
import importlib.util

# 仓库根目录（tests/ 的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 已加载模块缓存：合成名 → module
_MODULE_CACHE = {}


def _iter_chapter_py(chapter_no: int):
    """列出某章所有 .py 源码文件（排除 __pycache__）"""
    chapter_dir = os.path.join(ROOT_DIR, f"chapter{chapter_no:02d}")
    return sorted(glob.glob(os.path.join(chapter_dir, "*.py")))


def load_chapter_module(chapter_no: int, file_prefix: str):
    """按「章号 + 文件序号前缀」动态加载源码模块

    参数:
        chapter_no  — 章号（1~13）
        file_prefix — 文件序号前缀（"01" / "02" / ... / "11"）

    返回:
        已加载的模块对象（同一前缀重复调用返回同一模块实例）

    异常:
        FileNotFoundError — 该章下找不到匹配前缀的文件
        ValueError        — 前缀匹配到多个文件（命名歧义）
    """
    key = f"ch{chapter_no:02d}_{file_prefix}"
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]

    matches = [p for p in _iter_chapter_py(chapter_no)
               if os.path.basename(p).startswith(f"{file_prefix}_")]
    if not matches:
        raise FileNotFoundError(
            f"chapter{chapter_no:02d} 下找不到以 '{file_prefix}_' 开头的 .py 文件")
    if len(matches) > 1:
        raise ValueError(f"前缀 {file_prefix} 匹配到多个文件: {matches}")

    path = matches[0]
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod          # 先注册，支持模块内相互 import
    spec.loader.exec_module(mod)
    _MODULE_CACHE[key] = mod
    return mod


def load_module_by_path(abs_path: str):
    """按绝对路径加载任意源码模块（跨章复用场景）

    参数: abs_path — .py 文件绝对路径
    返回: 模块对象
    """
    key = "mod_" + re.sub(r"\W+", "_", os.path.splitext(os.path.basename(abs_path))[0])
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"文件不存在: {abs_path}")
    spec = importlib.util.spec_from_file_location(key, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    _MODULE_CACHE[key] = mod
    return mod


# ============================================================
# 共享 fixture
# ============================================================

import pytest


@pytest.fixture(scope="session")
def ch13_01():
    """chapter13 / 01 标准 Agent 接口层和数据结构"""
    return load_chapter_module(13, "01")


@pytest.fixture(scope="session")
def ch13_02():
    """chapter13 / 02 用户意图识别与入口解析"""
    return load_chapter_module(13, "02")


@pytest.fixture(scope="session")
def ch13_03():
    """chapter13 / 03 工具调用链与异常回退机制"""
    return load_chapter_module(13, "03")


@pytest.fixture(scope="session")
def ch13_04():
    """chapter13 / 04 子状态管理与任务调度"""
    return load_chapter_module(13, "04")


@pytest.fixture(scope="session")
def ch13_05():
    """chapter13 / 05 RAG 检索问答子系统"""
    return load_chapter_module(13, "05")


@pytest.fixture(scope="session")
def ch13_06():
    """chapter13 / 06 MCP 协议的上下文路由器"""
    return load_chapter_module(13, "06")


@pytest.fixture(scope="session")
def ch13_07():
    """chapter13 / 07 A2A 消息协议的模块注入"""
    return load_chapter_module(13, "07")


@pytest.fixture(scope="session")
def ch13_08():
    """chapter13 / 08 LangChain 的通用 Agent 主控链条"""
    return load_chapter_module(13, "08")


@pytest.fixture(scope="session")
def ch13_09():
    """chapter13 / 09 Test 工具调用正确率测试框架"""
    return load_chapter_module(13, "09")


@pytest.fixture(scope="session")
def ch13_10():
    """chapter13 / 10 Test 多用户并发测试与系统压测"""
    return load_chapter_module(13, "10")


@pytest.fixture(scope="session")
def ch13_11():
    """chapter13 / 11 Test 模型幻觉率与用户满意度评估"""
    return load_chapter_module(13, "11")
