# [Telegram bot called Sebastian](https://t.me/chxxxxbot), a chatbot whose main priority is user convenience.

## Overview
Messengers, especially Telegram, offer an exceptionally convenient platform for interacting with generative AI models. They are accessible on all devices and are designed for dialogues and the rapid exchange and forwarding of text and graphic information with minimal requirements for internet connection speed.

**Sebastian** is a Telegram bot providing access to the most advanced modern AI models  (currently only **GPT-4** and **DALLE**), designed for seamless interaction with them through the Telegram. 

## Project Goals
The name **Sebastian**, which is a traditional butler name in anime, represents the aspiration to make the project not just a chatbot but a full-fledged assistant capable of handling a wide range of tasks.
The main goal of this project is to create the most 'human-like' chatbot possible by actively utilizing the advantages of messenger platform.

Thus, most of the tasks are divided into two categories:
- Implementing support for new types of input data such as various files, audio requests and video requests;
- Processing all possible use cases of the existing functionality and extending its capabilities through manual handling of edge cases and exceptional situations.

The latter category essentially involves working on numerous, often unnoticed details that, nevertheless, constitute an important part of the user experience.

## Features


## Installation
[Provide step-by-step instructions on how to install and set up your project.]

## Project Structure
```
chxxxxbot/
├── secrets/
│   ├── bot_token.txt
│   ├── db_password.txt
│   ├── openai_token.txt
│   └── webhook_secret.txt
├── src/
│   ├── main.py
│   ├── core/
│   │   ├── chat_completion.py
│   │   └── image_generation.py
│   ├── database/
│   │   └── queries.py
│   ├── handlers/
│   │   ├── callbacks.py
│   │   ├── hidden_cmds.py
│   │   ├── other_upds.py
│   │   ├── privileged_cmds.py
│   │   └── public_cmds.py
│   ├── templates/
│   │   ├── bot_menu.py
│   │   ├── scripts.py
│   │   ├── keyboards/
│   │   │   ├── inline_kbd.py
│   │   │   └── reply_kbd.py
│   │   └── tutorial/
│   │       ├── generation.mp4
│   │       ├── latex.mp4
│   │       ├── prompt.mp4
│   │       ├── recognition.mp4
│   │       ├── tokens.mp4
│   │       └── videos.py
│   └── utils/
│       ├── formatting.py
│       ├── globals.py
│       ├── validations.py
│       ├── analytics/
│       │   ├── analytics.py
│       │   └── logging.py
│       └── temp/
│           ├── documents/
│           └── images/
├── .dockerignore
├── .gitignore
├── .gitattributes
├── .env
├── compose.yaml
├── Dockerfile
├── nginx.conf.template
├── pgdb_scheme.sql
├── pyproject.toml
├── LICENSE
└── README.md
```
