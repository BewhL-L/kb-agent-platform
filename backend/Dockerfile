# 与 CI（3.11）保持一致；本地 3.13 仅用于跑脚本，不要用来判断依赖是否装得上
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，Python 不生成 pyc、不缓冲输出
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 系统依赖：所有 Python 包均使用预编译 wheel，无需 build-essential
# 如需从源码编译包，再取消下面的注释（注意容器内 apt 网络可能不稳定）
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目代码
COPY . .

# 创建上传目录与运行期可写目录（data 目录同时供 BM25 索引 / Embedding 缓存 / 长期记忆使用）
RUN mkdir -p uploads chroma_db data

EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
