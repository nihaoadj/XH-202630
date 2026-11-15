"""Bounded deterministic learning tasks; never call an LLM or translate text."""
from app.core.retrieval.knowledge_ids import normalize_text

QUERY_VERSION = "learning-tasks-v2"

NODE_TASKS = {
    "rag_basics": ("RAG 的索引、检索与生成各负责什么，与只用模型内部知识有何区别？", "RAG 在哪些条件下需要检索，如何判断证据是否充分？"),
    "document_parsing": ("PDF、HTML 文档解析如何保留标题、阅读顺序和表格结构？", "解析结果如何清洗并验证页码、正文和来源定位？"),
    "chunking": ("chunk_size 与 chunk_overlap 如何影响上下文完整性和检索召回？", "代码、表格和章节边界应如何切分并验证？"),
    "hybrid_retrieval": ("BM25 与向量检索分数尺度不一致时，RRF 如何按排名融合？", "混合检索的候选召回、去重和 Top-K 截断分别在哪一步执行？"),
    "rerank": ("Cross-Encoder 如何对 query 和 passage 评分，与向量召回有什么区别？", "Rerank 的候选数、输入长度与相关性阈值有哪些限制？"),
    "similarity_retrieval": ("相似度检索如何选择 cosine、Top-K 并衡量召回率？", "非对称语义检索中 encode_query 与 encode_document 有什么区别？"),
    "embedding": ("Embedding 如何编码语义，归一化和距离度量应如何配合？", "Embedding 模型的维度、输入长度与多语言能力有哪些使用限制？"),
    "vector_store": ("向量数据库的索引、距离度量和元数据过滤如何配合召回？", "HNSW 的索引参数如何影响召回率、时延和更新一致性？"),
    "prompt_assembly": ("检索证据如何组织到 Prompt，如何区分事实依据与任务指令？", "上下文预算不足时如何截取、排序证据并避免丢失关键条件？"),
    "citation": ("生成事实如何绑定 evidence_id、原文引用和来源定位？", "如何验证引用确实支持结论，而不仅是引用编号合法？"),
    "hallucination_control": ("RAG 如何识别无证据支持的事实与矛盾声明？", "证据不足或相互冲突时如何拒答、纠偏并核验？"),
    "rag_evaluation": ("Recall、MRR、nDCG 与答案忠实度分别衡量什么？", "如何构造评测问题、标注参考证据并区分检索错误与生成错误？"),
    "rag_tuning": ("RAG 的切分、召回、精排和生成瓶颈如何分别诊断？", "如何通过消融实验比较质量、时延与成本，避免只优化单个指标？"),
}

RESOURCE_TASKS = {
    "实操指南": "具体操作步骤、前置条件和结果验证方法是什么？",
    "分阶测试题": "哪些概念容易混淆，如何判断适用条件和错误结论？",
    "复习清单": "关键检查项、易错点和适用边界分别是什么？",
    "案例分析": "实际应用中如何选择方案，决策依据和限制条件是什么？",
}


def learning_queries(node_input, descriptor, budget):
    """Return None on an unrepresentable request so callers retain old semantics."""
    topic = normalize_text(node_input.topic)
    nodes = list(dict.fromkeys(node_input.target_skill_nodes[:3]))
    weak = [str(v).strip() for v in node_input.diagnosis.get("weak_points", []) if str(v).strip()][:2]
    scopes = [(node, *descriptor(node)) for node in nodes] or [(None, v, []) for v in weak] or [(None, "", [])]
    if budget < len(scopes):
        return None
    queries, mapping = [], {}

    def add(value, node):
        value = normalize_text(value)
        if len(value) > 2000:
            return False
        if value not in queries:
            queries.append(value)
        if node:
            # A one-owner map cannot truthfully assign a shared query to two nodes.
            if value in mapping and mapping[value] != node:
                return False
            mapping[value] = node
        return True

    specific = "?" in topic or "？" in topic
    if specific and len(nodes) != 1 and budget < len(scopes) + 1:
        return None
    if specific and not add(topic, nodes[0] if len(nodes) == 1 else None):
        return None
    task = next((RESOURCE_TASKS[k] for k in node_input.resource_types if k in RESOURCE_TASKS), None)
    for turn in range(2):
        for node, name, points in scopes:
            if len(queries) >= budget:
                return queries, mapping
            stem = " ".join([topic, name, *points]).strip()
            focus = NODE_TASKS.get(node, ("工作原理、概念区别和适用条件是什么？", task or "如何操作验证，常见错误和限制条件是什么？"))[turn]
            if specific:
                focus = ("针对上述问题，涉及哪些概念区别、技术前提和适用条件？",
                         "验证上述结论需要哪些操作步骤、限制条件和反例？")[turn]
            if turn == 1 and task:
                focus += " " + task
            if not add(f"{stem}：{focus}", node):
                return None
    return queries, mapping
