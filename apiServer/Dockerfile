FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./

EXPOSE 8030
CMD ["python", "app.py", "--config", "/app/config.yaml"]
