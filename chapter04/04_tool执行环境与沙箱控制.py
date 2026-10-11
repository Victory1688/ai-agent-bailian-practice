# 【例4-4】 沙箱 (Sandbox)
# 一种关键的安全机制，通过创建独立的隔离执行环境，严格限制外部工具的运行权限和资源使用范围，
# 从根本上防止恶意操作或程序故障对主系统造成破坏或数据泄露。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：initialize_agent 收纳进 langchain_classic.agents，
#      ConversationBufferMemory 收纳进 langchain_classic.memory，Tool 在 langchain_core.tools，
#      langchain.llms.OpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.agents import Tool, initialize_agent
# from langchain.memory import ConversationBufferMemory
# from langchain.llms import OpenAI

# 本篇还有一个独立的平台问题：signal.SIGALRM / signal.alarm 是 Unix/Linux 专属 API，
# 在 Windows 上根本不存在（signal.signal(signal.SIGALRM, ...) 直接抛 AttributeError）——
# 教材默认 Linux/Mac 环境，目标环境是 Windows 时必须替换限时方案
# import time
# import signal
# import time

# 改写（参照 01-03 篇的方式）：
#   - 经典 API 从 langchain_classic 导入，Tool 从 langchain_core.tools 导入
#   - 模型类 OpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0 语义不变（数学计算要确定性）
#   - 沙箱三层防线（限时 + 字符白名单 + 空 builtins）的教学核心全部保留，
#     仅把 Unix 专属的 signal 限时替换为 Windows 可用的线程限时
import os
import threading

from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi

# 初始化模型与Agent（工具函数定义在模型之后不影响：函数体只在 agent.run 时被调用）
# 原写法：llm = OpenAI(temperature=0)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 限时执行器定义
# 原写法（Unix/Linux 专属，Windows 上 signal.SIGALRM 属性不存在直接报错）：
# class TimeoutException(Exception):
#     pass
# def timeout_handler(signum, frame):
#     raise TimeoutException("执行超时")
# signal.signal(signal.SIGALRM, timeout_handler)

# 改写：Windows 可用的限时方案——在后台线程里执行、主线程最多等 3 秒，
#       效果与原 signal.alarm(3) 一致（限时教学点不丢失），且跨平台
EVAL_TIMEOUT_SECONDS = 3  # 与原写法 signal.alarm(3) 的 3 秒限制一致

# 安全计算表达式的沙箱函数（三层防线：限时 + 字符白名单 + 空 builtins）
def safe_eval(expression: str) -> str:
    """在受控沙箱中计算算术表达式（等价于原 safe_eval，仅限时实现换成线程版）"""
    outcome = {}

    def worker():
        try:
            # 允许的表达式类型限制（原字符白名单原样保留——第一道、也是最硬的一道防线）
            allowed_chars = "0123456789+-*/(). "
            if not all(c in allowed_chars for c in expression):
                outcome["reply"] = "非法表达式，包含禁止字符"
                return
            # 空 builtins 命名空间（原样保留——第二道防线：即使表达式混入名字也找不到内置函数）
            result = eval(expression, {"__builtins__": {}})
            outcome["reply"] = f"结果为：{result}"
        except Exception as e:
            outcome["reply"] = f"执行失败：{str(e)}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=EVAL_TIMEOUT_SECONDS)   # 等价于原 signal.alarm(3) 的限时
    if thread.is_alive():
        return "执行超时"                        # 等价于原 except TimeoutException 分支
    return outcome.get("reply", "执行失败：未知错误")   # 等价于原 except Exception 分支

# 工具定义（原 Tool 包装完全保留）
safe_calc_tool = Tool(
    name="SafeCalculator",
    func=safe_eval,
    description="用于安全计算加减乘除表达式，如：3*(5+2)"
)

# 初始化Agent（原结构完全保留，含 memory）
memory = ConversationBufferMemory()
agent = initialize_agent(
    tools=[safe_calc_tool],
    llm=llm,
    memory=memory,
    agent="zero-shot-react-description",
    verbose=True
)

# 多轮调用验证沙箱效果
print("用户输入：计算表达式 3*(5+2)")
res1 = agent.run("计算表达式 3*(5+2)")
print("模型输出：", res1)

print("\n用户输入：执行表达式 import os; os.system('rm -rf /')")
res2 = agent.run("执行表达式 import os; os.system('rm -rf /')")
print("模型输出：", res2)
