dialogues = {
    "en": {
        "start": """
Pleased to meet you, *{}*!

  My name is *Sebastian*. I'm a bot powered by GPT-4o. Here is a short list of my skills:

  *Casual conversations*:
Type a message (of any length!) to start a conversation. I will reply with my message splitted into paragraphs so that you don't need to wait until I finish typing.

  *Image generation (DALLE-3) and variation (DALLE-2)*:
Describe your idea and generate an image based on it.

  *Image recognition*:
Attach an image to your message and ask any questions about it.

  *Automatic compilation of LaTeX formulas*:
Discuss math problems with comfort! All formulas will be compiled and sent as images.

  *No subscription or annual payments*:
You should only pay for the tokens that you used. No usage - no payment.

  *Type /help to get started!*""",
        "help": [
            """
*Sebastian provides access to OpenAI's GPT-4o and DALL-E.*
  His usage is pretty straightforward:

  *Just type any message to chat with GPT-4o!*

  To reduce the waiting time, Sebastian splits his speech into paragraphs and sends them when ready - you don't need to wait for the generation of the entire response to finish.
  *Only the last messages of your conversation are stored. Sebastian remembers them for 2 hours and then forgets. You may use /forget command to explicitly clear the Sebastian's memory.*
  
  `Note: the length of your messages is almost unlimited! Even if your message is so large that Telegram splits it into pieces, don't worry: Sebastian will consider them as a whole anyway.`""",
            """
*Sebastian is able to recognize and analyze images.*
  In order to do that, you need to send an image or attach it to your text prompt.

  Multiple images in a single conversation are allowed, so one of the use cases of the image recognition feature is correction of Sebastian's responses:

  *If some of his text response is incorrect, you may send a photo with the result of following his instructions and ask him to fix the error.*
  
  This process can be repeated many times.

  `Note: Image recognition has a fixed cost, regardless of resolution, equal to $0.008 \u2248 0.73\u20bd.`""",
            """
*Sebastian has image generation feature using DALLE-3.*
  To generate an image send him a message like this:

  `/draw YOUR_PROMPT`,

where `YOUR_PROMPT` - is a description of an image you want.
  Notice that completely different models are used for an image generation and text prompts. DALLE-3, which is in charge of image generation, doesn't know about GPT-4o's presence, which means *the message that contains the /draw command exists outside of the context of the rest of the conversation.*
  
  There is a button "Draw similar images" under the generated picture, which let you generate two variations of the original image using DALLE-2.

  `Note: OpenAI has a strict content policy which may result in your prompt being blocked. In that case just come up with another choice of words and try again.`""",
            """
*Sebastian automatically compile LaTeX formulas and send them as images.*
  In order to keep responses compact, only the most long and difficult formulas are compiled while the others are marked in bold font.

  "Show the source code" button under each image let you access the LaTeX code of it.

  *The automatic compilation feature does not apply to the LaTeX code that is considered a document.* This is a code that contains any of this:
  `
  documentclass{...}
  usepackage{...}
  begin{document}
  ...
  end{document}`

  Sebastian sends such code as is, without compilation.""",
        ],
        "balance": """ 
  *Your balance: ${} \u2248 {}*\u20bd *\u2248 {} tokens.*
        
  """,
        "payment": """
*Sebastian is not free for use.*
  The usage cost is determined by amount of tokens you used. So, *there isn't any subscription or annual payment. No usage - no payment.*
  The cost of each token is tied to OpenAI's pricing and can be calculated as following:

  `SEBASTIAN_TOKEN_PRICE = FEE * OPENAI_TOKEN_PRICE`,
  
  `FEE` - is currently equal to {},
  `OPENAI_TOKEN_PRICE` - can be found here: https://openai.com/pricing (prices per 1,000,000 tokens).

  *You may use GPT-4o and DALLE-3 only after you top up you balance.*
  Payment methods: Tinkoff/Sberbank transfter to +7-900-65-60-859. *Contact @trxxxxkov to inform about your payment.*""",
        "tokens": """
OpenAI's models process text as a set of *tokens*. 
  Tokens - are common sequences of characters found in text. You can think of tokens as pieces of words, where 1,000 tokens is about 750 words.
        
  Input tokens (what you send to a model) and output tokens (what the model returns) have different costs. Although input tokens are cheaper, they are used for sending context - information about all previous messages. 
  *The GPT models do not remember what you've been talking about. Instead, all previous messages are send together with a new one.* For this reason, it's recommended to clear Sebastian's memory by using /forget command once you've changed a subject of your conversation. Example:
  `
  USER: sends a message A; (of 10 tokens long)
  SEBASTIAN: sends a message B; (25 tokens)
  USER: sends a message C; (5 tokens)`
  
  In this case, sending the message `C` costs as much as 5+25+10=40 tokens because *all previous messages are also sent to a server.*""",
        "error": """
*_An unexpected error has occurred. The Sebastian's memory has been automatically cleared, so you may start a new conversation._* 
        
  _Don't worry! This incident has been reported and the problem will be fixed soon!_""",
        "empty": """
_You don't have enough funds to perform this request. You have to add funds to use GPT-4o and DALLE models. 
  For more details, type /balance_""",
        "draw": """
Describe the image you want to get after /draw command, for example:

  `/draw The stars tennis-balls, struck and bandied which way please them`""",
        "root": "_You are not allowed to use this command. Contact @trxxxxkov for a permission._",
        "forget": "_All previous messages have been forgotten!_",
        "forgotten": "_The source code is unavailable because the message was forgotten._",
        "old": "_A message can only be hidden if it was sent less than 48 hours ago._",
        "block": "_The response has been blocked by OpenAI because your prompt violates its content policy. Consider using other words in your prompt!_",
        "vision-pre-prompt": "What do you think about it?",
    },
    "ru": {
        "start": """
Здравствуйте, *{}*! 

  Меня зовут *Себастиан*. Я - бот под управлением GPT-4o. Вот краткий список моих возможностей:

  *Свободное общение*:
Начните разговор, просто написав мне сообщение (любой длины!), и я отвечу, раздробив своё сообщение по абзацам, чтобы вам не пришлось ждать, пока я допишу.

  *Распознавание изображений*:
Прикрепите фотографию к вашему сообщению и задавайте любые вопросы.

  *Генерация (DALLE-3) и вариация (DALLE-2) изображений*:
Опишите свою идею и получите изображение, созданное по мотивам ваших слов.

  *Автоматическое компиляция формул LaTeX*:
Обсуждайте математику с комфортом! Все формулы будут скомпилированы и отправлены в виде изображений.

  *Никаких подписок и ежемесячных платежей*:
Платите только за токены, которые вы использовали. Ничего не использовали - ничего не платите.

  *Введите команду /help, чтобы узнать больше!*""",
        "help": [
            """
*Себастиан предоставляет доступ к моделям GPT-4o и DALL-E от OpenAI.*
  Принцип его работы крайне прост:

  *Просто напишите любое сообщение, чтобы начать общение с GPT-4o!*

  Чтобы снизить время ожидания, Себастиан разбивает своё сообщение на абзацы и присылает их по мере готовности. Вам не придется ждать окончания генерации всего ответа целиком.     
  *Запоминаются только последние сообщения. Себастиан хранит их в течение двух часов, после чего забывает. Вы можете ввести команду /forget, чтобы вручную отчистить его память.*

  `Примечание: длина исходящий сообщений практически неограничена! Если ваше сообщение будет очень длинным, и Telegram автоматически разделит его и отправит по частям, не переживайте: Себастиан поймёт, что произошло, и ответит на все части вместе, как на одно-единственное сообщение.`
 """,
            """
*Себастиан умеет распознавать и анализировать содержимое изображений.*
  Для этого необходимо либо отправить изображение отдельным сообщением, либо прикрепить его к вашему текстовому запросу.

  Допускается отправка нескольких изображений в рамках одного диалога, поэтому одно из применений этой функции заключается использовании изображений для корректирования предлагаемых Себастианом решений или инструкций: 
  
  *если его сообщение содержит ошибку, можно отправить ему изображение с результатом выполнения его инструкций и потребовать исправить ошибку.*

  Данный процесс может повторяться до тех пор, пока не будет получен удовлетворительный результат.

  `Примечание: распознавание изображения имеет фиксированную стоимость вне зависимости от разрешения, равную $0.008 \u2248 0.73\u20bd.`""",
            """
*Себастиан способен генерировать изображения, используя DALLE-3.*
  Чтобы сгенерировать изображение, отправьте Себастиану сообщение следующего вида:
  
  `/draw ВАШ_ЗАПРОС`,
  
где `ВАШ_ЗАПРОС` - описание изображения, которое вы хотите получить. 
  Обратите внимание, что для создания изображений и текстовых запросов используются разные модели. DALLE-3, отвечающая за создание изображений, не знает осуществовании GPT-4o. Это означает, что *сообщение с командой /draw существует вне контекста остального разговора с Себастианом.*
  
  Кнопка "Нарисовать похожие изображения" под сгенерированной картинкой создать две вариации исходной картинки посредством DALLE-2.

  `Примечание: OpenAI имеет весьма строгую политику использования своих моделей, что может привести к ошибкам при генерации изображений с описанием, являющимся провокативным по мнению OpenAI. В случае, если у вас возникнет такая ошибка, попробуйте переформулировать свой запрос с использованием более нейтральных выражений.`""",
            """
*Себастиан автоматически преобразовывает формулы LaTeX в изображения.*
  В целях сохранения компактности переписки, преобразование затрагивает только некоторые, достаточно сложные формулы. Все прочие формулы просто выделяются жирным шрифтом. 

  Кнопка "Показать исходный код" под изображением с формулой позволяет увидеть LaTeX код, соответствующий данной формуле.

  *Функция автоматического преобразования кода не распространяется на LaTeX код, представляющий собой полноценный документ*. Документом считается код, содержащий что-либо из этого:
  `
  documentclass{...}
  usepackage{...}
  begin{document}
  ...
  end{document}`

  Такой код отправляется Себастианом без каких-либо преобразований.
            """,
        ],
        "balance": """
*Ваш баланс: ${} \u2248 {}*\u20bd *\u2248 {} токенов.*
        
  """,
        "payment": """
*Себастиан не бесплатен.*
  Цена определяется только количеством использованных вами токенов, то есть *никаких подписок и регулярных платежей нет. Ничего не использовали - ничего не платите.*
  Цена каждого токена жёстко связана с тарифами OpenAI, и вычисляется следующим образом:

  `ЦЕНА_ТОКЕНА_СЕБАСТИАНА = FEE * ЦЕНА_ТОКЕНА_OPENAI`,

  `FEE` - комиссия, в данный момент равная {},
  `ЦЕНА_ТОКЕНА_OPENAI` - доступна здесь: https://openai.com/pricing (цены указаны за 1,000,000 токенов).

  *Вы можете использовать GPT-4o и DALLE-3 только после пополнения баланса.*
  Способ оплаты: Тиньков/Сбербанк перевод по номеру +7-900-656-08-59. *Чтобы сообщить о вашем платеже, свяжитесь с @trxxxxkov.*""",
        "tokens": """
Модели OpenAI анализируют текст, воспринимая его частями, называемыми *токенами*.
  Токены - это просто последовательность из ~4 символов. Можно думать о токенах как о кусочках слов, на которые разбивается каждый текст. 

  Цены на входящие (то, что вы отправляете в модель) и исходящие (то, что модель возвращает) токены отличаются. Цены на входящие токены ниже, но они используются для отправки информации о всех прошлых сообщениях. 
  *Модели не запоминают ваш разговор, вместо этого каждый раз, когда вы пишете новое сообщение, вместе с ним на сервер отправляются и все предыдущие сообщения.* Поэтому при смене темы разговора рекомендуется использовать команду /forget для удаления предыдущих сообщений из памяти Себастиана. Пример:
  `
  ПОЛЬЗОВАТЕЛЬ: отправляет сообщение А; (длиной 10 токенов)
  СЕБАСТИАН: отвечает сообщением Б; (25 токенов)
  ПОЛЬЗОВАТЕЛЬ: отправляет сообщение В; (5 токенов)`
  
  Тогда отправка сообщения `В` будет стоить как 5+25+10=40 токенов, так как *вместе с ним будут отправлены все предыдущие сообщения.*""",
        "error": """
_*Возникла непредвиденная ошибка. Память Себастиана была автоматически отчищена, поэтому вы можете начать новый диалог.*
        
  Не переживайте! Об этом инциденте уже сообщено, так что скоро проблема будет исправлена!_""",
        "empty": """
_Недостаточно средств для оплаты вашего запроса. Пополните счёт, чтобы использовать модели GPT-4o DALLE.
  Для получения информации о ценах и способах пополнения, введите команду /balance_""",
        "draw": """
Введите команду /draw и опишите изображение, которое желаете получить, например:
     
  `/draw Теннисные мячики небес, которые соединяют и лупят, как захотят`""",
        "root": "_Эта команда вам недоступна. Чтобы получить доступ к ней, свяжитесь с @trxxxxkov._",
        "forget": "_Все предыдущие сообщения были забыты!_",
        "forgotten": "_Исходный код недоступен, так как сообщение было забыто_",
        "old": "_Сообщение может быть скрыто только если оно было отправлено менее 48 часов назад_",
        "block": "_Ваш запрос был отклонён сервером OpenAI, так как в нём содержится запрещённая информация. Попробуйте изменить формулировку и использовать другие слова!_",
        "vision-pre-prompt": "Что ты об этом думаешь?",
    },
}
