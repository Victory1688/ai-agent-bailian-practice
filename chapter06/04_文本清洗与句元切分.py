# 【例6-4】 # 文本清洗与句元切分
# 目的：去除非语言符号、冗余字符、HTML标签等干扰数据的"噪声"，净化文本。
# 方法：利用正则表达式 (Regex) 精准匹配并替换或删除无关字符。
#
# 关键作用：数据质量的第一道防线
# 经过清洗、切分与拼接的标准化文本，将直接作为输入数据，赋能后续的 Embedding (嵌入) 与 Recall (召回) 模块，是确保系统检索准确率的基石。
#
# 原写法（注释保留）：末尾有一行 Colab 专用调用：
#   import ace_tools as tools; tools.display_dataframe_to_user(name="文本清洗与句元切分结果", dataframe=df_chunks)
# ace_tools 是 Google Colab（AI Code Editor）的专属展示库，本地 Python 环境没有——
#   运行会报 ImportError。改写：改成标准 print 输出 chunks 列表。
# 另外 import pandas as pd 仅用于构造 DataFrame 展示——改写后也改用原生 print。

import re

# 模拟原始文本（原样保留——混入了换行、空格、英文缩写、中文全角标点，是典型的"脏"文本）
raw_text = """
近年来，人工智能在各个领域取得了飞速发展，尤其是在自然语言处理方面。
大语言模型（如GPT、BERT等）的出现，使得计算机在理解和生成自然语言的能力上有了质的飞跃。
然而，模型的性能高度依赖于输入数据的质量，如何对原始文本进行高质量的清洗与切分，成为构建高效语义检索系统的基础。
以RAG为代表的检索增强生成方法，需要将文档划分为结构合理、语义完整的片段，才能在后续嵌入计算与召回阶段获得最优表现。
本文将探讨一种面向中文文本的清洗与句元切分方案。
"""

# 文本清洗函数（原样保留——两行正则：保留白名单字符 + 清除所有空白）
def clean_text(text):
    # 白名单正则：仅保留 中文汉字 + 中文常用标点 + 英文字母 + 数字
    # \u4e00-\u9fa5 是中文 Unicode 范围；注意列表里有（全角括号）但没有半角()——
    # 被清洗掉时半角括号会被当作噪声删除（白名单内没有），运行时可以观察
    text = re.sub(r"[^\u4e00-\u9fa5。！？；，、（）——""《》：A-Za-z0-9]", "", text)
    # \s+ 清除所有空白（空格、换行、制表符）——让文本变成一整行
    text = re.sub(r"\s+", "", text)
    return text

# 切分函数：按中文标点断句（原样保留——断言 (?<=[。！？]) 表示"在句号/感叹号/问号后面断"）
def split_sentences(text):
    return re.split(r"(?<=[。！？])", text)

# Chunk生成：按照最大字符数贪婪拼接（原样保留——同 02 篇 RecursiveCharacterTextSplitter 的贪婪思想）
def generate_chunks(sentences, max_len=60):
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= max_len:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

# 执行清洗与切分（原样保留——三行是本篇的主流程）
cleaned_text = clean_text(raw_text)
sentences = split_sentences(cleaned_text)
chunks = generate_chunks(sentences, max_len=80)

# 构造结果并输出（改写：原 pandas DataFrame + ace_tools → 原生 print）
# 原写法（注释保留）：
# import pandas as pd
# df_chunks = pd.DataFrame({"chunk_id": range(1, len(chunks) + 1), "text_chunk": chunks})
# import ace_tools as tools; tools.display_dataframe_to_user(name="文本清洗与句元切分结果", dataframe=df_chunks)

print(f"清洗后文本：{cleaned_text}\n")
print(f"切分得到 {len(sentences)} 个句子\n")
print(f"拼接得到 {len(chunks)} 个 chunk（max_len=80）：")
for i, c in enumerate(chunks, 1):
    print(f"  [{i}] {c}")


# 实测输出：
# 清洗后文本（所有空白被 \s+ 清除，变成一整行；保留了中文汉字、中文标点、英文、数字、全角括号等白名单字符）：
#   近年来，人工智能在各个领域取得了飞速发展，尤其是在自然语言处理方面。大语言模型（如GPT、BERT等）的出现，
#   使得计算机在理解和生成自然语言的能力上有了质的飞跃。然而，模型的性能高度依赖于输入数据的质量，如何对
#   原始文本进行高质量的清洗与切分，成为构建高效语义检索系统的基础。以RAG为代表的检索增强生成方法，需要将
#   文档划分为结构合理、语义完整的片段，才能在后续嵌入计算与召回阶段获得最优表现。本文将探讨一种面向中文
#   文本的清洗与句元切分方案。
#
# 切分得到 6 个句子  ← 隐藏点！5 个句号按断言分割会产生 6 段（最后一段是空串），
#   空串被 generate_chunks 合并进最后一个 chunk 所以最终 chunks=5
#
# 拼接得到 5 个 chunk（max_len=80，每句独立成块都没到上限，所以一句一块）：
#   [1] 近年来，人工智能在各个领域取得了飞速发展，尤其是在自然语言处理方面。
#   [2] 大语言模型（如GPT、BERT等）的出现，使得计算机在理解和生成自然语言的能力上有了质的飞跃。
#   [3] 然而，模型的性能高度依赖于输入数据的质量，如何对原始文本进行高质量的清洗与切分，成为构建高效语义检索系统的基础。
#   [4] 以RAG为代表的检索增强生成方法，需要将文档划分为结构合理、语义完整的片段，才能在后续嵌入计算与召回阶段获得最优表现。
#   [5] 本文将探讨一种面向中文文本的清洗与句元切分方案。
#
# 值得讨论的细节：
#   1) 与 02 篇 RecursiveCharacterTextSplitter 的产出几乎等价——这是"自定义实现 vs 现成组件"的对照，
#      本篇的 clean_text + split_sentences + generate_chunks 三步，基本就是 RecursiveCharacterTextSplitter
#      在默认参数下的手动复刻（只是没有递归降级机制）
#   2) clean_text 白名单里有全角括号（）但没有半角()——原始文本用了全角括号所以保留了；
#      如果换成半角括号，它们会被当作噪声删掉（写个例子验证一下就知道了）
#   3) re.split 的末尾空串——文本末尾是句号时 split 会在句号后也分割一次，产生一个空字符串，
#      这是正则分割的常见陷阱，实际生产通常要加 [s for s in sentences if s] 过滤
