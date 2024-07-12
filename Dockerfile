# syntax=docker/dockerfile:1
FROM python:3-slim

WORKDIR /app
COPY . .
RUN apt update \
  && apt install -y libcairo2-dev libpq-dev libaio1 \
  && apt clean
RUN pip install .

CMD ["python", "src/main.py"]