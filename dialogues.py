dialogues = {
    "ru": {
        "auth": "Вы не были добавлены в список разрешённых пользователей. Свяжитесь с @trxxxxkov, чтобы получить доступ к боту.",
        "start": """Привет, *{}*! 

Меня зовут *Себастиан*. Я - бот под управлением GPT-4-Turbo. Вот краткий список моих возможностей:

 *Свободное общение*: начните разговор, просто написав мне сообщение (любой длины!), и я отвечу, раздробив своё сообщение по абзацам, чтобы вам не пришлось ждать, пока я допишу.

 *Генерация (DALLE-3) и вариация (DALLE-2) изображений*: опишите свою идею и получите изображение, созданное по мотивам ваших слов.

 *Распознавание изображений*: прикрепите фотографию к вашему сообщению и задавайте любые вопросы.

 *Автоматическое компиляция формул LaTeX*: обсуждайте математику с комфортом! Все формулы будут скомпилированы и отправлены в виде изображений.

 *Никаких подписок и ежемесячных платежей*: платите только за токены, которые вы использовали. Ничего не использовали - ничего не платите.

 *Введите команду /help, чтобы узнать больше!*""",
        "help": [
            """Себастиан предоставляет доступ к моделям GPT-4-Turbo и DALL-E от OpenAI. Принцип его работы очень прост:

      *Просто напишите любое сообщение, чтобы начать общение с GPT-4-Turbo.*

 Чтобы снизить время ожидания, *Себастиан разбивает свой ответ на абзацы и присылает их по готовности.* Вам не придется ждать окончания генерации всего ответа целиком. Технически, такие абзацы являются частью одного-единственного сообщения от GPT-4-Turbo, и запоминаются только последние 20 сообщений. *Длина отправляемых сообщений не ограничена!* Даже если ваше сообщение будет очень большим, и Телеграм разобъёт его на части, они будут восприняты как единое целое. Себастиан хранит сообщения на протяжении двух часов, а потом забывает. Вы можете ввести команду /forget, чтобы вручную отчистить память Себастиана.
 """,
            """Помимо понимания обычных текстовых сообщений, *доступно распознавание изображений* - достаточно прикрепить к вашему сообщению любую картинку. *Также Себастиан способен компилировать формулы LaTeX в изображения*, поэтому с ним особенно приятно обсуждать вопросы, касающиеся математики. Если захотите, Себастиан скомпилирует и вашу формулу - просто попросите его об этом!

`Примечание: крайне рекомендуется вводить команду /forget каждый раз, когда вы собираетесь сменить тему разговора, так как чем меньше памяти использует Себастиан, тем меньше стоимость общения с ним: хранящиеся в памяти сообщения можно воспринимать как "одно большое сообщение", которое каждый раз добавляется к новому сообщению, а потом отправляется на сервер OpenAI и обрабатывается вместе с ним.`""",
            """ *Ещё одна функция - генерация изображений*:
Если вы введёте команду /draw, а после напишите описание картинки, возникшей у вас в голове, Себастиан использует DALLE-3 чтобы воплотить ваши фантазии в жизнь. После того, как изображение будет сгенерировано, вы сможете сгенерировать два дополнительных варианта этого изображения, нажав кнопку "Нарисовать похожие изображения!" под первой картинкой. Эти два варианта генерируются с помощью DALLE-2, поэтому они имеют намного меньшую цену, и меньшее качество.

`Примечание: OpenAI имеет весьма строгую политику использования своих моделей, что может привести к ошибкам при генерации изображений с описанием, являющимся провокативным по мнению OpenAI. В случае, если у вас возникнет эта ошибка, попробуйте переформулировать свой запрос с использованием более нейтральных выражений.`""",
            """*Себастиан не бесплатен.*
OpenAI, модели которой используются этим ботом, берёт плату за обработку каждого отправленного сообщения, поэтому вам необходимо компенсировать все затраты, если вы желаете сохранить свой доступ. Это подразумевает оплату всех токенов, которые вы использовали. *Никаких подписок и регулярных платежей нет.* Вы можете получить больше информации о расценках, способах оплаты и вашем текущем балансе, введя команду /balance.

Если у вас есть предложения касательно добавления нового функционала, вы хотите поделиться доступом к боту с другом или вы столкнулись с ошибкой при взаимодействии с ботом, пожалуйста, свяжитесь с @trxxxxkov.""",
        ],
        "forget": "_Все предыдущие сообщения были забыты!_",
        "balance": """*Ваш баланс: ${} \u2248 {}*\u20bd \u2248 {} токенов.

*Обратите внимание, что если на вашем балансе будет недостаточно средств для совершения запроса, доступ к GPT-4-Turbo и DALLE-3 будет приостановлен до тех пор, пока вы не пополните счёт.*
Предпочитаемый способ оплаты: Тиньков, +7-900-656-08-59.
Напишите ваше имя в комментарии к переводу или свяжитесь с @trxxxxkov, чтобы сообщить о вашем платеже.

При использовании Себастиана стоимость каждого отправленного и полученного сообщения считается отдельно (со стоимостью токенов OpenAI можно ознакомиться здесь: https://openai.com/pricing) и умножается в ~1.6 раз для компенсации комиссий сервисов, предоставляющих иностранные карты (20-30%) и налогов (VAT \u2248 19%).
*Этот коэффициент может быть снижен, если вы предоставите информацию о способе пополнения счёта в OpenAI с меньшей комиссией. Пожалуйста, свяжитесь с @trxxxxkov, если у вас есть такая информация!*""",
        "empty": """*Недостаточно средств для оплаты вашего запроса. Доступ к моделям OpenAI приостановлен до тех пор, пока счёт не будет пополнен.* Для получения информации о расценках и способах оплаты, введите команду /balance""",
        "draw": """Введите команду /draw и опишите изображение, которое желаете получить, например:```
/draw Теннисные мячики небес, которые соединяют и лупят, как захотят```""",
        "old": "Сообщение может быть скрыто только если оно было отправлено менее 48 часов назад",
        "forgotten": "*[СООБЩЕНИЕ БЫЛО ЗАБЫТО]*",
        "error": """Возникла непредвиденная ошибка. Для предотвращения повторного сбоя память Себастиана была автоматически отчищена, и теперь вы можете начать новый диалог. 
        
 *Не переживайте! Об этом инциденте уже сообщено, так что скоро проблема будет исправлена!*""",
        "block": "*Ваш запрос был отклонён сервером OpenAI, так как в нём содержится запрещённая информация.* Попробуйте изменить формулировку и использовать другие слова!",
    },
    "en": {
        "auth": "You are not authorized. Contact @trxxxxkov to be allowed to chat.",
        "start": """Hello, *{}*!

My name is *Sebastian*. I'm a bot powered by GPT-4-Turbo. Here is a short list of my skills:

 *Casual conversations*: type a message (of any length!) to start a conversation. I will reply with my message splitted into paragraphs so that you don't need to wait until I finish typing.

 *Image generation (DALLE-3) and variation (DALLE-2)*: describe your idea and generate an image based on it.

 *Image recognition*: attach an image to your message and ask any questions about it.
        
 *Automatic compilation of LaTeX formulas*: discuss math problems with comfort! All formulas will be compiled and sent as images.

 *No subscription or annual payments*: you should only pay for the tokens that you used. No usage - no payment.

*Type /help to get started!*""",
        "help": [
            """Sebastian provides access to OpenAI's *GPT-4-Turbo* and *DALL-E*. Its usage is pretty straightforward:

     *Just type any message to chat with GPT-4-Turbo.*

 To reduce the waiting time, *Sebastian splits his speech into paragraphs and sends them as the are finished.* You don't need to wait for the generation of the entire response to finish. Technically, such paragraphs are part of a single message from GPT-4-Turbo, and only the last 20 messages of your conversation are stored. *The length of your messages is unlimited!* Even if your message is large and Telegram split it into pieces, they will be considered as a whole. Sebastian remembers them for 2 hours and then forgets. You may use /forget command to explicitly clear Sebastian's memory.""",
            """Among regular text messages, *image recognition is available* - attach an image to your question and wait for a result. *Sebastian also can compile LaTeX formulas into images*, so he is exceptionally good at talking about math. He may compile your formula if you want to!

`Note: it's recommended to run /forget when you want to change a topic of conversation because the less memory Sebastian uses, the cheaper your conversation is: stored messages can be considered as a "big single message" which is sent and processed together with each new message.`""",
            """*Another feature is image generation*:
If you type /draw command and provide a description, Sebastian will use DALLE-3 to bring your idea into the world. After an image is generated, you may get two variations of it by clicking "Draw similar images!" button below. The variations are generated by DALLE-2 which means they have much lower cost and lower quality.

`Note: OpenAI has quite a strict content policy which may result in error if your description is considered unethical. In this case just come up with another choice of words and try again.`""",
            """*Sebastian is not free to use.*
OpenAI, whose models are used by this bot, charges processing of your messages so you should cover expenses if you want to preserve access, which means that you have to pay for all tokens that you used. *There isn't any subscription or annual payment.* You may find details about pricing, payment and your current expenses by typing /balance command.""",
            """If you have any wishes for adding new features, want to share this bot with your friends or encountered an error, please contact @trxxxxkov.""",
        ],
        "forget": "_All previous messages have been forgotten!_",
        "balance": """You balance: ${} \u2248 {}\u20bd \u2248 {} tokens. 

Note that if your balance is empty, your access to GPT-4-Turbo will be paused until you add funds.
Preferred payment method: Tinkoff, +7-900-656-08-59. 
Add your username in the payment comments or contact @trxxxxkov to inform about your fee.

Payment is calculated for each token (OpenAI's tokens pricing for GPT-4-Turbo can be found here: https://openai.com/pricing) and multiplied by ~1.6 as compensation for account top-up fees (20-30%) and taxes (VAT \u2248 19%).
The coefficient will be decreased if you share a payment method with less fee. Contact @trxxxxkov if you have one!""",
        "empty": """*Your access is paused because your balance is empty.*
You have to add funds to continue using this bot. 
For more details, type /balance""",
        "draw": """Describe the image you want to get after /draw command, for example:```
/draw The stars tennis-balls, struck and bandied which way please them```""",
        "forgotten": "*[THE MESSAGE WAS FORGOTTEN]*",
        "old": "A message can only be hidden if it was sent less than 48 hours ago",
        "error": """An unexpected error has occurred. To prevent it from happening again, the Sebastian's memory has been automatically cleared, so you may start a new conversation with him. 
        
 *Don't worry! This incident has been reported and the problem will be fixed soon!*""",
        "block": "*The response has been blocked by OpenAI because your prompt violates its content policy.* Consider using other words in your prompt!",
    },
}
