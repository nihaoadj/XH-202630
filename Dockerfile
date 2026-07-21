FROM python:3.11-slim

WORKDIR /app

# 先复制并安装依赖，利用 Docker 缓存层
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码与项目资源
COPY backend ./backend
COPY knowledge_base ./knowledge_base
COPY examples ./examples
COPY scripts ./scripts
COPY backend/data ./backend/data
COPY backend/chroma_db ./backend/chroma_db

RUN mkdir -p /app/backend/data/generated_resources /app/backend/chroma_db /app/backend/logs

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
