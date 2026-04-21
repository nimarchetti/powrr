FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# To bundle a custom font, uncomment and update the path:
# COPY fonts/ /app/fonts/

COPY . .

CMD ["python", "main.py"]
