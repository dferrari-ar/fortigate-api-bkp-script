FROM python:3.11-slim

WORKDIR /app

COPY app/requirements.txt .
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

CMD ["python", "backup_manager.py"]
