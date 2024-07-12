# syntax=docker/dockerfile:1
FROM python:3-slim

WORKDIR /app
COPY . .
RUN apt update && apt install -y libcairo2-dev
RUN pip install .

CMD ["python", "src/main.py"]