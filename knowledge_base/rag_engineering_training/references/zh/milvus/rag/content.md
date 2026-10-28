# 用 Milvus 创建 RAG

在本教程中，我们将向您展示如何使用 Milvus 构建 RAG（检索-增强生成）管道。

RAG 系统结合了检索系统和生成模型，可根据给定提示生成新文本。系统首先使用 Milvus 从语料库中检索相关文档，然后使用生成模型根据检索到的文档生成新文本。

## 准备工作

### 依赖和环境

```python
$ pip install --upgrade pymilvus openai requests tqdm
```

如果使用的是 Google Colab，要启用刚刚安装的依赖项，可能需要重新启动运行时。(点击屏幕上方的 "Runtime（运行时）"菜单，从下拉菜单中选择 "Restart session（重新启动会话）"）。

在本例中，我们将使用 OpenAI 作为 LLM。您应将[api key](https://platform.openai.com/docs/quickstart) `OPENAI_API_KEY` 作为环境变量。

```python
import os

os.environ["OPENAI_API_KEY"] = "sk-***********"
```

### 准备数据

我们使用[Milvus 文档 2.4.x](https://github.com/milvus-io/milvus-docs/releases/download/v2.4.6-preview/milvus_docs_2.4.x_en.zip)中的常见问题页面作为 RAG 中的私有知识，这对于简单的 RAG 管道来说是一个很好的数据源。

下载 zip 文件并将文档解压缩到`milvus_docs` 文件夹中。

```bash
$ wget https://github.com/milvus-io/milvus-docs/releases/download/v2.4.6-preview/milvus_docs_2.4.x_en.zip
$ unzip -q milvus_docs_2.4.x_en.zip -d milvus_docs
```

我们从`milvus_docs/en/faq` 文件夹中加载所有标记文件。对于每个文档，我们只需简单地使用 "#"来分隔文件中的内容，这样就能大致分隔出 markdown 文件中每个主要部分的内容。

```python
from glob import glob

text_lines = []

for file_path in glob("milvus_docs/en/faq/*.md", recursive=True):
    with open(file_path, "r") as file:
        file_text = file.read()

    text_lines += file_text.split("# ")
```

### 准备嵌入模型

我们初始化 OpenAI 客户端，准备嵌入模型。

```python
from openai import OpenAI

openai_client = OpenAI()
```

定义一个函数，使用 OpenAI 客户端生成文本嵌入。我们以[text-embedding-3-small](https://platform.openai.com/docs/guides/embeddings)模型为例。

```python
def emb_text(text):
    return (
        openai_client.embeddings.create(input=text, model="text-embedding-3-small")
        .data[0]
        .embedding
    )
```

生成测试嵌入并打印其维度和前几个元素。

```python
test_embedding = emb_text("This is a test")
embedding_dim = len(test_embedding)
print(embedding_dim)
print(test_embedding[:10])
```

```text
1536
[0.00988506618887186, -0.005540902726352215, 0.0068014683201909065, -0.03810417652130127, -0.018254263326525688, -0.041231658309698105, -0.007651153020560741, 0.03220026567578316, 0.01892443746328354, 0.00010708322952268645]
```

## 将数据载入 Milvus

### 创建 Collections

```python
from pymilvus import MilvusClient

milvus_client = MilvusClient(uri="./milvus_demo.db")

collection_name = "my_rag_collection"
```

至于`MilvusClient` 的参数：

- 将`uri` 设置为本地文件，如`./milvus.db` ，是最方便的方法，因为它会自动利用[Milvus Lite](https://milvus.io/docs/milvus_lite.md)将所有数据存储在此文件中。

- 如果数据规模较大，可以在[docker 或 kubernetes](https://milvus.io/docs/quickstart.md) 上设置性能更强的 Milvus 服务器。在此设置中，请使用服务器 uri，例如`http://localhost:19530` ，作为您的`uri` 。

- 如果你想使用[Zilliz Cloud](https://zilliz.com/cloud)（Milvus 的全托管云服务），请调整`uri` 和`token` ，它们与 Zilliz Cloud 中的[公共端点和 Api 密钥](https://docs.zilliz.com/docs/on-zilliz-cloud-console#free-cluster-details)相对应。

检查 Collections 是否已存在，如果已存在，则删除它。

```python
if milvus_client.has_collection(collection_name):
    milvus_client.drop_collection(collection_name)
```

使用指定参数创建新 Collections。

如果我们不指定任何字段信息，Milvus 会自动创建一个主键的默认`id` 字段，以及一个存储向量数据的`vector` 字段。保留的 JSON 字段用于存储非 Schema 定义的字段及其值。

```python
milvus_client.create_collection(
    collection_name=collection_name,
    dimension=embedding_dim,
    metric_type="IP",  # Inner product distance
    consistency_level="Bounded",  # Supported values are (`"Strong"`, `"Session"`, `"Bounded"`, `"Eventually"`). See https://milvus.io/docs/tune_consistency.md#Consistency-Level for more details.
)
```

### 插入数据

遍历文本行，创建 Embeddings，然后将数据插入 Milvus。

这里有一个新字段`text` ，它是 Collections Schema 中的一个非定义字段。它将自动添加到保留的 JSON 动态字段中，在高层次上可将其视为普通字段。

```python
from tqdm import tqdm

data = []

for i, line in enumerate(tqdm(text_lines, desc="Creating embeddings")):
    data.append({"id": i, "vector": emb_text(line), "text": line})

milvus_client.insert(collection_name=collection_name, data=data)
```

```text
Creating embeddings: 100%|██████████| 72/72 [00:27<00:00,  2.67it/s]





{'insert_count': 72,
 'ids': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71],
 'cost': 0}
```

## 构建 RAG

### 为查询检索数据

让我们指定一个关于 Milvus 的常见问题。

```python
question = "How is data stored in milvus?"
```

在 Collections 中搜索该问题，并检索语义前 3 个匹配项。

```python
search_res = milvus_client.search(
    collection_name=collection_name,
    data=[
        emb_text(question)
    ],  # Use the `emb_text` function to convert the question to an embedding vector
    limit=3,  # Return top 3 results
    search_params={"metric_type": "IP", "params": {}},  # Inner product distance
    output_fields=["text"],  # Return the text field
)
```

让我们看看查询的搜索结果

```python
import json

retrieved_lines_with_distances = [
    (res["entity"]["text"], res["distance"]) for res in search_res[0]
]
print(json.dumps(retrieved_lines_with_distances, indent=4))
```

```text
[
    [
        " Where does Milvus store data?\n\nMilvus deals with two types of data, inserted data and metadata. \n\nInserted data, including vector data, scalar data, and collection-specific schema, are stored in persistent storage as incremental log. Milvus supports multiple object storage backends, including [MinIO](https://min.io/), [AWS S3](https://aws.amazon.com/s3/?nc1=h_ls), [Google Cloud Storage](https://cloud.google.com/storage?hl=en#object-storage-for-companies-of-all-sizes) (GCS), [Azure Blob Storage](https://azure.microsoft.com/en-us/products/storage/blobs), [Alibaba Cloud OSS](https://www.alibabacloud.com/product/object-storage-service), and [Tencent Cloud Object Storage](https://www.tencentcloud.com/products/cos) (COS).\n\nMetadata are generated within Milvus. Each Milvus module has its own metadata that are stored in etcd.\n\n###",
        0.7883545756340027
    ],
    [
        "How does Milvus handle vector data types and precision?\n\nMilvus supports Binary, Float32, Float16, and BFloat16 vector types.\n\n- Binary vectors: Store binary data as sequences of 0s and 1s, used in image processing and information retrieval.\n- Float32 vectors: Default storage with a precision of about 7 decimal digits. Even Float64 values are stored with Float32 precision, leading to potential precision loss upon retrieval.\n- Float16 and BFloat16 vectors: Offer reduced precision and memory usage. Float16 is suitable for applications with limited bandwidth and storage, while BFloat16 balances range and efficiency, commonly used in deep learning to reduce computational requirements without significantly impacting accuracy.\n\n###",
        0.6757288575172424
    ],
    [
        "How much does Milvus cost?\n\nMilvus is a 100% free open-source project.\n\nPlease adhere to [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0) when using Milvus for production or distribution purposes.\n\nZilliz, the company behind Milvus, also offers a fully managed cloud version of the platform for those that don't want to build and maintain their own distributed instance. [Zilliz Cloud](https://zilliz.com/cloud) automatically maintains data reliability and allows users to pay only for what they use.\n\n###",
        0.6421123147010803
    ]
]
```

### 使用 LLM 获取 RAG 响应

将检索到的文档转换为字符串格式。

```python
context = "\n".join(
    [line_with_distance[0] for line_with_distance in retrieved_lines_with_distances]
)
```

为语言模型定义系统和用户提示。该提示与从 Milvus 检索到的文档组装在一起。

```python
SYSTEM_PROMPT = """
Human: You are an AI assistant. You are able to find answers to the questions from the contextual passage snippets provided.
"""
USER_PROMPT = f"""
Use the following pieces of information enclosed in <context> tags to provide an answer to the question enclosed in <question> tags.
<context>
{context}
</context>
<question>
{question}
</question>
"""
```

使用 OpenAI ChatGPT 根据提示生成响应。

```python
response = openai_client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ],
)
print(response.choices[0].message.content)
```

```text
Milvus stores data in persistent storage as incremental logs, including inserted data (vector data, scalar data, and collection-specific schema) and metadata. Inserted data is stored in various object storage backends like MinIO, AWS S3, Google Cloud Storage, Azure Blob Storage, Alibaba Cloud OSS, and Tencent Cloud Object Storage. Metadata generated within Milvus is stored in etcd.
```

## 快速部署

要了解如何使用本教程启动在线演示，请参阅[示例应用程序](https://github.com/milvus-io/bootcamp/tree/master/tutorials/quickstart/apps/rag_search_with_milvus)。
