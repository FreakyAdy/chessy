FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure working directories exist
RUN mkdir -p uploaded_agents results games

EXPOSE 8000

CMD ["python", "web_server.py", "--host", "0.0.0.0", "--port", "8000"]
