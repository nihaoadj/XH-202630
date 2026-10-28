# 利用知识图谱增强 RAG 推理能力

_作者: [Diego Carpintero](https://github.com/dcarpintero)_

知识图谱提供了一种以既能为人类又能为机器理解的格式建模和存储互联信息的方法。这些图谱由*节点*和*边*组成，分别表示实体及其关系。与传统数据库不同，图谱固有的表达能力允许更丰富的语义理解，同时提供了灵活性，可以在不受固定模式限制的情况下，适应新的实体类型和关系。

通过将知识图谱与嵌入（向量搜索）结合，我们可以利用*多跳连接性*和*信息的上下文理解*，来增强大语言模型（LLMs）的推理能力和可解释性。

本文档探讨了这一方法的实际应用，展示了如何：
- 使用合成数据集在 [Neo4j](https://neo4j.com/docs/) 中构建与研究出版物相关的知识图谱，
- 使用[嵌入模型](https://python.langchain.com/v0.2/docs/integrations/text_embedding/)将我们的部分数据字段投影到高维向量空间，
- 在这些嵌入上构建向量索引以启用相似性搜索，
- 使用自然语言从我们的图谱中提取洞见，通过 [LangChain](https://python.langchain.com/v0.2/docs/introduction/) 轻松将用户查询转换为 [Cypher](https://neo4j.com/docs/cypher-manual/current/introduction/) 语句：

## 初始化

```python
%pip install neo4j langchain langchain_openai langchain-community python-dotenv --quiet
```

### 设置 Neo4j 实例

我们将使用 [Neo4j](https://neo4j.com/docs/) 来创建我们的知识图谱，它是一个开源的数据库管理系统，专门用于图数据库技术。

为了快速且简便地设置，您可以在 [Neo4j Aura](https://neo4j.com/product/auradb/)上 启动一个免费的实例。

接着，你可以使用 `.env` 文件将 `NEO4J_URI`、`NEO4J_USERNAME` 和 `NEO4J_PASSWORD` 设置为环境变量：

```python
import dotenv
dotenv.load_dotenv('.env', override=True)
```

LangChain 提供了 `Neo4jGraph` 类来与 Neo4j 进行交互：

```python
import os
from langchain_community.graphs import Neo4jGraph

graph = Neo4jGraph(
    url=os.environ['NEO4J_URI'], 
    username=os.environ['NEO4J_USERNAME'],
    password=os.environ['NEO4J_PASSWORD'],
)
```

### 将数据集加载到图谱中

以下示例演示了如何与我们的 `Neo4j` 数据库建立连接，并使用[合成数据](https://github.com/dcarpintero/generative-ai-101/blob/main/dataset/synthetic_articles.csv)填充它，这些数据包括研究文章及其作者。

实体包括：
- *研究人员*（Researcher）
- *文章*（Article）
- *主题*（Topic）

关系包括：
- *研究人员* --[PUBLISHED]--> *文章*
- *文章* --[IN_TOPIC]--> *主题*

```python
from langchain_community.graphs import Neo4jGraph

graph = Neo4jGraph()

q_load_articles = """
LOAD CSV WITH HEADERS
FROM 'https://raw.githubusercontent.com/dcarpintero/generative-ai-101/main/dataset/synthetic_articles.csv' 
AS row 
FIELDTERMINATOR ';'
MERGE (a:Article {title:row.Title})
SET a.abstract = row.Abstract,
    a.publication_date = date(row.Publication_Date)
FOREACH (researcher in split(row.Authors, ',') | 
    MERGE (p:Researcher {name:trim(researcher)})
    MERGE (p)-[:PUBLISHED]->(a))
FOREACH (topic in [row.Topic] | 
    MERGE (t:Topic {name:trim(topic)})
    MERGE (a)-[:IN_TOPIC]->(t))
"""

graph.query(q_load_articles)
```

让我们检查节点和关系是否已正确初始化：

```python
graph.refresh_schema()
print(graph.get_schema)
```

我们可以在 Neo4j 工作区中检查我们的知识图谱：

### 构建向量索引

现在，我们构建一个向量索引，以便根据*主题、标题和摘要*高效地搜索相关的*文章*。这一过程包括使用这些字段计算每篇文章的嵌入。在查询时，系统通过使用相似性度量（例如余弦距离）来找到与用户输入最相似的文章。

```python
from langchain_community.vectorstores import Neo4jVector
from langchain_openai import OpenAIEmbeddings

vector_index = Neo4jVector.from_existing_graph(
    OpenAIEmbeddings(),
    url=os.environ['NEO4J_URI'],
    username=os.environ['NEO4J_USERNAME'],
    password=os.environ['NEO4J_PASSWORD'],
    index_name='articles',
    node_label="Article",
    text_node_properties=['topic', 'title', 'abstract'],
    embedding_node_property='embedding',
)
```

**注意：** 要访问 OpenAI 嵌入模型，你需要创建一个 OpenAI 账户，获取 API 密钥，并将 `OPENAI_API_KEY` 设置为环境变量。你还可以尝试使用其他的[嵌入模型](https://python.langchain.com/v0.2/docs/integrations/text_embedding/)集成，进行实验和对比。

## 基于相似性的问答

`Langchain RetrievalQA` 创建了一个问答（QA）链，使用上述的向量索引作为检索器。

```python
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI

vector_qa = RetrievalQA.from_chain_type(
    llm=ChatOpenAI(),
    chain_type="stuff",
    retriever=vector_index.as_retriever()
)
```

我们来问一下：“*哪些文章讨论了人工智能如何影响我们的日常生活？*”

```python
r = vector_qa.invoke(
    {"query": "which articles discuss how AI might affect our daily life? include the article titles and abstracts."}
)
print(r['result'])
```

## 通过知识图谱进行推理

知识图谱非常适合于在实体之间建立连接，能够提取模式并发现新的洞察。

本节将演示如何实现这一过程，并通过自然语言查询将结果集成到大语言模型（LLM）管道中。

### Graph-Cypher-Chain 与 LangChain

为了构建富有表现力且高效的查询，`Neo4j` 使用 `Cypher`，一种受 SQL 启发的声明式查询语言。`LangChain` 提供了封装器 `GraphCypherQAChain`，它是一个抽象层，允许通过自然语言查询图数据库，从而更容易将基于图的数据检索集成到大语言模型（LLM）管道中。

在实际应用中，`GraphCypherQAChain`：
- 从用户输入（自然语言）生成 Cypher 语句（图数据库的查询，如 Neo4j），并应用上下文学习（提示工程），
- 将这些语句执行到图数据库中，
- 将结果作为上下文提供，帮助 LLM 基于准确、最新的信息生成回答。

**注意：** 该实现涉及执行模型生成的图查询，这可能带来潜在风险，例如意外访问或修改数据库中的敏感数据。为减少这些风险，请确保数据库连接权限尽可能受限，以满足链/代理的特定需求。虽然这种方法能够降低风险，但并不能完全消除风险。

```python
from langchain.chains import GraphCypherQAChain
from langchain_openai import ChatOpenAI

graph.refresh_schema()

cypher_chain = GraphCypherQAChain.from_llm(
    cypher_llm = ChatOpenAI(temperature=0, model_name='gpt-4o'),
    qa_llm = ChatOpenAI(temperature=0, model_name='gpt-4o'), 
    graph=graph,
    verbose=True,
)
```

### 使用自然语言的查询示例

请注意，在以下示例中，Cypher 查询执行的结果是如何作为上下文提供给大语言模型（LLM）的：

#### **"*Emily Chen 发布了多少篇文章？*"**

在这个示例中，我们的问题“*Emily Chen 发布了多少篇文章？*”将被转换为以下 Cypher 查询：

```
MATCH (r:Researcher {name: "Emily Chen"})-[:PUBLISHED]->(a:Article)
RETURN COUNT(a) AS numberOfArticles
```

该查询通过匹配名称为“Emily Chen”的 `Researcher` 节点，并遍历与之相关的 `PUBLISHED` 关系，连接到 `Article` 节点。然后，它计算与“Emily Chen”连接的 `Article` 节点的数量。

执行查询后，结果将作为上下文提供给 LLM，LLM 基于这个上下文来生成回答。

```python
# the answer should be '7'
cypher_chain.invoke(
    {"query": "How many articles has published Emily Chen?"}
)
```

#### **"*是否有任何一对研究人员共同发布了超过三篇文章？*"**

在这个示例中，查询“*是否有任何一对研究人员共同发布了超过三篇文章？*”将结果转换为以下 Cypher 查询：

```
MATCH (r1:Researcher)-[:PUBLISHED]->(a:Article)<-[:PUBLISHED]-(r2:Researcher)
WHERE r1 <> r2
WITH r1, r2, COUNT(a) AS sharedArticles
WHERE sharedArticles > 3
RETURN r1.name, r2.name, sharedArticles
```

该查询首先从 `Researcher` 节点出发，遍历 `PUBLISHED` 关系，找到与之连接的 `Article` 节点，然后再次遍历，查找与另一位 `Researcher` 节点的连接。通过这种方式，查询找出那些共同发表了超过三篇文章的研究人员对。最终，结果将作为上下文提供给 LLM，LLM 会基于这个上下文生成回答。

```python
# the answer should be David Johnson & Emily Chen, Robert Taylor & Emily Chen
cypher_chain.invoke(
    {"query": "are there any pair of researchers who have published more than three articles together?"}
)
```

#### **"*哪位研究人员与最多的同行合作过？*"**

让我们找出哪位研究人员与最多的同行合作过。  
我们的查询“*哪位研究人员与最多的同行合作过？*”现在转换为以下 Cypher 查询：

```
MATCH (r:Researcher)-[:PUBLISHED]->(:Article)<-[:PUBLISHED]-(peer:Researcher)
WITH r, COUNT(DISTINCT peer) AS peerCount
RETURN r.name AS researcher, peerCount
ORDER BY peerCount DESC
LIMIT 1
```

在这个查询中，我们从所有 `Researcher` 节点出发，遍历它们的 `PUBLISHED` 关系，找到与之连接的 `Article` 节点。对于每个 `Article` 节点，Neo4j 会继续回溯，查找那些也发表了同一篇文章的其他 `Researcher` 节点（同行）。通过这种方式，查询能够计算出每位研究人员与多少位同行合作，并按合作次数降序排列，最终返回合作最多的研究人员及其同行数量。

```python
# the answer should be 'David Johnson'
cypher_chain.invoke(
    {"query": "Which researcher has collaborated with the most peers?"}
)
```

----