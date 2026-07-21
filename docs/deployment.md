# 部署说明

## 环境要求

- Python 3.11 或 3.12
- Node.js 18+
- 国产大模型 API Key（通义千问 / 文心一言 / DeepSeek / 智谱等）

## 后端部署

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 复制环境变量模板并填写
# macOS/Linux
cp .env.example .env
# Windows PowerShell
Copy-Item .env.example .env
# 两种命令都在 backend/ 目录执行，生成 backend/.env
# 编辑 .env 填入 LLM_API_KEY 与 LLM_BASE_URL

# 数据库配置（可选）
# DB_TYPE=memory        # 默认，服务重启数据丢失，适合开发演示
# DB_TYPE=sqlite        # 使用 SQLite，数据持久化到 backend/data/domain_knowledge.db
# DB_TYPE=postgresql    # 使用 PostgreSQL，需配置 DATABASE_URL

cd ..
# 在项目根目录执行，脚本会自动定位 backend/、examples/ 与 knowledge_base/
python scripts/ingest_knowledge.py
python scripts/init_db.py

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 前端部署

```bash
cd frontend
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

## Docker 部署（可选）

```bash
# 构建镜像（构建上下文为项目根目录，包含 knowledge_base 与 examples）
docker build -t domain-knowledge-agent .

# 运行容器，传入环境变量
docker run -p 8000:8000 --env-file ./backend/.env domain-knowledge-agent
```

## 测试

```bash
cd backend
pytest tests/ -v
```
