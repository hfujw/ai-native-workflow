# 时光像素 后端 Docker 镜像
# 基于 Playwright 官方镜像——已预装 Chromium 所需的所有系统依赖
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存——代码改了不用重新 pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 下载 Chromium 浏览器（系统依赖已内置，只需二进制）
RUN playwright install chromium

# 复制应用代码
COPY . .

# 非 root 运行（安全合规，面试加分细节）
# 注意：Playwright 基础镜像已占用 UID 1000，不能指定 -u 1000（会报 useradd exit 4）
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
