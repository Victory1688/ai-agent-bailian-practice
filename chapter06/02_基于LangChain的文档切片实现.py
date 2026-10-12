# 【例6-2】 基于LangChain的文档切片实现
# 文档切片（chunking）是 RAG 检索质量的第一道闸门：切太碎丢失上下文，切太大稀释语义。

# 原写法：from langchain.text_splitter import RecursiveCharacterTextSplitter
# 原写法的问题：langchain 0.x 的旧路径。1.x 把文本切分器拆到了独立的 langchain_text_splitters 包，
#   旧路径下报 ImportError（与 01 篇的 embeddings 断裂同款问题）。
# 原写法代码（注释保留）：
# from langchain.text_splitter import RecursiveCharacterTextSplitter

# 改写：从 1.x 的独立包导入（类名、构造参数、行为完全一致）
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 原始中文文档文本（原样保留）
document_text = """
人工智能是计算机科学的一个分支，旨在研究和开发模拟、延伸和扩展人类智能的理论、方法、技术及应用系统。
它是一门综合性很强的学科，涉及哲学、数学、经济学、神经科学、计算机科学等多个领域。
随着计算能力和数据规模的迅猛增长，人工智能技术在自然语言处理、计算机视觉、智能控制等方面取得了显著进展。
其中，大语言模型的兴起极大提升了机器处理自然语言的能力。
然而，为了使这些模型在问答、对话等场景下具备更强的事实性与可控性，往往需要引入检索增强机制（RAG）以结合外部知识源。
在此过程中，文档切片（chunking）策略成为RAG系统性能优化的重要一环。
"""

# 实例化切片器，设置最大块长100字符，块间重叠20字符（原样保留）
# 教学点：RecursiveCharacterTextSplitter 默认分隔符是 ["\n\n", "\n", " ", ""]——
#   按优先级递归降级，尽量在"自然边界"（段落→行→空格）切开；
#   注意默认列表里没有中文标点（。！？，），中文文本只能在换行处切——
#   对长段落中文文档，改进姿势是传入 separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]（见讲解文档练习2）
splitter = RecursiveCharacterTextSplitter(
    chunk_size=100,
    chunk_overlap=20
)

# 执行切片（原样保留）
chunks = splitter.split_text(document_text)

# 输出所有切片结果（原样保留）
for i, chunk in enumerate(chunks):
    print(f"Chunk {i+1}:\n{chunk}\n")

# 实测输出（6 个自然段按 chunk_size=100 贪婪合并成 3 块）：
# Chunk 1:
# 人工智能是计算机科学的一个分支，旨在研究和开发模拟、延伸和扩展人类智能的理论、方法、技术及应用系统。
# 它是一门综合性很强的学科，涉及哲学、数学、经济学、神经科学、计算机科学等多个领域。
#
# Chunk 2:
# 随着计算能力和数据规模的迅猛增长，人工智能技术在自然语言处理、计算机视觉、智能控制等方面取得了显著进展。
# 其中，大语言模型的兴起极大提升了机器处理自然语言的能力。
#
# Chunk 3:
# 然而，为了使这些模型在问答、对话等场景下具备更强的事实性与可控性，往往需要引入检索增强机制（RAG）以结合外部知识源。
# 在此过程中，文档切片（chunking）策略成为RAG系统性能优化的重要一环。
# 观察：贪婪合并把相邻小段拼到接近 100 字符上限；chunk_overlap=20 在段落级切分时
#   体现为"边界语义延续的预留"，本例段落都是完整句、无跨块句子，所以看不到字面重叠。
