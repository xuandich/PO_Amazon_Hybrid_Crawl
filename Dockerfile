# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Cài đặt D-Bus để tránh lỗi bus.cc
RUN apt-get update && apt-get install -y \
    dbus \
    dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Tạo thư mục và cấp quyền
RUN mkdir -p /app/browser-profile /app/cookies && \
    chmod -R 777 /app/browser-profile /app/cookies

# Dùng user có sẵn
USER pwuser

CMD ["python", "main.py"]