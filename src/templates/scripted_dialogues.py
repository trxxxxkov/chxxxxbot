"""Pre-written text dialogues that are used for interaction with users"""

dialogues = {
    "doc": {
        "start": {
            "en": "Pleased to meet you\\, {}\\! My name is *Sebastian*\\. I am an [open\\-source](https://github.com/trxxxxkov/chxxxxbot) bot powered by the most advanced *AI* models\\, which means you can explore my source code or participate in my development\\.\n\n *I ask you to review my capabilities\\. To do this\\, your balance has just been funded with __2000__ tokens\\. Now type /help to learn about the basic features and available commands\\!*",
            "ru": "Здравствуйте, {}\\! Меня зовут *Себастиан*\\. Я \\- [open\\-source](https://github.com/trxxxxkov/chxxxxbot) бот под управлением передовых моделей *AI*\\. Это означает\\, что вы можете изучить мой исходный код или принять участие в моей разработке\\.\n\n *Предлагаю вам оценить мои способности\\. Для этого ваш баланс только что был пополнен на __2000__ токенов\\. Теперь введите /help\\, чтобы узнать о базовых возможностях и доступных командах\\!*",
        },
        "help": [
            {
                "en": "*Sebastian provides access to OpenAI's GPT-4o and DALL-E.*\nHis usage is pretty straightforward:\n\n *Just type any message to chat with GPT-4o!*\n\n To reduce the waiting time, Sebastian splits his speech into paragraphs and sends them when ready - you don't need to wait for the generation of the entire response to finish.\n *Only the last messages of your conversation are stored. Sebastian remembers them for 2 hours and then forgets. You may use /forget command to explicitly clear the Sebastian's memory.*\n\n `Note: the length of your messages is almost unlimited! Even if your message is so large that Telegram splits it into pieces, don't worry: Sebastian will consider them as a whole anyway.`",
                "ru": "*Себастиан предоставляет доступ к моделям GPT-4o и DALL-E от OpenAI.*\nПринцип его работы крайне прост:\n\n *Просто напишите любое сообщение, чтобы начать общение с GPT-4o!*\n\n Чтобы снизить время ожидания, Себастиан разбивает своё сообщение на абзацы и присылает их по мере готовности. Вам не придется ждать окончания генерации всего ответа целиком.\n *Запоминаются только последние сообщения. Себастиан хранит их в течение двух часов, после чего забывает. Вы можете ввести команду /forget, чтобы вручную отчистить его память.*\n\n `Примечание: длина исходящий сообщений практически неограничена! Если ваше сообщение будет очень длинным, и Telegram автоматически разделит его и отправит по частям, не переживайте: Себастиан поймёт, что произошло, и ответит на все части вместе, как на одно-единственное сообщение.`",
            },
            {
                "en": "*Sebastian is able to recognize and analyze images.*\n In order to do that, you need to send an image or attach it to your text prompt.\n\n Multiple images in a single conversation are allowed, so one of the use cases of the image recognition feature is correction of Sebastian's responses:\n\n *If some of his text response is incorrect, you may send a photo with the result of following his instructions and ask him to fix the error.*\n\n This process can be repeated many times.\n\n `Note: Image recognition has a fixed cost, regardless of resolution.`",
                "ru": "*Себастиан умеет распознавать и анализировать содержимое изображений.*\n Для этого необходимо либо отправить изображение отдельным сообщением, либо прикрепить его к вашему текстовому запросу.\n\n Допускается отправка нескольких изображений в рамках одного диалога, поэтому одно из применений этой функции заключается использовании изображений для корректирования предлагаемых Себастианом решений или инструкций:\n\n *Если его сообщение содержит ошибку, можно отправить ему изображение с результатом выполнения его инструкций и потребовать исправить ошибку.*\n\n Данный процесс может повторяться до тех пор, пока не будет получен удовлетворительный результат.\n\n `Примечание: распознавание изображения имеет фиксированную стоимость вне зависимости от разрешения.`",
            },
            {
                "en": "*Sebastian has image generation feature using DALLE-3.*\n To generate an image send him a message like this:\n\n `/draw YOUR_PROMPT`,\n\nwhere `YOUR_PROMPT` - is a description of an image you want.\n Notice that completely different models are used for an image generation and text prompts. DALLE-3, which is in charge of image generation, doesn't know about GPT-4o's presence, which means *the message that contains the /draw command exists outside of the context of the rest of the conversation.*\n\n There is a button \"Draw similar images\" under the generated picture, which let you generate two variations of the original image using DALLE-2.\n\n `Note: OpenAI has a strict content policy which may result in your prompt being blocked. In that case just come up with another choice of words and try again.`",
                "ru": '*Себастиан способен генерировать изображения, используя DALLE-3.*\n Чтобы сгенерировать изображение, отправьте Себастиану сообщение следующего вида:\n\n `/draw ВАШ_ЗАПРОС`,\n\nгде `ВАШ_ЗАПРОС` - описание изображения, которое вы хотите получить.\n Обратите внимание, что для создания изображений и текстовых запросов используются разные модели. DALLE-3, отвечающая за создание изображений, не знает осуществовании GPT-4o. Это означает, что *сообщение с командой /draw существует вне контекста остального разговора с Себастианом.*\n\n Кнопка "Нарисовать похожие изображения" под сгенерированной картинкой создать две вариации исходной картинки посредством DALLE-2.\n\n `Примечание: OpenAI имеет весьма строгую политику использования своих моделей, что может привести к ошибкам при генерации изображений с описанием, являющимся провокативным по мнению OpenAI. В случае, если у вас возникнет такая ошибка, попробуйте переформулировать свой запрос с использованием более нейтральных выражений.`',
            },
            {
                "en": "*Sebastian automatically highlights and numbers LaTeX formulas in the text, allowing you to convert them into images with a single button press.*\n\n To convert a formula into an image, you need to find the button with the corresponding number under the message. For example:\n\n*#1:*\n`\\[ \\nabla \\cdot \\mathbf{u} = 0 \\]`.\n\nIn this case, you need to press the __#1__ button under the message. After pressing it, Sebastian will send a new message with the image, which can be hidden by pressing the __Hide__ button.",
                "ru": "*Себастиан автоматически выделяет и нумерует формулы LaTeX в тексте, позволяя одним нажатием кнопки преобразовывать их в изображение.*\n\n Для того, чтобы преобразовать формулу в изображение, необходимо найти кнопку с соответствующим номером под собщением. Например:\n\n*#1:*\n`\\[ \\nabla \\cdot \\mathbf{u} = 0 \\]`.\n\nВ данном случае необходимо нажать кнопку __#1__ под сообщением. После её нажатия Себастиан пришлёт новое сообщение с изображением, которое можно будет скрыть, нажав кнопку __Скрыть__.",
            },
        ],
        "payment": {
            "en": "*Your balance: {} tokens.*\n\n Sebastian uses tokens to pay for your interactions with *GPT-4o* and *DALLE*. The number of tokens charged for each message depends solely on the size of that message.\n *Purchased tokens remain with you forever. Therefore, there are no subscriptions or regular payments. If you don't use your tokens, you don't pay anything.*\n\n To purchase tokens, use the command /pay:\n\n `/pay STARS_AMOUNT`,\n\nwhere `STARS_AMOUNT` is the amount of Telegram Stars you wish to spend on tokens. The minimum purchase is ⭐️*1* which equals *{}* tokens.\n\n `Note: You can get a full refund within 28 days using the command /refund.`",
            "ru": "*Ваш баланс: {} токенов.*\n\n Себастиан использует токены для оплаты вашего взаимодействия с *GPT-4o* и *DALLE*. Количество токенов, взымаемых за каждое сообщение, зависит только от размера этого сообщения.\n *Купленные токены остаются у вас навсегда. Таким образом, никаких подписок и регулярных платежей нет. Не использовали свои токены - ничего не платите.*\n\n Для покупки токенов используйте команду /pay:\n\n `/pay ЧИСЛО_ЗВЁЗД`,\n\nгде `ЧИСЛО_ЗВЁЗД` - сумма, на которую вы желаете приобрести токены. Минимальная сумма покупки - ⭐*1*, что равняется *{}* токенам.\n\n `Примечание: Вы можете вернуть свои средства в полном обьеме в течение 28, используя команду /refund.`",
        },
        "tokens": {
            "en": "OpenAI's models process text as a set of *tokens*.\n Tokens - are common sequences of characters found in text. You can think of tokens as pieces of words, where 1,000 tokens is about 750 words.\n\n Input tokens (what you send to a model) and output tokens (what the model returns) have different costs. Although input tokens are cheaper, they are used for sending context - information about all previous messages.\n *The GPT models do not remember what you've been talking about. Instead, all previous messages are send together with a new one.* For this reason, it's recommended to clear Sebastian's memory by using /forget command once you've changed a subject of your conversation. Example:\n\n  `USER: sends a message A; (of 10 tokens long)\n SEBASTIAN: sends a message B; (25 tokens)\n USER: sends a message C; (5 tokens)`\n\n In this case, sending the message `C` costs as much as 5+25+10=40 tokens because *all previous messages are also sent to a server.*",
            "ru": "Модели OpenAI анализируют текст, воспринимая его частями, называемыми *токенами*.\n Токены - это просто последовательность из ~4 символов. Можно думать о токенах как о кусочках слов, на которые разбивается каждый текст.\n\n Цены на входящие (то, что вы отправляете в модель) и исходящие (то, что модель возвращает) токены отличаются. Цены на входящие токены ниже, но они используются для отправки информации о всех прошлых сообщениях.\n *Модели не запоминают ваш разговор, вместо этого каждый раз, когда вы пишете новое сообщение, вместе с ним на сервер отправляются и все предыдущие сообщения.* Поэтому при смене темы разговора рекомендуется использовать команду /forget для удаления предыдущих сообщений из памяти Себастиана. Пример:\n\n  `ПОЛЬЗОВАТЕЛЬ: отправляет сообщение А; (длиной 10 токенов)\n СЕБАСТИАН: отвечает сообщением Б; (25 токенов)\n ПОЛЬЗОВАТЕЛЬ: отправляет сообщение В; (5 токенов)`\n\n Тогда отправка сообщения `В` будет стоить как 5+25+10=40 токенов, так как *вместе с ним будут отправлены все предыдущие сообщения.*",
        },
        "draw": {
            "en": "_The command must have the following syntax:_\n\n `/draw YOUR_PROMPT`,\n\n_where_ `YOUR_PROMPT` _- is a description of an image you want._\n _After executing this command, you will receive an image with a_ `Draw Similar Images` _button. By clicking on it, you will be able to get two similar images._",
            "ru": "_Команда должна иметь следующий вид:_\n\n `/draw ВАШ_ЗАПРОС`,\n\n_где_ `ВАШ_ЗАПРОС` _- описание изображения, которое вы хотите получить._\n _После выполнения этой команды вы получите изображение с кнопкой_ `Нарисовать похожие изображения`, _нажав на которую вы сможете получить два похожих изображения._",
        },
        "refund": {
            "en": "_The command must have the following syntax:_\n\n `/refund PURCHASE_ID`,\n\n_where_ `PURCHASE_ID` _- is the string you got after successful payment with Telegram Stars._\n _After executing this command, the Telegram Stars spent on the purchase will be fully refunded to your account, as long as less than 28 days have passed since the purchase and there are enough tokens for a refund._",
            "ru": "_Команда должна иметь следующий вид:_\n\n `/refund ИДЕНТИФИКАТОР_ПОКУПКИ`,\n\n_где_ `ИДЕНТИФИКАТОР_ПОКУПКИ` _- код, который вы получили после успешного пополнения счета с помощью Звёзд Telegram._\n _После выполнения этой команды потраченные на покупку Звёзды Telegram вернутся вам на счёт в полном обьёме при условии, что с момента совершения покупки прошло менее 28 дней и имеющихся токенов достаточно для возврата._",
        },
        "pay": {
            "en": "_The command must have the following syntax:_\n\n `/pay STARS_AMOUNT`,\n\n_where_ `STARS_AMOUNT` _- is an integer between 1 and 2500. Each ⭐ is *{}* tokens._\n _After executing this command, you will receive a message with a_ `Pay to Sebastian` _button. By clicking on it, you will be able to make a payment for the specified amount of Telegram Stars._",
            "ru": "_Команда должна иметь следующий вид:_\n\n `/pay ЧИСЛО_ЗВЁЗД`,\n\n_где_ `ЧИСЛО_ЗВЁЗД` _- целое число от 1 до 2500._ Одна ⭐ равняется *{}* токенам.\n _После выполнения этой команды вам будет отправлено сообщение с кнопкой_ `Заплатить Себастиану`, _нажав которую вы сможете совершить оплату на указанную вами сумму Звёзд Telegram._",
        },
        "payment description": {
            "en": "You will top up your balance with {} tokens. They will be used exclusively for sending your requests to GPT-4o and DALLE and receiving responses from them.",
            "ru": "Вы пополните свой баланс на {} токенов. Эти средства будут использоваться только для отправки ваших запросов к GPT-4o и DALLE и получения ответов от них.",
        },
    },
    "info": {
        "forget success": {
            "en": "_All previous messages have been forgotten!_",
            "ru": "_Все предыдущие сообщения были забыты!_",
        },
        "payment success": {
            "en": "_*{} tokens has been successfully added to your account!\nSave your purchase ID in case you wish to request a refund in the future!*_\n\n*Purchase ID:* `{}`.",
            "ru": "_*Ваш баланс успешно пополнен на {} токенов!\nСохраните идентификатор покупки на случай, если в будущем пожелаете сделать возврат средств!*_\n\n*Идентификатор покупки:* `{}`.",
        },
        "refund success": {
            "en": "_*Refund successful!* ⭐*{}* have been returned to your account._",
            "ru": "_*Возврат средств произведён успешно!* ⭐*{}* уже вернулись на ваш счёт._",
        },
        "long message": {
            "en": "_The last message seems to be very long. Would you like it to be sent as a text file?_",
            "ru": "_Последнее сообщение оказалось очень длинным. Желаете чтобы оно было прислано в формате текстового файла?_",
        },
    },
    "err": {
        "unexpected err": {
            "en": "*_An unexpected error has occurred. The Sebastian's memory has been automatically cleared, so you may start a new conversation._*\n\n _Don't worry! This incident has been reported and the problem will be fixed soon!_",
            "ru": "_*Возникла непредвиденная ошибка. Память Себастиана была автоматически отчищена, поэтому вы можете начать новый диалог.*\n\n Не переживайте! Об этом инциденте уже сообщено, так что скоро проблема будет исправлена!_",
        },
        "balance is empty": {
            "en": "_You don't have enough tokens to process your request. Please top up your account using the /pay command to access OpenAI models! For a refund, use /refund. To learn more about Sebastian, use /help.\n\n *If it's your first time adding funds to your account, try a minimum payment of ⭐️1 to explore Sebastian's capabilities.*_",
            "ru": "_Недостаточно токенов для оплаты вашего запроса. Пополните счёт, используя команду /pay, чтобы получить доступ к моделям OpenAI! Для возврата средств используйте /refund. Для того, чтобы больше узнать о Себастиана, используйте /help.\n\n *Если вы пополняете счёт впервые, попробуйте минимальный платёж в размере ⭐1 для ознакомления с возможностями Себастиана.*_",
        },
        "not privileged": {
            "en": "_You are not allowed to use this command. Contact @trxxxxkov for a permission._",
            "ru": "_Эта команда вам недоступна. Чтобы получить доступ к ней, свяжитесь с @trxxxxkov._",
        },
        "no source code": {
            "en": "_The source code is unavailable because the message was forgotten._",
            "ru": "_Исходный код недоступен, так как сообщение было забыто_",
        },
        "too old to hide": {
            "en": "A message can only be hidden if it was sent less than 48 hours ago.",
            "ru": "Сообщение может быть скрыто только если оно было отправлено менее 48 часов назад",
        },
        "policy block": {
            "en": "_The response has been blocked by OpenAI because your prompt violates its content policy. Consider using other words in your prompt!_",
            "ru": "_Ваш запрос был отклонён сервером OpenAI, так как в нём содержится запрещённая информация. Попробуйте изменить формулировку и использовать другие слова!_",
        },
        "nothing to convert": {
            "en": "No messages are available to be sent as a file.",
            "ru": "Отсутствуют сообщения, которые можно было бы отправить как файл.",
        },
        "already refunded": {
            "en": "_Refund for the purchase with the specified ID has already been processed. The stars have been successfully returned to your account!\n\n *If you believe an error has occurred, please contact @trxxxxkov.*_",
            "ru": "_Возврат за покупку с указанным идентификатором уже был выполнен ранее. Звёзды успешно зачислены на ваш счёт!\n\n *Если вы полагаете, что произошла ошибка, пожалуйста, свяжитесь с @trxxxxkov.*_",
        },
        "invalid purchase id": {
            "en": "_The provided purchase ID is invalid.\n\n *If you believe an error has occurred, plase contact @trxxxxkov.*_",
            "ru": "_Возврат за покупку с указанным идентификатором невозможен.\n\n *Если вы полагаете, что произошла ошибка, пожалуйста, свяжитесь с @trxxxxkov.*_",
        },
        "refund expired": {
            "en": "_The refund period for the purchase with the specified identifier has expired.\n\n *If you believe an error has occurred, plase contact @trxxxxkov.*_",
            "ru": "_Срок возврата за покупку с указанным идентификатором истёк.\n\n *Если вы полагаете, что произошла ошибка, пожалуйста, свяжитесь с @trxxxxkov.*_",
        },
    },
    "bttn": {
        "to help": [
            {"en": "Prompts", "ru": "Текстовые запросы"},
            {"en": "Recognition", "ru": "Распознавание"},
            {"en": "Drawing", "ru": "Рисование"},
            {"en": "LaTeX", "ru": "LaTeX"},
        ],
        "redraw": {
            "en": "Draw similar images",
            "ru": "Нарисовать похожие изображения",
        },
        "to balance": {"en": "Your balance & prices", "ru": "Цены и баланс"},
        "what now": {"en": "What now?", "ru": "Что теперь?"},
        "hide": {"en": "Hide", "ru": "Скрыть"},
        "to tokens": {"en": "What are tokens?", "ru": "Что такое токены?"},
        "back to balance": {
            "en": "To your balance & prices",
            "ru": "К ценам и балансу",
        },
        "back to help": {"en": "/help", "ru": "/help"},
        "pay": {"en": "Pay ⭐{} to Sebastian", "ru": "Заплатить Себастиану ⭐{}"},
        "try payment": {"en": "Pay ⭐1", "ru": "Заплатить ⭐1"},
        "send as file": {
            "en": "Send as a text file",
            "ru": "Отправить в формате текстового файла",
        },
    },
    "other": {
        "payment title": {
            "en": "Payment for Sebastian's services",
            "ru": "Оплата услуг Себастиана",
        },
        "vision pre-prompt": {
            "en": "What do you think about it?",
            "ru": "Что ты об этом думаешь?",
        },
    },
}
