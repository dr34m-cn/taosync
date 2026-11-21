FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py trust.py trust_manifest.py index.html logo.ico ./
RUN mkdir -p /app/data

VOLUME ["/app/data"]
EXPOSE 8030
CMD ["python", "app.py"]
