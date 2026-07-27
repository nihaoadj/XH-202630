# 教学卡：Chunk 切分策略

**能力节点**：Chunk 切分｜**适用水平**：Python 基础｜**卡片 ID**：card_chunking

## 学习目标

理解切片大小和重叠区间如何影响检索质量、上下文完整性与生成成本。

## 核心概念

Chunk 是向量检索的最小证据单元。过大时主题混杂、检索不精确；过小时上下文不足。`chunk_overlap` 用于保留相邻段落交界处的语义。对 Markdown、代码和 JSON，应优先按照标题、函数或对象边界切分，再用长度限制兜底。

## 工程步骤

1. 以段落、标题、句子等由大到小的边界递归切分。
2. 设定初始参数，例如 500 字符与 50 字符重叠。
3. 为每个片段记录 `chunk_id`、序号、内容哈希和所属文档。
4. 用同一批问题比较不同参数的命中率与答案忠实度。
5. 选取质量与成本平衡较好的参数并写入知识库版本说明。

## 常见错误

- 只按固定字符数硬切，导致定义和条件被拆开。
- 重叠比例过大，产生大量近似重复片段。
- 片段 ID 随每次入库顺序变化，造成引用和评测样本失效。

## 小练习与评测点

对同一教程分别用 200/0、500/50、1000/100 参数切分，比较“Rerank 为什么需要候选集？”的检索结果。评测：目标片段命中率、重复率、平均片段长度。

## 来源

- LangChain, [Text Splitters](https://docs.langchain.com/oss/python/integrations/splitters/index)，访问日期：2026-07-24。
- LangChain, [Recursive Text Splitter](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)，访问日期：2026-07-24。
