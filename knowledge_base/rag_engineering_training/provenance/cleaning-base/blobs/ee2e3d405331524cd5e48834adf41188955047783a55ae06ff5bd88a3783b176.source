# 使用 LangChain 和 Milvus 进行全文检索

[全文搜索](https://milvus.io/docs/full-text-search.md#Full-Text-Search)是一种通过匹配文本中特定关键词或短语来检索文档的传统方法。它根据词频等因素计算出的相关性分数对结果进行排序。语义搜索更善于理解含义和上下文，而全文搜索则擅长精确的关键词匹配，因此是语义搜索的有益补充。BM25 算法被广泛用于全文搜索的排序，并在检索增强生成（RAG）中发挥着关键作用。

[Milvus 2.5](https://milvus.io/blog/introduce-milvus-2-5-full-text-search-powerful-metadata-filtering-and-more.md)引入了使用 BM25 的本地全文搜索功能。这种方法将文本转换为代表 BM25 分数的稀疏向量。您只需输入原始文本，Milvus 就会自动生成并存储稀疏向量，无需手动生成稀疏嵌入。

LangChain 与 Milvus 的集成也引入了这一功能，简化了将全文检索纳入 RAG 应用程序的过程。通过将全文搜索与密集向量的语义搜索相结合，可以实现一种混合方法，既能利用密集嵌入的语义上下文，又能利用单词匹配的精确关键词相关性。这种整合提高了搜索系统的准确性、相关性和用户体验。

本教程将展示如何使用 LangChain 和 Milvus 在应用程序中实现全文搜索。

- 目前，Milvus Standalone、Milvus Distributed 和 Zilliz Cloud 均提供全文搜索功能，但 Milvus Lite 尚不支持该功能（该功能计划在未来实现）。如需了解更多信息，请访问 support@zilliz.com。

- 在继续本教程之前，请确保您已基本了解[全文搜索](https://milvus.io/docs/full-text-search.md#Full-Text-Search)和 LangChain Milvus 集成的[基本用法](https://milvus.io/docs/basic_usage_langchain.md)。

## 前提条件

在运行本笔记本之前，请确保已安装以下依赖项：

```shell
! pip install --upgrade --quiet  langchain langchain-core langchain-community langchain-text-splitters langchain-milvus langchain-openai bs4 #langchain-voyageai
```

如果您使用的是 Google Colab，要启用刚刚安装的依赖项，可能需要重启运行时（点击屏幕上方的 "运行时 "菜单，从下拉菜单中选择 "重启会话"）。

我们将使用 OpenAI 的模型。您应准备好[OpenAI](https://platform.openai.com/docs/quickstart) 的环境变量`OPENAI_API_KEY` 。

```python
import os

os.environ["OPENAI_API_KEY"] = "sk-***********"
```

指定您的 Milvus 服务器`URI` （可选`TOKEN` ）。有关如何安装和启动 Milvus 服务器，请参阅本[指南](https://milvus.io/docs/install_standalone-docker-compose.md)。

```python
URI = "http://localhost:19530"
# TOKEN = ...
```

准备一些示例文档：

```python
from langchain_core.documents import Document

docs = [
    Document(page_content="I like this apple", metadata={"category": "fruit"}),
    Document(page_content="I like swimming", metadata={"category": "sport"}),
    Document(page_content="I like dogs", metadata={"category": "pets"}),
]
```

## 使用 BM25 函数初始化

### 混合搜索

对于全文检索，Milvus VectorStore 接受一个`builtin_function` 参数。通过该参数，可以传入`BM25BuiltInFunction` 的实例。这与语义搜索不同，语义搜索通常将密集嵌入传入`VectorStore` 、

下面是一个在 Milvus 中使用 OpenAI dense embedding 进行语义搜索和 BM25 进行全文搜索的混合搜索的简单示例：

```python
from langchain_milvus import Milvus, BM25BuiltInFunction
from langchain_openai import OpenAIEmbeddings


vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=OpenAIEmbeddings(),
    builtin_function=BM25BuiltInFunction(),
    # `dense` is for OpenAI embeddings, `sparse` is the output field of BM25 function
    vector_field=["dense", "sparse"],
    connection_args={
        "uri": URI,
    },
    # Strong consistency waits for all loads to complete, adding latency with large datasets
    # consistency_level="Strong",
    # drop_old=True,
)
```

在上面的代码中，我们定义了`BM25BuiltInFunction` 的一个实例，并将其传递给`Milvus` 对象。`BM25BuiltInFunction` 是一个轻量级的封装类。 [`Function`](https://milvus.io/docs/manage-collections.md#Function)的轻量级封装类。

您可以在`BM25BuiltInFunction` 的参数中指定该函数的输入和输出字段：

- `input_field_names` (str)：输入字段的名称，默认为`text` 。它表示此函数读取哪个字段作为输入。

- `output_field_names` (str)：输出字段的名称，默认为`sparse` 。它表示此函数将计算结果输出到哪个字段。

请注意，在上述 Milvus 初始化参数中，我们也指定了`vector_field=["dense", "sparse"]` 。由于`sparse` 字段被当作由`BM25BuiltInFunction` 定义的输出字段，因此其他`dense` 字段将被自动分配给 OpenAIEmbeddings 的输出字段。

在实践中，尤其是在组合多个 Embeddings 或函数时，我们建议明确指定每个函数的输入和输出字段，以避免歧义。

在下面的示例中，我们明确指定了`BM25BuiltInFunction` 的输入字段和输出字段，从而清楚地说明了内置函数用于哪个字段。

```python
# from langchain_voyageai import VoyageAIEmbeddings

embedding1 = OpenAIEmbeddings(model="text-embedding-ada-002")
embedding2 = OpenAIEmbeddings(model="text-embedding-3-large")
# embedding2 = VoyageAIEmbeddings(model="voyage-3")  # You can also use embedding from other embedding model providers, e.g VoyageAIEmbeddings


vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=[embedding1, embedding2],
    builtin_function=BM25BuiltInFunction(
        input_field_names="text", output_field_names="sparse"
    ),
    text_field="text",  # `text` is the input field name of BM25BuiltInFunction
    # `sparse` is the output field name of BM25BuiltInFunction, and `dense1` and `dense2` are the output field names of embedding1 and embedding2
    vector_field=["dense1", "dense2", "sparse"],
    connection_args={
        "uri": URI,
    },
    # Strong consistency waits for all loads to complete, adding latency with large datasets
    # consistency_level="Strong",
    # drop_old=True,
)

vectorstore.vector_fields
```

```text
['dense1', 'dense2', 'sparse']
```

在本例中，我们有三个向量字段。其中，`sparse` 作为`BM25BuiltInFunction` 的输出字段，而其他两个字段`dense1` 和`dense2` 则被自动指定为两个`OpenAIEmbeddings` 模型的输出字段（根据顺序）。

这样，就可以定义多个向量场，并为其分配不同的嵌入或函数组合，从而实现混合搜索。

执行混合搜索时，我们只需传入查询文本，并选择性地设置 topK 和 Reranker 参数。`vectorstore` 实例会自动处理向量嵌入和内置函数，最后使用 Reranker 对结果进行细化。搜索过程的底层实现细节对用户是隐藏的。

```python
vectorstore.similarity_search(
    "Do I like apples?", k=1
)  # , ranker_type="weighted", ranker_params={"weights":[0.3, 0.3, 0.4]})
```

```text
[Document(metadata={'category': 'fruit', 'pk': 454646931479251897}, page_content='I like this apple')]
```

有关混合搜索的更多信息，可以参考[混合搜索介绍](https://milvus.io/docs/multi-vector-search.md#Hybrid-Search)和这篇[LangChain Milvus 混合搜索教程](https://milvus.io/docs/milvus_hybrid_search_retriever.md)。

### 无嵌入的 BM25 搜索

如果只想使用 BM25 函数执行全文搜索，而不想使用任何基于嵌入的语义搜索，可以将嵌入参数设置为`None` ，并只保留指定为 BM25 函数实例的`builtin_function` 。向量字段只有 "稀疏 "字段。例如

```python
vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=None,
    builtin_function=BM25BuiltInFunction(
        output_field_names="sparse",
    ),
    vector_field="sparse",
    connection_args={
        "uri": URI,
    },
    # Strong consistency waits for all loads to complete, adding latency with large datasets
    # consistency_level="Strong",
    # drop_old=True,
)

vectorstore.vector_fields
```

```text
['sparse']
```

## 自定义分析器

分析器在全文检索中至关重要，它可以将句子分解成词块，并执行词法分析，如词干分析和停止词删除。分析器通常针对特定语言。您可以参考[本指南](https://milvus.io/docs/analyzer-overview.md#Analyzer-Overview)，了解有关 Milvus 分析器的更多信息。

Milvus 支持两种类型的分析器：内置分析器和自定义分析器。默认情况下，`BM25BuiltInFunction` 将使用[标准的内置分析器](https://milvus.io/docs/standard-analyzer.md)，这是最基本的分析器，会用标点符号标记文本。

如果想使用其他分析器或自定义分析器，可以在`BM25BuiltInFunction` 初始化时传递`analyzer_params` 参数。

```python
analyzer_params_custom = {
    "tokenizer": "standard",
    "filter": [
        "lowercase",  # Built-in filter
        {"type": "length", "max": 40},  # Custom filter
        {"type": "stop", "stop_words": ["of", "to"]},  # Custom filter
    ],
}


vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=OpenAIEmbeddings(),
    builtin_function=BM25BuiltInFunction(
        output_field_names="sparse",
        enable_match=True,
        analyzer_params=analyzer_params_custom,
    ),
    vector_field=["dense", "sparse"],
    connection_args={
        "uri": URI,
    },
    # Strong consistency waits for all loads to complete, adding latency with large datasets
    # consistency_level="Strong",
    # drop_old=True,
)
```

我们可以看看 Milvus Collections 的 Schema，确保定制的分析器设置正确。

```python
vectorstore.col.schema
```

```text
{'auto_id': True, 'description': '', 'fields': [{'name': 'text', 'description': '', 'type': <DataType.VARCHAR: 21>, 'params': {'max_length': 65535, 'enable_match': True, 'enable_analyzer': True, 'analyzer_params': {'tokenizer': 'standard', 'filter': ['lowercase', {'type': 'length', 'max': 40}, {'type': 'stop', 'stop_words': ['of', 'to']}]}}}, {'name': 'pk', 'description': '', 'type': <DataType.INT64: 5>, 'is_primary': True, 'auto_id': True}, {'name': 'dense', 'description': '', 'type': <DataType.FLOAT_VECTOR: 101>, 'params': {'dim': 1536}}, {'name': 'sparse', 'description': '', 'type': <DataType.SPARSE_FLOAT_VECTOR: 104>, 'is_function_output': True}, {'name': 'category', 'description': '', 'type': <DataType.VARCHAR: 21>, 'params': {'max_length': 65535}}], 'enable_dynamic_field': False, 'functions': [{'name': 'bm25_function_de368e79', 'description': '', 'type': <FunctionType.BM25: 1>, 'input_field_names': ['text'], 'output_field_names': ['sparse'], 'params': {}}]}
```

更多概念详情，如`analyzer`,`tokenizer`,`filter`,`enable_match`,`analyzer_params` ，请参阅[分析器文档](https://milvus.io/docs/analyzer-overview.md)。

### 多语言分析仪

Milvus 支持多语言分析器，可分析多种语言的文档。在`BM25BuiltInFunction` 中使用`multi_analyzer_params` ：

```python
from pymilvus import DataType

multi_analyzer_params = {
    "analyzers": {
        "english": {"type": "english"},
        "chinese": {"type": "chinese"},
        "default": {"tokenizer": "icu"},
    },
    "by_field": "language",
}

vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=OpenAIEmbeddings(),
    builtin_function=BM25BuiltInFunction(
        output_field_names="sparse",
        multi_analyzer_params=multi_analyzer_params,
    ),
    vector_field=["dense", "sparse"],
    metadata_schema={"language": {"dtype": DataType.VARCHAR, "kwargs": {"max_length": 100}}},
    connection_args={"uri": URI},
)
```

更多详情，请参阅[多语言分析器文档](https://milvus.io/docs/multi-language-analyzers.md)。

## 在 RAG 中使用混合搜索和 Rerankers

我们已经学习了如何在 LangChain 和 Milvus 中使用基本的 BM25 内置功能。下面让我们介绍一种使用混合检索和重排的优化 RAG 实现。

该图显示了混合检索和重排过程，将用于关键词匹配的 BM25 和用于语义检索的向量搜索结合在一起。来自两种方法的结果经过合并、Rerankers 和传递给 LLM 生成最终答案。

混合搜索兼顾了精确性和语义理解，提高了不同查询的准确性和稳健性。它通过 BM25 全文检索和向量搜索检索候选内容，同时确保语义、上下文感知和精确检索。

让我们从一个例子开始。

### 准备数据

我们使用 Langchain WebBaseLoader 从网络源加载文档，并使用 RecursiveCharacterTextSplitter 将文档分割成块。

```python
import bs4
from langchain_community.document_loaders import WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Create a WebBaseLoader instance to load documents from web sources
loader = WebBaseLoader(
    web_paths=(
        "https://lilianweng.github.io/posts/2023-06-23-agent/",
        "https://lilianweng.github.io/posts/2023-03-15-prompt-engineering/",
    ),
    bs_kwargs=dict(
        parse_only=bs4.SoupStrainer(
            class_=("post-content", "post-title", "post-header")
        )
    ),
)
# Load documents from web sources using the loader
documents = loader.load()
# Initialize a RecursiveCharacterTextSplitter for splitting text into chunks
text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

# Split the documents into chunks using the text_splitter
docs = text_splitter.split_documents(documents)

# Let's take a look at the first document
docs[1]
```

```text
Document(metadata={'source': 'https://lilianweng.github.io/posts/2023-06-23-agent/'}, page_content='Fig. 1. Overview of a LLM-powered autonomous agent system.\nComponent One: Planning#\nA complicated task usually involves many steps. An agent needs to know what they are and plan ahead.\nTask Decomposition#\nChain of thought (CoT; Wei et al. 2022) has become a standard prompting technique for enhancing model performance on complex tasks. The model is instructed to “think step by step” to utilize more test-time computation to decompose hard tasks into smaller and simpler steps. CoT transforms big tasks into multiple manageable tasks and shed lights into an interpretation of the model’s thinking process.\nTree of Thoughts (Yao et al. 2023) extends CoT by exploring multiple reasoning possibilities at each step. It first decomposes the problem into multiple thought steps and generates multiple thoughts per step, creating a tree structure. The search process can be BFS (breadth-first search) or DFS (depth-first search) with each state evaluated by a classifier (via a prompt) or majority vote.\nTask decomposition can be done (1) by LLM with simple prompting like "Steps for XYZ.\\n1.", "What are the subgoals for achieving XYZ?", (2) by using task-specific instructions; e.g. "Write a story outline." for writing a novel, or (3) with human inputs.\nAnother quite distinct approach, LLM+P (Liu et al. 2023), involves relying on an external classical planner to do long-horizon planning. This approach utilizes the Planning Domain Definition Language (PDDL) as an intermediate interface to describe the planning problem. In this process, LLM (1) translates the problem into “Problem PDDL”, then (2) requests a classical planner to generate a PDDL plan based on an existing “Domain PDDL”, and finally (3) translates the PDDL plan back into natural language. Essentially, the planning step is outsourced to an external tool, assuming the availability of domain-specific PDDL and a suitable planner which is common in certain robotic setups but not in many other domains.\nSelf-Reflection#')
```

### 将文档加载到 Milvus 向量存储中

如上介绍，我们将准备好的文档初始化并加载到 Milvus 向量存储中，其中包含两个向量字段：`dense` 用于 OpenAI 嵌入，`sparse` 用于 BM25 函数。

```python
vectorstore = Milvus.from_documents(
    documents=docs,
    embedding=OpenAIEmbeddings(),
    builtin_function=BM25BuiltInFunction(),
    vector_field=["dense", "sparse"],
    connection_args={
        "uri": URI,
    },
    # Strong consistency waits for all loads to complete, adding latency with large datasets
    # consistency_level="Strong",
    # drop_old=True,
)
```

### 构建 RAG 链

我们准备好 LLM 实例和提示，然后使用 LangChain 表达式语言将它们结合到 RAG 管道中。

```python
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# Initialize the OpenAI language model for response generation
llm = ChatOpenAI(model_name="gpt-4o", temperature=0)

# Define the prompt template for generating AI responses
PROMPT_TEMPLATE = """
Human: You are an AI assistant, and provides answers to questions by using fact based and statistical information when possible.
Use the following pieces of information to provide a concise answer to the question enclosed in <question> tags.
If you don't know the answer, just say that you don't know, don't try to make up an answer.
<context>
{context}
</context>

<question>
{question}
</question>

The response should be specific and use statistics or numbers when possible.

Assistant:"""

# Create a PromptTemplate instance with the defined template and input variables
prompt = PromptTemplate(
    template=PROMPT_TEMPLATE, input_variables=["context", "question"]
)
# Convert the vector store to a retriever
retriever = vectorstore.as_retriever()


# Define a function to format the retrieved documents
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)
```

使用 LCEL（LangChain 表达式语言）构建 RAG 链。

```python
# Define the RAG (Retrieval-Augmented Generation) chain for AI response generation
rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

# rag_chain.get_graph().print_ascii()
```

使用特定问题调用 RAG 链并获取响应

```python
query = "What is PAL and PoT?"
res = rag_chain.invoke(query)
res
```

```text
'PAL (Program-aided Language models) and PoT (Program of Thoughts prompting) are approaches that involve using language models to generate programming language statements to solve natural language reasoning problems. This method offloads the solution step to a runtime, such as a Python interpreter, allowing for complex computation and reasoning to be handled externally. PAL and PoT rely on language models with strong coding skills to effectively generate and execute these programming statements.'
```

恭喜您！您已经构建了由 Milvus 和 LangChain 支持的混合（密集向量 + 稀疏 bm25 函数）搜索 RAG 链。
