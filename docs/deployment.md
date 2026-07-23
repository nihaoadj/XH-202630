# 部署说明

> **当前项目只是框架阶段，不支持完整业务运行或生产部署。**  


## 环境要求

- Python 3.11
- Node.js 18+
- 国产大模型 API Key（通义千问 / 文心一言 / DeepSeek / 智谱等）

## 后端部署

虚拟环境只在项目根目录 `.venv/` 本地创建，用于安装和隔离依赖；`.venv/` 不属于项目源码，已在 `.gitignore` 中排除，禁止提交到仓库。

创建或重建：

```powershell
cd D:\CODE\XH-202630\version1
conda create -p .\.venv python=3.11 pip -y
.\.venv\python.exe -m pip install -r backend\requirements.txt
```

复制环境变量模板：

```powershell
cd backend
Copy-Item .env.example .env
```

编辑 `backend/.env`，至少填写：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-max
DB_TYPE=memory
```

启动后端：

```powershell
cd D:\CODE\XH-202630\version1\backend
..\.venv\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：

```text
http://localhost:8000/
http://localhost:8000/docs
```

## 知识库与示例数据

```powershell
cd D:\CODE\XH-202630\version1
.\.venv\python.exe scripts\ingest_knowledge.py
.\.venv\python.exe scripts\init_db.py
```

注意：知识库入库会涉及 Embedding 和向量库，首次运行可能需要下载模型。

## 前端部署

```powershell
cd frontend
npm install
npm run dev
```

生产构建：

```powershell
npm run build
```

## Docker 部署（后续）

当前不建议作为正式部署方式。后续完整业务闭环完成后再验证：

```powershell
docker build -t domain-knowledge-agent .
docker run -p 8000:8000 --env-file ./backend/.env domain-knowledge-agent
```

## 测试

```powershell
cd D:\CODE\XH-202630\version1
.\.venv\python.exe -m compileall backend\app backend\tests
.\.venv\python.exe -m pytest backend\tests -q
.\.venv\python.exe -m pip check
```
