# 基于 SQL 和 Jina Reranker v2 的 RAG

_作者：[Scott Martens](https://github.com/scott-martens) @ [Jina AI](https://jina.ai)_

本教程将展示如何构建一个简单的检索增强生成（RAG）系统，该系统从 SQL 数据库中提取信息，而不是从文档存储中提取。

### 工作原理

* 给定一个 SQL 数据库，我们提取 SQL 表的定义（SQL 导出文件中的 `CREATE` 语句），并将其存储。在本教程中，我们已经为您完成了这部分操作，表定义被存储在内存中，作为一个列表。根据此示例扩展可能需要更复杂的存储方案。
* 用户输入一个自然语言查询。
* [Jina Reranker v2](https://jina.ai/reranker/)（[`jinaai/jina-reranker-v2-base-multilingual`](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual)），一个由 [Jina AI](https://jina.ai) 提供的 SQL 感知排序模型，会根据查询的相关性对表定义进行排序。
* 我们将用户的查询和排名前三的表定义作为提示，传递给 [Mistral 7B Instruct v0.1 \(`mistralai/Mistral-7B-Instruct-v0.1`)](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.1)，并请求生成一个 SQL 查询来完成任务。
* Mistral Instruct 生成一个 SQL 查询，我们将其在数据库上执行并检索结果。
* SQL 查询结果被转换为 JSON 格式，并作为新提示传递给 Mistral Instruct，包含用户的原始查询、SQL 查询及请求，要求生成自然语言形式的答案。
* Mistral Instruct 的自然语言文本响应返回给用户。

### 数据库

本教程使用一个小型的开放访问视频游戏销售记录数据库，存储在 [GitHub](https://github.com/bbrumm/databasestar/tree/main/sample_databases/sample_db_videogames/sqlite) 上。我们将使用 [SQLite](https://www.sqlite.org/index.html) 版本，因为 SQLite 非常紧凑，跨平台，并且内置对 Python 的支持。

### 软件和硬件要求

我们将在本地运行 Jina Reranker v2 模型。如果您使用 Google Colab 运行此笔记本，请确保使用支持 GPU 的运行时。如果您在本地运行，您需要 Python 3（本教程使用 Python 3.11 编写），并且在启用了 CUDA 的 GPU 上运行将会 *大大* 提升速度。

本教程还将广泛使用开源的 [LlamaIndex RAG 框架](https://www.llamaindex.ai/)，以及 [Hugging Face Inference API](https://huggingface.co/inference-api/serverless) 来访问 Mistral 7B Instruct v0.1。您需要一个 [Hugging Face 账户](https://huggingface.co/login) 和一个至少具有 `READ` 权限的 [访问令牌](https://huggingface.co/settings/tokens)。

> [!WARNING]
> 如果你使用 Google Colab，SQLite 已经安装。它可能没有安装在您的本地计算机上。如果未安装，请按照 [SQLite 网站](https://www.sqlite.org/download.html) 上的说明进行安装。Python 接口代码已经集成在 Python 中，无需额外安装任何 Python 模块。

## 开始

### 安装环境

首先，安装需要的 python 模块：

```python
!pip install -qU transformers einops llama-index llama-index-postprocessor-jinaai-rerank  llama-index-llms-huggingface "huggingface_hub[inference]"
```

### 下载数据库

接下来，从 [GitHub](https://github.com/bbrumm/databasestar/tree/main/sample_databases/sample_db_videogames/sqlite) 下载 SQLite 数据库 `videogames.db` 到本地文件系统。如果你的系统上没有 `wget` 命令，可以通过 [这个链接](https://github.com/bbrumm/databasestar/raw/main/sample_databases/sample_db_videogames/sqlite/videogames.db) 下载数据库，并将其放置在你运行本 Notebook 的相同目录中。

```python
!wget https://github.com/bbrumm/databasestar/raw/main/sample_databases/sample_db_videogames/sqlite/videogames.db
```

### 下载并运行 Jina Reranker v2

以下代码将下载模型 `jina-reranker-v2-base-multilingual` 并在本地运行： 

```python
from transformers import AutoModelForSequenceClassification

reranker_model = AutoModelForSequenceClassification.from_pretrained(
    'jinaai/jina-reranker-v2-base-multilingual',
    torch_dtype="auto",
    trust_remote_code=True,
)

reranker_model.to('cuda') # or 'cpu' if no GPU is available
reranker_model.eval()
```

### 设置 Mistral Instruct 的接口

我们将使用 LlamaIndex 创建一个持有对象，用于连接 Hugging Face 推理 API 和运行在那里的 `mistralai/Mistral-7B-Instruct-v0.1` 模型。

首先，从你的 [Hugging Face 账户设置页面](https://huggingface.co/settings/tokens) 获取一个 Hugging Face 访问令牌。

在下面的提示中输入该令牌：

```python
import getpass

print("Paste your Hugging Face access token here: ")
hf_token = getpass.getpass()
```

接下来，初始化 LlamaIndex 中 `HuggingFaceInferenceAPI` 类的实例，并将其存储为 `mistral_llm`：

```python
from llama_index.llms.huggingface import HuggingFaceInferenceAPI

mistral_llm = HuggingFaceInferenceAPI(
    model_name="mistralai/Mixtral-8x7B-Instruct-v0.1", token=hf_token
)
```

## 使用 SQL 感知的 Jina Reranker v2

我们从 [GitHub 上的数据库导入文件](https://github.com/bbrumm/databasestar/tree/main/sample_databases/sample_db_videogames/sqlite) 中提取了八个表的定义。运行以下命令，将它们放入名为 `table_declarations` 的 Python 列表中：

```python
table_declarations = ['CREATE TABLE platform (\n\tid INTEGER PRIMARY KEY,\n\tplatform_name TEXT DEFAULT NULL\n);',
 'CREATE TABLE genre (\n\tid INTEGER PRIMARY KEY,\n\tgenre_name TEXT DEFAULT NULL\n);',
 'CREATE TABLE publisher (\n\tid INTEGER PRIMARY KEY,\n\tpublisher_name TEXT DEFAULT NULL\n);',
 'CREATE TABLE region (\n\tid INTEGER PRIMARY KEY,\n\tregion_name TEXT DEFAULT NULL\n);',
 'CREATE TABLE game (\n\tid INTEGER PRIMARY KEY,\n\tgenre_id INTEGER,\n\tgame_name TEXT DEFAULT NULL,\n\tCONSTRAINT fk_gm_gen FOREIGN KEY (genre_id) REFERENCES genre(id)\n);',
 'CREATE TABLE game_publisher (\n\tid INTEGER PRIMARY KEY,\n\tgame_id INTEGER DEFAULT NULL,\n\tpublisher_id INTEGER DEFAULT NULL,\n\tCONSTRAINT fk_gpu_gam FOREIGN KEY (game_id) REFERENCES game(id),\n\tCONSTRAINT fk_gpu_pub FOREIGN KEY (publisher_id) REFERENCES publisher(id)\n);',
 'CREATE TABLE game_platform (\n\tid INTEGER PRIMARY KEY,\n\tgame_publisher_id INTEGER DEFAULT NULL,\n\tplatform_id INTEGER DEFAULT NULL,\n\trelease_year INTEGER DEFAULT NULL,\n\tCONSTRAINT fk_gpl_gp FOREIGN KEY (game_publisher_id) REFERENCES game_publisher(id),\n\tCONSTRAINT fk_gpl_pla FOREIGN KEY (platform_id) REFERENCES platform(id)\n);',
 'CREATE TABLE region_sales (\n\tregion_id INTEGER DEFAULT NULL,\n\tgame_platform_id INTEGER DEFAULT NULL,\n\tnum_sales REAL,\n   CONSTRAINT fk_rs_gp FOREIGN KEY (game_platform_id) REFERENCES game_platform(id),\n\tCONSTRAINT fk_rs_reg FOREIGN KEY (region_id) REFERENCES region(id)\n);']
```

现在，我们定义一个函数，该函数接受一个自然语言查询和表定义列表，使用 Jina Reranker v2 对所有表进行评分，并按得分从高到低返回它们：

```python
from typing import List, Tuple

def rank_tables(query: str, table_specs: List[str], top_n:int=0) -> List[Tuple[float, str]]:
  """
  Get sorted pairs of scores and table specifications, then return the top N,
  or all if top_n is 0 or default.
  """
  pairs = [[query, table_spec] for table_spec in table_specs]
  scores = reranker_model.compute_score(pairs)
  scored_tables = [(score, table_spec) for score, table_spec in zip(scores, table_specs)]
  scored_tables.sort(key=lambda x: x[0], reverse=True)
  if top_n and top_n < len(scored_tables):
    return scored_tables[0:top_n]
  return scored_tables
```

Jina Reranker v2 会对我们提供的每个表定义进行评分，默认情况下，这个函数将返回所有表及其得分。可选参数 `top_n` 限制返回的结果数量，按得分从高到低，直到用户定义的数量。

试试这个。首先，定义一个查询：

```python
user_query = "Identify the top 10 platforms by total sales."
```

运行 `rank_tables` 来获取表定义的列表。我们将 `top_n` 设置为 3，以限制返回列表的大小，并将结果赋值给变量 `ranked_tables`，然后检查结果：

```python
ranked_tables = rank_tables(user_query, table_declarations, top_n=3)
ranked_tables
```

输出应该包括 `region_sales`、`platform` 和 `game_platform` 这三个表，它们似乎都是查找查询答案的合理地方。

## 使用 Mistral Instruct 生成 SQL 查询

我们将使用 Mistral Instruct v0.1 编写一个 SQL 查询，满足用户的查询需求，基于根据重新排序器得出的前三个表的声明。

首先，我们使用 LlamaIndex 的 `PromptTemplate` 类为此目的创建一个提示：

```python
from llama_index.core import PromptTemplate

make_sql_prompt_tmpl_text = (
    """
Generate a SQL query to answer the following question from the user:
\"{query_str}\"

The SQL query should use only tables with the following SQL definitions:

Table 1:
{table_1}

Table 2:
{table_2}

Table 3:
{table_3}

Make sure you ONLY output an SQL query and no explanation.
"""
)
make_sql_prompt_tmpl = PromptTemplate(make_sql_prompt_tmpl_text)
```

我们使用 `format` 方法将用户查询和来自 Jina Reranker v2 的前三个表定义填充到模板字段中：

```python
make_sql_prompt = make_sql_prompt_tmpl.format(query_str=user_query,
                                              table_1=ranked_tables[0][1],
                                              table_2=ranked_tables[1][1],
                                              table_3=ranked_tables[2][1])
```

你可以看到我们将传递给 Mistral Instruct 的实际文本：

```python
print(make_sql_prompt)
```

现在，让我们将提示发送给 Mistral Instruct 并获取其响应：

```python
response = mistral_llm.complete(make_sql_prompt)
sql_query = str(response)
print(sql_query)
```

## 运行 SQL 查询
使用内置的 Python SQLite 接口，针对数据库 `videogames.db` 运行上面的 SQL 查询：

```python
import sqlite3

con = sqlite3.connect("videogames.db")
cur = con.cursor()
sql_response = cur.execute(sql_query).fetchall()
```

有关 SQLite 接口的详细信息，请参阅 [Python3 文档](https://docs.python.org/3/library/sqlite3.html)。

检查结果：

```python
sql_response
```

你可以通过运行您自己的 SQL 查询来检查结果是否正确。该数据库中存储的销售数据是浮动点数，可能是以千或百万为单位的销售数量。

## 获取自然语言回答

现在，我们将用户的查询、SQL 查询和结果通过一个新的提示模板传递回 Mistral Instruct。

首先，使用 LlamaIndex 创建新的提示模板，和之前一样：

```python
rag_prompt_tmpl_str = (
    """
Use the information in the JSON table to answer the following user query.
Do not explain anything, just answer concisely. Use natural language in your
answer, not computer formatting.

USER QUERY: {query_str}

JSON table:
{json_table}

This table was generated by the following SQL query:
{sql_query}

Answer ONLY using the information in the table and the SQL query, and if the
table does not provide the information to answer the question, answer
"No Information".
"""
)
rag_prompt_tmpl = PromptTemplate(rag_prompt_tmpl_str)
```

我们将把 SQL 输出转换为 JSON 格式，这是 Mistral Instruct v0.1 理解的格式。

填充模板字段：

```python
import json

rag_prompt = rag_prompt_tmpl.format(query_str="Identify the top 10 platforms by total sales",
                                    json_table=json.dumps(sql_response),
                                    sql_query=sql_query)
```

现在从 Mistral Instruct 请求自然语言回答：

```python
rag_response = mistral_llm.complete(rag_prompt)
print(str(rag_response))
```

## 尝试自己动手

让我们将所有步骤组织成一个函数，并加入异常处理：

```python
def answer_sql(user_query: str) -> str:
  try:
    ranked_tables = rank_tables(user_query, table_declarations, top_n=3)
  except Exception as e:
    print(f"Ranking failed.\nUser query:\n{user_query}\n\n")
    raise(e)

  make_sql_prompt = make_sql_prompt_tmpl.format(query_str=user_query,
                                                table_1=ranked_tables[0][1],
                                                table_2=ranked_tables[1][1],
                                                table_3=ranked_tables[2][1])

  try:
    response = mistral_llm.complete(make_sql_prompt)
  except Exception as e:
    print(f"SQL query generation failed\nPrompt:\n{make_sql_prompt}\n\n")
    raise(e)

  # Backslash removal is a necessary hack because sometimes Mistral puts them
  # in its generated code.
  sql_query = str(response).replace("\\", "")

  try:
    sql_response = sqlite3.connect("videogames.db").cursor().execute(sql_query).fetchall()
  except Exception as e:
    print(f"SQL querying failed. Query:\n{sql_query}\n\n")
    raise(e)

  rag_prompt = rag_prompt_tmpl.format(query_str=user_query,
                                      json_table=json.dumps(sql_response),
                                      sql_query=sql_query)
  try:
    rag_response = mistral_llm.complete(rag_prompt)
    return str(rag_response)
  except Exception as e:
    print(f"Answer generation failed. Prompt:\n{rag_prompt}\n\n")
    raise(e)
```

尝试:

```python
print(answer_sql("Identify the top 10 platforms by total sales."))
```

试一试其他的问题:

```python
print(answer_sql("Summarize sales by region."))
```

```python
print(answer_sql("List the publisher with the largest number of published games."))
```

```python
print(answer_sql("Display the year with most games released."))
```

```python
print(answer_sql("What is the most popular game genre on the Wii platform?"))
```

```python
print(answer_sql("What is the most popular game genre of 2012?"))
```

试一试你自己的问题:

```python
print(answer_sql("<INSERT QUESTION OR INSTRUCTION HERE>"))
```

## 复习与总结

我们向你展示了如何构建一个非常基础的 RAG（检索增强生成）系统，用于自然语言问答，并将 SQL 数据库作为信息来源。在这个实现中，我们使用相同的大型语言模型（Mistral Instruct v0.1）来生成 SQL 查询和构造自然语言回答。

这里的数据库是一个非常小的示例，扩展到更大规模可能需要比仅仅对表定义进行排序更复杂的方法。你可能需要使用一个双阶段的过程，其中嵌入模型和向量存储首先检索更多的结果，但重排序模型会将结果修剪到你能够放入生成语言模型提示中的数量。

本 Notebook 假设没有任何请求需要超过三个表来满足，显然，在实际应用中，这种假设并不总是成立。Mistral 7B Instruct v0.1 并不保证生成正确（甚至是可执行的）SQL 输出。在生产环境中，类似的实现需要更深入的错误处理。

更复杂的错误处理、更长的输入上下文窗口以及专门用于 SQL 任务的生成模型，可能在实际应用中带来显著的改进。

尽管如此，你可以看到 RAG 概念如何扩展到结构化数据库，极大地扩展了其应用范围。