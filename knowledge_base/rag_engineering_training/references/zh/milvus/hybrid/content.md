# 使用 Milvus 进行混合搜索

如果您想体验本教程的最终效果，可以直接访问 https://demos.milvus.io/hybrid-search/

在本教程中，我们将演示如何利用[Milvus](https://milvus.io/docs/multi-vector-search.md)和[BGE-M3 模型](https://github.com/FlagOpen/FlagEmbedding/tree/master/FlagEmbedding/BGE_M3)进行混合搜索。BGE-M3 模型可以将文本转换为密集向量和稀疏向量。Milvus 支持在一个 Collections 中存储这两种向量，从而可以进行混合搜索，增强搜索结果的相关性。

Milvus 支持密集、稀疏和混合检索方法：

- 密集检索：利用语义上下文来理解查询背后的含义。

- 稀疏检索：强调关键词匹配，根据特定术语查找结果，相当于全文检索。

- 混合检索：结合了密集和稀疏两种方法，捕捉完整的上下文和特定的关键词，从而获得全面的搜索结果。

通过整合这些方法，Milvus 混合搜索平衡了语义和词汇的相似性，提高了搜索结果的整体相关性。本笔记本将介绍这些检索策略的设置和使用过程，并重点介绍它们在各种搜索场景中的有效性。

### 依赖关系和环境

```shell
$ pip install --upgrade pymilvus "pymilvus[model]"
```

### 下载数据集

要演示搜索，我们需要一个文档语料库。让我们使用 Quora 重复问题数据集，并将其放在本地目录中。

数据集来源：[首次发布的 Quora 数据集：问题对](https://www.quora.com/q/quoradata/First-Quora-Dataset-Release-Question-Pairs)

```shell
# Run this cell to download the dataset
$ wget http://qim.fs.quoracdn.net/quora_duplicate_questions.tsv
```

### 加载和准备数据

我们将加载数据集，并准备一个小型语料库用于搜索。

```python
import pandas as pd

file_path = "quora_duplicate_questions.tsv"
df = pd.read_csv(file_path, sep="\t")
questions = set()
for _, row in df.iterrows():
    obj = row.to_dict()
    questions.add(obj["question1"][:512])
    questions.add(obj["question2"][:512])
    if len(questions) > 500:  # Skip this if you want to use the full dataset
        break

docs = list(questions)

# example question
print(docs[0])
```

```text
What is the strongest Kevlar cord?
```

### 使用 BGE-M3 模型进行嵌入

BGE-M3 模型可以将文本嵌入为密集向量和稀疏向量。

```python
from pymilvus.model.hybrid import BGEM3EmbeddingFunction

ef = BGEM3EmbeddingFunction(use_fp16=False, device="cpu")
dense_dim = ef.dim["dense"]

# Generate embeddings using BGE-M3 model
docs_embeddings = ef(docs)
```

```text
Fetching 30 files: 100%|██████████| 30/30 [00:00<00:00, 302473.85it/s]
Inference Embeddings: 100%|██████████| 32/32 [01:59<00:00,  3.74s/it]
```

### 设置 Milvus Collections 和索引

我们将设置 Milvus Collections 并为向量场创建索引。

- 将 uri 设置为本地文件，如"./milvus.db"，是最方便的方法，因为它会自动利用[Milvus Lite](https://milvus.io/docs/milvus_lite.md)将所有数据存储在此文件中。

- 如果你有大规模数据，比如超过一百万个向量，你可以在[Docker 或 Kubernetes](https://milvus.io/docs/quickstart.md) 上设置性能更强的 Milvus 服务器。在此设置中，请使用服务器 uri（如 http://localhost:19530）作为您的 uri。

- 如果你想使用[Zilliz Cloud](https://zilliz.com/cloud)（Milvus 的全托管云服务），请调整 uri 和令牌，它们与 Zilliz Cloud 中的[公共端点和 API 密钥](https://docs.zilliz.com/docs/on-zilliz-cloud-console#cluster-details)相对应。

```python
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
)

# Connect to Milvus given URI
connections.connect(uri="./milvus.db")

# Specify the data schema for the new Collection
fields = [
    # Use auto generated id as primary key
    FieldSchema(
        name="pk", dtype=DataType.VARCHAR, is_primary=True, auto_id=True, max_length=100
    ),
    # Store the original text to retrieve based on semantically distance
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=512),
    # Milvus now supports both sparse and dense vectors,
    # we can store each in a separate field to conduct hybrid search on both vectors
    FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
    FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=dense_dim),
]
schema = CollectionSchema(fields)

# Create collection (drop the old one if exists)
col_name = "hybrid_demo"
if utility.has_collection(col_name):
    Collection(col_name).drop()
col = Collection(col_name, schema, consistency_level="Bounded")

# To make vector search efficient, we need to create indices for the vector fields
sparse_index = {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"}
col.create_index("sparse_vector", sparse_index)
dense_index = {"index_type": "AUTOINDEX", "metric_type": "IP"}
col.create_index("dense_vector", dense_index)
col.load()
```

### 将数据插入 Milvus Collections

将文档及其 Embeddings 插入 Collections。

```python
# For efficiency, we insert 50 records in each small batch
for i in range(0, len(docs), 50):
    batched_entities = [
        docs[i : i + 50],
        docs_embeddings["sparse"][i : i + 50],
        docs_embeddings["dense"][i : i + 50],
    ]
    col.insert(batched_entities)
print("Number of entities inserted:", col.num_entities)
```

```text
Number of entities inserted: 502
```

### 输入搜索查询

```python
# Enter your search query
query = input("Enter your search query: ")
print(query)

# Generate embeddings for the query
query_embeddings = ef([query])
# print(query_embeddings)
```

```text
How to start learning programming?
```

### 运行搜索

我们将首先准备一些有用的函数来运行搜索：

- `dense_search`只搜索密集向量场

- `sparse_search`只在稀疏向量场中搜索

- `hybrid_search`：使用加权 Reranker 在密集向量场和向量场中搜索

```python
from pymilvus import (
    AnnSearchRequest,
    WeightedRanker,
)


def dense_search(col, query_dense_embedding, limit=10):
    search_params = {"metric_type": "IP", "params": {}}
    res = col.search(
        [query_dense_embedding],
        anns_field="dense_vector",
        limit=limit,
        output_fields=["text"],
        param=search_params,
    )[0]
    return [hit.get("text") for hit in res]


def sparse_search(col, query_sparse_embedding, limit=10):
    search_params = {
        "metric_type": "IP",
        "params": {},
    }
    res = col.search(
        [query_sparse_embedding],
        anns_field="sparse_vector",
        limit=limit,
        output_fields=["text"],
        param=search_params,
    )[0]
    return [hit.get("text") for hit in res]


def hybrid_search(
    col,
    query_dense_embedding,
    query_sparse_embedding,
    sparse_weight=1.0,
    dense_weight=1.0,
    limit=10,
):
    dense_search_params = {"metric_type": "IP", "params": {}}
    dense_req = AnnSearchRequest(
        [query_dense_embedding], "dense_vector", dense_search_params, limit=limit
    )
    sparse_search_params = {"metric_type": "IP", "params": {}}
    sparse_req = AnnSearchRequest(
        [query_sparse_embedding], "sparse_vector", sparse_search_params, limit=limit
    )
    rerank = WeightedRanker(sparse_weight, dense_weight)
    res = col.hybrid_search(
        [sparse_req, dense_req], rerank=rerank, limit=limit, output_fields=["text"]
    )[0]
    return [hit.get("text") for hit in res]
```

让我们用定义的函数运行三种不同的搜索：

```python
dense_results = dense_search(col, query_embeddings["dense"][0])
sparse_results = sparse_search(col, query_embeddings["sparse"][[0]])
hybrid_results = hybrid_search(
    col,
    query_embeddings["dense"][0],
    query_embeddings["sparse"][[0]],
    sparse_weight=0.7,
    dense_weight=1.0,
)
```

### 显示搜索结果

要显示密集搜索、稀疏搜索和混合搜索的结果，我们需要一些工具来格式化搜索结果。

```python
def doc_text_formatting(ef, query, docs):
    tokenizer = ef.model.tokenizer
    query_tokens_ids = tokenizer.encode(query, return_offsets_mapping=True)
    query_tokens = tokenizer.convert_ids_to_tokens(query_tokens_ids)
    formatted_texts = []

    for doc in docs:
        ldx = 0
        landmarks = []
        encoding = tokenizer.encode_plus(doc, return_offsets_mapping=True)
        tokens = tokenizer.convert_ids_to_tokens(encoding["input_ids"])[1:-1]
        offsets = encoding["offset_mapping"][1:-1]
        for token, (start, end) in zip(tokens, offsets):
            if token in query_tokens:
                if len(landmarks) != 0 and start == landmarks[-1]:
                    landmarks[-1] = end
                else:
                    landmarks.append(start)
                    landmarks.append(end)
        close = False
        formatted_text = ""
        for i, c in enumerate(doc):
            if ldx == len(landmarks):
                pass
            elif i == landmarks[ldx]:
                if close:
                    formatted_text += "</span>"
                else:
                    formatted_text += "<span style='color:red'>"
                close = not close
                ldx = ldx + 1
            formatted_text += c
        if close is True:
            formatted_text += "</span>"
        formatted_texts.append(formatted_text)
    return formatted_texts
```

然后，我们就可以用带高亮显示的文本显示搜索结果了：

```python
from IPython.display import Markdown, display

# Dense search results
display(Markdown("**Dense Search Results:**"))
formatted_results = doc_text_formatting(ef, query, dense_results)
for result in dense_results:
    display(Markdown(result))

# Sparse search results
display(Markdown("\n**Sparse Search Results:**"))
formatted_results = doc_text_formatting(ef, query, sparse_results)
for result in formatted_results:
    display(Markdown(result))

# Hybrid search results
display(Markdown("\n**Hybrid Search Results:**"))
formatted_results = doc_text_formatting(ef, query, hybrid_results)
for result in formatted_results:
    display(Markdown(result))
```

密集搜索结果：

开始学习机器人技术的最佳方法是什么？

如何学习 java 等计算机语言？

如何开始学习信息安全？

什么是 Java 编程？如何学习 Java 编程语言？

如何学习计算机安全？

开始学习机器人技术的最佳方法是什么？哪种开发板最适合我开始工作？

如何学说流利的英语？

学习法语的最佳方法是什么？

如何让物理变得简单易学？

如何准备 UPSC？

稀疏搜索结果：

什么是 Java 编程？如何学习 Java 编程语言？

 开始学习机器人技术的最佳方法是什么？

机器 学习的替代方法是什么 ？

如何使用 C 语言在 Linux 中创建新终端和新 shell ？

如何使用 C 语言在新终端（Linux 终端）中创建新 shell？

在海得拉巴 做哪一行比较好？

在海得拉巴做哪一行比较好？

 启动机器人技术的最佳方式是什么？哪种开发板最适合我 开始工作？

新手需要掌握哪些数学知识 才能理解计算机 编程的算法 ？哪些算法书籍适合完全初学者？

如何让生活适合自己，不让生活在精神上和情感上虐待自己？

混合搜索结果：

 开始学习机器人技术的最佳方法是什么？哪种开发板最好？

什么是 Java 编程？如何学习 Java 编程语言？

 开始学习机器人技术的最佳方法是什么？

如何备考 UPSC？

如何让物理变得简单 易学？

学习法语 的最佳方法是什么？

如何 学说流利的英语？

如何学习计算机安全？

如何开始 学习信息安全？

如何学习 java 等计算机语言？

机器 学习的替代方法是什么？

如何使用 C 语言在 Linux 中创建新的终端和新的 shell ？

如何使用 C 语言在新终端（Linux 终端）中创建新 shell？

在海得拉巴 做哪一行比较好？

在海得拉巴做哪一行比较好？

一个完全的新手需要掌握哪些数学知识 才能理解计算机 编程的算法 ？哪些算法书籍适合完全初学者？

如何让生活适合自己，让生活不再从精神和情感上虐待自己？

### 快速部署

要了解如何使用本教程开始在线演示，请参考[示例应用程序](https://github.com/milvus-io/bootcamp/tree/master/tutorials/quickstart/apps/hybrid_demo_with_milvus)。
