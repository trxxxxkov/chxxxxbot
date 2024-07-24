# [Telegram bot called Sebastian](https://t.me/chxxxxbot), a chatbot whose main priority is user convenience.

## Table of Contents
1. [Overview](#overview)
2. [Motivation](#motivation)
3. [Features](#features)
4. [Project Structure](#project-structure)
5. [Installation](#installation)
6. [Contributions](#contributions)
7. [FAQ](#faq)

## Overview
Messengers, especially Telegram, offer an exceptionally convenient platform for interacting with generative AI models. They are accessible on all devices and are designed for dialogues and the rapid exchange and forwarding of text and graphic information with minimal requirements for internet connection speed.

**Sebastian** is a Telegram bot written using the **aiogram** asynchronous framework. It provides access to the most advanced modern AI models  (currently only **GPT-4** and **DALLE**), designed for seamless interaction with them through the Telegram. 

## Motivation
#### The main goal of this project is to create the most 'human-like' chatbot possible. The name **Sebastian**, which is a traditional butler name in anime, represents the aspiration to make the project not just a chatbot but a full-fledged assistant capable of handling a wide range of tasks.
Thus, most of the tasks are divided into two categories:
- Providing support for new types of input data such as various files, audio requests and video requests;
- Processing all possible use cases of the existing functionality and extending its capabilities through manual handling of edge cases and exceptional situations.

The latter category essentially involves working on numerous, often unnoticed details that, nevertheless, constitute an important part of the user experience.

## Features
##### You can [try out Sebastian's features right now](https://t.me/chxxxxbot) - new users receive a welcome gift of 1000 tokens.
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
```bash
chxxxxbot/  # The main project's directory
├── secrets/                # Directory for build secrets. 
│   ├── bot_token.txt       # Telegram Bot Token (provided by @BotFather)
│   ├── db_password.txt     # Database password  (arbitrary)
│   ├── openai_token.txt    # OpenAI API token   (provided by OpenAI)
│   └── webhook_secret.txt  # Webhook secret     (arbitrary
├── src/         # Directory for bot source code
│   ├── main.py  # Bot entrypoint
│   ├── core/                    # Directory for core chatbot functionality 
│   │   ├── chat_completion.py   # Text processing
│   │   └── image_generation.py  # Image processing
│   ├── database/       # Directory for database-related python code
│   │   └── queries.py  # Wrapper functions over psycopg calls
│   ├── handlers/               # Directory for Telegram API updates handlers
│   │   ├── callbacks.py        # Inline keyboards events
│   │   ├── hidden_cmds.py      # Commands that aren't visible in Telegram interface
│   │   ├── other_upds.py       # Payment updates 
│   │   ├── privileged_cmds.py  # Commands that are available only for bot owner
│   │   └── public_cmds.py      # Commands that are shown in Telegram interface
│   ├── templates/       # Directory for documentation and keyboards templates
│   │   ├── bot_menu.py  # Dict structure that store Telegram Bot Menu commands
│   │   ├── scripted_dialogues.py   # Dict structure for all docs and buttons texts
│   │   ├── keyboards/         # Directory for keyboards templates 
│   │   │   ├── inline_kbd.py  # Templates and a factory for inline keyboards
│   │   │   └── reply_kbd.py   # Templates for reply keyboards
│   │   └── tutorial/            # Directory for tutorial's media
│   │       ├── generation.mp4   # Video for image generation functionality
│   │       ├── latex.mp4        # Video for latex detection and compilation functionality
│   │       ├── prompt.mp4       # Video for chat completion functionality
│   │       ├── recognition.mp4  # Video for image recognition functionality
│   │       ├── tokens.mp4       # Video about describing what are tokens
│   │       └── videos.py        # Dict structure for tutorial videos file_ids
│   └── utils/              # Directory for auxiliary functions and temprorary data
│       ├── formatting.py   # Functions for text parsing and formatting
│       ├── globals.py      # Storage for bot object, openai client and global constants
│       ├── validations.py  # Functions for input validations
│       ├── analytics/        # Directory for administration tools and logging
│       │   ├── analytics.py  # Analytics auxiliary function
│       │   └── logging.py    # Logging wrapper
│       └── temp/           # Directory for data sent to users or obtained from them
│           ├── documents/  # Directory for all temporary files that are not images
│           └── images/     # Directory for images that are obtained from user
├── .dockerignore        # Ignore files that should not be in Bot's docker container
├── .gitignore           # Ignore secret and temporary files
├── .env                 # Storage for all environment variables
├── compose.yaml         # Docker compose file
├── Dockerfile           # Bot container's Dockerfile
├── nginx.conf.template  # NGINX reverse proxy servers configuration
├── pgdb_scheme.sql      # File for PostgreSQL database initialization
├── pyproject.toml       # Configuration file for bot's source code build system
├── LICENSE              # Project's license
└── README.md            # The file you are currently looking at 
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
 - Write your Telegram Bot token (obtained from [@BotFather](https://t.me/botfather)) to `chxxxxbot/secrets/bot_token.txt`;
 - Write your OpenAI API token (obtained from OpenAI) to `chxxxxbot/secrets/openai_token.txt`;
 - Write your database password (arbitrary) to `chxxxxbot/secrets/db_password.txt`;
 - Write your [webhook secret](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks#use-a-webhook-secret) (arbitrary) to `chxxxxbot/secrets/webhook_secret.txt`;
#### 6. Deploy the project by entering the following command in your console:
```bash
docker compose up
```

## Contributions

The project needs help not only with improvements and additions to the codebase but also with ideas! The main goal of the project can only be achieved by working through numerous details that are hard to foresee in advance, but when encountered, make you think, "Oh! This is so natural and convenient!"
##### So, if you have any suggestions that you would like to see implemented in this project, please feel free to either write in the [Issues section](https://github.com/trxxxxkov/chxxxxbot/issues) or contact the project author through [Telegram](https://t.me/trxxxxkov) or [email](mailto:trxxxxkov@gmail.com).

## FAQ

###### [This section will be added later]
