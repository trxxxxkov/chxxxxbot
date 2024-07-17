# [Telegram bot called Sebastian](https://t.me/chxxxxbot), a chatbot whose main priority is user convenience.

## Overview
Messengers, especially Telegram, offer an exceptionally convenient platform for interacting with generative AI models. They are accessible on all devices and are designed for dialogues and the rapid exchange and forwarding of text and graphic information with minimal requirements for internet connection speed.

**Sebastian** is a Telegram bot providing access to the most advanced modern AI models  (currently only **GPT-4** and **DALLE**), designed for seamless interaction with them through the Telegram. 

## Project Goals
#### The main goal of this project is to create the most 'human-like' chatbot possible. The name **Sebastian**, which is a traditional butler name in anime, represents the aspiration to make the project not just a chatbot but a full-fledged assistant capable of handling a wide range of tasks.
Thus, most of the tasks are divided into two categories:
- Providing support for new types of input data such as various files, audio requests and video requests;
- Processing all possible use cases of the existing functionality and extending its capabilities through manual handling of edge cases and exceptional situations.

The latter category essentially involves working on numerous, often unnoticed details that, nevertheless, constitute an important part of the user experience.

## Features
#### Chatbot features, such as:
- Processing text messages using GPT-4o;
- Recognizing images using GPT-4o;
- Generating images using DALLE-3 and their variations using DALLE-2;
#### Telegram Bot API features:
- Support for payments and refunds using Telegram Stars and all related commands;
- Telegram Webhooks;
- Error-prone MarkdownV2 text formatting that minimize the number of escapements in a response;
- The interface language (buttons, documentation) is determined individually for each user;
- Inline & Reply Keyboards;
#### Usability Enhancements:
- OpenAI streaming API usage for real-time response transmission by editing the message as chunks of the response are received;
- Storage of each user's message history, with both automatic and manual clearing options;
- Handling of long messages:
  + Splitting messages into chunks with a length of less than 4096 characters
  + Joining messages that were split into chunks due to Telegram's limitations."
  + User notification offering to send long messages as a txt file;
- Automatic LaTeX compilation;
- Over 18,000 characters in various system messages for user interaction;
- User tutorial including short video clips;
- Handling of quotations;
- Handling of messages with multiple images;
- Integration of DALLE-3 into the dialogue context of GPT-4o;
And much more.
#### Build features:
- **Docker** for containerization and **Docker Compose** for container orchestration;
- **PostgreSQL** database for user data storage;
- **NGINX** as a reverse proxy with automatic SSL certificate issuance;
- Proper handling of secrets used in environment setup;
- Use of pyproject.toml for storing build system configuration and dependency management;

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

## Installation
#### 1. [Install Git](https://git-scm.com/downloads);
#### 2. [Install Docker Desktop or Docker Engine](https://docs.docker.com/get-docker/);
#### 3. Clone this repository:
```bash
git clone https://github.com/trxxxxkov/chxxxxbot.git
```
#### 4. Specify the required environment variables in `chxxxxbot/.env` file, for example:
```.env
### BOT ENVIRONMENT VARIABLES
OWNER_TG_ID=000000000

### WEBSERVER ENVIRONMENT VARIABLES
CERTBOT_EMAIL=example@gmail.com
NGINX_HOST=example.com
```
#### 5. Add your tokens and passwords into the files in `chxxxxbot/secret/` folder:

Write your Telegram Bot token (can be obtained from [@BotFather](https://t.me/botfather)) to `chxxxxbot/secrets/bot_token.txt`:
```
0000000000:EXamplEeXAmPleExaMPLeeXaMplEeXamplE
```
Write your database password (the password can be anything, but it is not recommended to make it too simple) to `chxxxxbot/secrets/db_password.txt`:
```
myfavoriteexamplepassword123456789
```
Write your OpenAI API token to `chxxxxbot/secrets/openai_token.txt`:
```
eE-XamPlEExaMPLeEXAmplEexampleExampLEexaMPleeXAMPle
```
Write your [webhook secret](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks#use-a-webhook-secret) to `chxxxxbot/secrets/webhook_secret.txt`:
```
myfavoriteexamplewebhooksecret1234
```
#### 6. Deploy the project by entering the following command in the console:
```bash
docker compose up
```
##### Done. You have successfully deployed chxxxbot.

## FAQ

###### [This section will be added later]
