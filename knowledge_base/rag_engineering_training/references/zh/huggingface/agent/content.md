# 智能体 RAG：通过查询重构和自查询来增强你的 RAG ！🚀

_作者: [Aymeric Roucher](https://huggingface.co/m-ric)_

>这个教程比较高级，建议你先看看另一个[更基础的教程](https://github.com/huggingface/cookbook/blob/b23df069425fe24cd9a38f8a86c5cb9e163917a0/notebooks/zh-CN/advanced_rag)。

>检索增强生成（RAG）是一种用大型语言模型（LLM）来回答问题的方法，但它会先从知识库中查找相关信息。这种方法比只用大型语言模型有很多好处，比如可以基于真实的事实来回答问题，减少虚构内容，还可以让模型获取特定领域的知识，并且可以精确控制模型从知识库中获取信息。

不过，普通的RAG方法有两个主要问题：

- 它只进行**一次信息检索**，如果检索的结果不好，那么回答也会差。
- 它计算**语义相似性时是以用户的提问为参照**，这可能不太理想。比如，用户提出的问题通常是用疑问句，而包含答案的文档通常是陈述句，这样就会导致真正含有答案的文档和用户提问的相似性得分不高，可能会错过重要的信息。

为了解决这些问题，我们可以创建**一个带有检索功能的 RAG 智能体。**

这个智能体可以 ✅ 自己构建查询，并且 ✅ 在需要的时候重新检索信息。

所以，我们得用点高级的 RAG 技术！

- 不直接使用用户的提问去搜索，而是智能体自行制定一个更接近目标文档的参考句子，就像 [HyDE](https://huggingface.co/papers/2212.10496) 那样
- 智能体能生成片段并在需要时重新检索，就像 [Self-Query](https://docs.llamaindex.ai/en/stable/examples/evaluation/RetryQuery/) 那样

让我们开始做这个系统吧。🛠️

运行下面的命令来安装所需的软件包：

```python
!pip install pandas langchain langchain-community sentence-transformers faiss-cpu smolagents
```

我们首先加载一个知识库，以便在其上执行 RAG：这个数据集是许多 `huggingface` 软件包的文档页面的汇总，以 markdown 格式存储。

```python
import datasets

knowledge_base = datasets.load_dataset("m-ric/huggingface_doc", split="train")
```

现在我们通过处理数据集并将其存储到向量数据库中，为检索器准备知识库。我们使用 [LangChain](https://python.langchain.com/)，因为它具有出色的向量数据库工具。对于嵌入模型，我们使用 [thenlper/gte-small](https://huggingface.co/thenlper/gte-small)，因为它在我们的 `RAG_evaluation` 指南中表现良好。

```python
from transformers import AutoTokenizer
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores.utils import DistanceStrategy
from tqdm import tqdm

source_docs = [
    Document(page_content=doc["text"], metadata={"source": doc["source"].split("/")[1]})
    for doc in knowledge_base
]

text_splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
    AutoTokenizer.from_pretrained("thenlper/gte-small"),
    chunk_size=200,
    chunk_overlap=20,
    add_start_index=True,
    strip_whitespace=True,
    separators=["\n\n", "\n", ".", " ", ""],
)

# Split docs and keep only unique ones
print("Splitting documents...")
docs_processed = []
unique_texts = {}
for doc in tqdm(source_docs):
    new_docs = text_splitter.split_documents([doc])
    for new_doc in new_docs:
        if new_doc.page_content not in unique_texts:
            unique_texts[doc.page_content] = True
            docs_processed.append(new_doc)

print(
    "Embedding documents... This should take a few minutes (5 minutes on MacBook with M1 Pro)"
)
embedding_model = HuggingFaceEmbeddings(model_name="thenlper/gte-small")
vectordb = FAISS.from_documents(
    documents=docs_processed,
    embedding=embedding_model,
    distance_strategy=DistanceStrategy.COSINE,
)
```

现在数据库已经准备好了：让我们构建我们的智能体 RAG 系统吧！

👉 我们只需要一个 `RetrieverTool`，我们的智能体可以利用它从知识库中检索信息。

```python
from smolagents import Tool
from langchain_core.vectorstores import VectorStore


class RetrieverTool(Tool):
    name = "retriever"
    description = "Using semantic similarity, retrieves some documents from the knowledge base that have the closest embeddings to the input query."
    inputs = {
        "query": {
            "type": "text",
            "description": "The query to perform. This should be semantically close to your target documents. Use the affirmative form rather than a question.",
        }
    }
    output_type = "text"

    def __init__(self, vectordb: VectorStore, **kwargs):
        super().__init__(**kwargs)
        self.vectordb = vectordb

    def forward(self, query: str) -> str:
        assert isinstance(query, str), "Your search query must be a string"

        docs = self.vectordb.similarity_search(
            query,
            k=7,
        )

        return "\nRetrieved documents:\n" + "".join(
            [
                f"===== Document {str(i)} =====\n" + doc.page_content
                for i, doc in enumerate(docs)
            ]
        )
```

现在创建一个利用这个工具的智能体就简单了！

智能体在初始化时需要以下参数：
- *`tools`*：智能体能够调用的工具列表。
- *`llm_engine`*：为智能体提供动力的LLM。

我们的 `llm_engine` 必须是一个可调用的对象，它接受一个 [messages](https://huggingface.co/docs/transformers/main/chat_templating) 列表作为输入并返回文本。它还需要接受一个 `stop_sequences` 参数，该参数指示何时停止生成。为了方便起见，我们直接使用包中提供的 `HfModel` 类来获取一个调用我们的 [Inference API](https://huggingface.co/docs/api-inference/en/index) 的 LLM 引擎。
我们使用 [CohereForAI/c4ai-command-r-plus](https://huggingface.co/CohereForAI/c4ai-command-r-plus) 作为 llm 引擎，因为：
- 它有一个长达 128k 的上下文，这对于处理长源文档很有帮助
- 它在 HF 的 Inference API 上始终免费提供！

```python
from smolagents import HfModel, ToolCallingAgent

model = HfModel("CohereForAI/c4ai-command-r-plus")

retriever_tool = RetrieverTool(vectordb)
agent = ToolCallingAgent(
    tools=[retriever_tool], model=model, max_iterations=4, verbose=2
)
```

既然我们已经将智能体初始化为 `ToolCallingAgent`，它就已经自动赋予了一个默认的系统提示，告诉 LLM 引擎要逐步处理并生成工具调用作为 JSON 块（你可以根据需要用你自己的提示模板替换这个）。

然后，当它的 `.run()` 方法被启动时，智能体负责调用 LLM 引擎，解析工具调用的 JSON 块并执行这些工具调用，所有这些都在一个循环中进行，只有当提供最终答案时才会结束。

```python
agent_output = agent.run("How can I push a model to the Hub?")

print("Final output:")
print(agent_output)
```

## 智能体RAG与标准RAG的比较

智能体 RAG 和标准 RAG，哪个更好？我们用 LLM Judge 来比一比。

我们会用一个非常强的模型 [meta-llama/Meta-Llama-3-70B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-70B-Instruct) 来做这个评估。

```python
eval_dataset = datasets.load_dataset("m-ric/huggingface_doc_qa_eval", split="train")
```

在运行测试之前，让我们让智能体输出更简洁一些。

```python
import logging

agent.logger.setLevel(logging.WARNING)
```

```python
outputs_agentic_rag = []

for example in tqdm(eval_dataset):
    question = example["question"]

    enhanced_question = f"""Using the information contained in your knowledge base, which you can access with the 'retriever' tool,
give a comprehensive answer to the question below.
Respond only to the question asked, response should be concise and relevant to the question.
If you cannot find information, do not give up and try calling your retriever again with different arguments!
Make sure to have covered the question completely by calling the retriever tool several times with semantically different queries.
Your queries should not be questions but affirmative form sentences: e.g. rather than "How do I load a model from the Hub in bf16?", query should be "load a model from the Hub bf16 weights".

Question:
{question}"""
    answer = agent.run(enhanced_question)
    print("=======================================================")
    print(f"Question: {question}")
    print(f"Answer: {answer}")
    print(f'True answer: {example["answer"]}')

    results_agentic = {
        "question": question,
        "true_answer": example["answer"],
        "source_doc": example["source_doc"],
        "generated_answer": answer,
    }
    outputs_agentic_rag.append(results_agentic)
```

```python
from huggingface_hub import InferenceClient

reader_llm = InferenceClient("CohereForAI/c4ai-command-r-plus")

outputs_standard_rag = []

for example in tqdm(eval_dataset):
    question = example["question"]
    context = retriever_tool(question)

    prompt = f"""Given the question and supporting documents below, give a comprehensive answer to the question.
Respond only to the question asked, response should be concise and relevant to the question.
Provide the number of the source document when relevant.
If you cannot find information, do not give up and try calling your retriever again with different arguments!

Question:
{question}

{context}
"""
    messages = [{"role": "user", "content": prompt}]
    answer = reader_llm.chat_completion(messages).choices[0].message.content

    print("=======================================================")
    print(f"Question: {question}")
    print(f"Answer: {answer}")
    print(f'True answer: {example["answer"]}')

    results_agentic = {
        "question": question,
        "true_answer": example["answer"],
        "source_doc": example["source_doc"],
        "generated_answer": answer,
    }
    outputs_standard_rag.append(results_agentic)
```

评估提示遵循了[我们的 llm_judge cookbook](https://github.com/huggingface/cookbook/blob/b23df069425fe24cd9a38f8a86c5cb9e163917a0/notebooks/zh-CN/llm_judge) 中展示的一些最佳原则：它遵循一个小的整数李克特量表，有明确的评分标准和每个分数的描述。

```python
EVALUATION_PROMPT = """You are a fair evaluator language model.

You will be given an instruction, a response to evaluate, a reference answer that gets a score of 3, and a score rubric representing a evaluation criteria are given.
1. Write a detailed feedback that assess the quality of the response strictly based on the given score rubric, not evaluating in general.
2. After writing a feedback, write a score that is an integer between 1 and 3. You should refer to the score rubric.
3. The output format should look as follows: \"Feedback: {{write a feedback for criteria}} [RESULT] {{an integer number between 1 and 3}}\"
4. Please do not generate any other opening, closing, and explanations. Be sure to include [RESULT] in your output.
5. Do not score conciseness: a correct answer that covers the question should receive max score, even if it contains additional useless information.

The instruction to evaluate:
{instruction}

Response to evaluate:
{response}

Reference Answer (Score 3):
{reference_answer}

Score Rubrics:
[Is the response complete, accurate, and factual based on the reference answer?]
Score 1: The response is completely incomplete, inaccurate, and/or not factual.
Score 2: The response is somewhat complete, accurate, and/or factual.
Score 3: The response is completely complete, accurate, and/or factual.

Feedback:"""
```

```python
from huggingface_hub import InferenceClient

evaluation_client = InferenceClient("meta-llama/Meta-Llama-3-70B-Instruct")
```

```python
import pandas as pd

for type, outputs in [
    ("agentic", outputs_agentic_rag),
    ("standard", outputs_standard_rag),
]:
    for experiment in tqdm(outputs):
        eval_prompt = EVALUATION_PROMPT.format(
            instruction=experiment["question"],
            response=experiment["generated_answer"],
            reference_answer=experiment["true_answer"],
        )
        messages = [
            {"role": "system", "content": "You are a fair evaluator language model."},
            {"role": "user", "content": eval_prompt},
        ]

        eval_result = evaluation_client.text_generation(
            eval_prompt, max_new_tokens=1000
        )
        try:
            feedback, score = [item.strip() for item in eval_result.split("[RESULT]")]
            experiment["eval_score_LLM_judge"] = score
            experiment["eval_feedback_LLM_judge"] = feedback
        except:
            print(f"Parsing failed - output was: {eval_result}")

    results = pd.DataFrame.from_dict(outputs)
    results = results.loc[~results["generated_answer"].str.contains("Error")]
    results["eval_score_LLM_judge_int"] = (
        results["eval_score_LLM_judge"].fillna(1).apply(lambda x: int(x))
    )
    results["eval_score_LLM_judge_int"] = (results["eval_score_LLM_judge_int"] - 1) / 2

    print(
        f"Average score for {type} RAG: {results['eval_score_LLM_judge_int'].mean()*100:.1f}%"
    )
```

**让我们回顾一下：与标准的 RAG 相比，智能体设置提高了 8.5% 的得分！**（从 70.0% 提高到 78.5%）

这是一个巨大的改进，而且设置非常简单🚀

（作为基准，不使用知识库的 Llama-3-70B 得分为 36%）
