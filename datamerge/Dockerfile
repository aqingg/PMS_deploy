FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./custom_python_docx /app/custom_python_docx
RUN pip install ./custom_python_docx

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
