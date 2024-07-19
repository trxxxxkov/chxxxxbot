# syntax=docker/dockerfile:1
FROM python:3-slim

WORKDIR /app
COPY . .
# Create directory for Telegram webhooks
RUN ["mkdir", "webhooks"]
# Install libs for svg2jpg images conversion feature of the bot.
RUN apt update \
  && apt install -y libcairo2-dev libpq-dev libaio1 \ 
  && apt clean
RUN pip install .

CMD ["python", "src/main.py"]