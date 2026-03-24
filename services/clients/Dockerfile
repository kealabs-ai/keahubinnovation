FROM python:3.11-slim
WORKDIR /app
COPY clients/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY clients/ .
COPY database.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
