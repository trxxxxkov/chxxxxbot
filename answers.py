templates = {
    "ru": {
        "auth": "Вы не были добавлены в список разрешённых пользователей. Свяжитесь с @trxxxxkov, чтобы получить доступ к боту.",
        "start": "Привет, *{}*! Введите команду /help, чтобы больше узнать о возможностях этого бота.",
        "help": """Себастиан предоставляет доступ к моделям GPT-4-Turbo и DALL-E от OpenAI. Принцип его работы очень прост:

      *Просто напишите любое сообщение, чтобы начать общение с GPT-4-Turbo.*
      
Запоминаются только последние 20 сообщений. Себастиан хранит их на протяжении двух часов, а потом забывает. Вы можете ввести команду /forget, чтобы вручную отчистить память Себастиана.

`Примечание: крайне рекомендуется вводить команду /forget каждый раз, когда вы собираетесь сменить тему разговора, так как чем меньше памяти использует Себастиан, тем меньше стоимость общения с ним: хранящиеся в памяти сообщения можно воспринимать как "одно большое сообщение", которое каждый раз добавляется к новому сообщению, а потом отправляется на сервер OpenAI и обрабатывается вместе с ним.`

*Себастиан не бесплатен.*
OpenAI, модели которой используются этим ботом, берёт плату за обработку каждого отправленного сообщения, поэтому вам необходимо компенсировать все затраты, если вы желаете сохранить свой доступ. Это подразумевает оплату всех токенов, которые вы использовали. *Никаких подписок и регулярных платежей нет.* Вы можете получить больше информации о расценках, способах оплаты и вашем текущем балансе, введя команду /balance.

Если у вас есть предложения касательно добавления нового функционала, вы хотите поделиться доступом к боту с другом или вы столкнулись с ошибкой при взаимодействии с ботом, пожалуйста, свяжитесь с @trxxxxkov.

Кстати, в ближайшее время Себастиан получит новые возможности:
    ` - Перевод описания и команд бота на Французский язык;`""",
        "forget": "{} предыдущих сообщений было забыто!",
        "balance": """*Ваш баланс: ${} \u2248 {}*\u20bd.

*Обратите внимание, что если на вашем балансе будет недостаточно средств для совершения запроса, доступ к GPT-4-Turbo и DALLE-3 будет приостановлен до тех пор, пока вы не пополните счёт.*
Предпочитаемый способ оплаты: Тиньков, +7-900-656-08-59.
Напишите ваше имя в комментарии к переводу или свяжитесь с @trxxxxkov, чтобы сообщить о вашем платеже.

При использовании Себастиана стоимость каждого отправленного и полученного сообщения считается отдельно (со стоимостью токенов OpenAI можно ознакомиться здесь: https://openai.com/pricing) и умножается в ~1.6 раз для компенсации комиссий сервисов, предоставляющих иностранные карты (20-30%) и налогов (VAT \u2248 19%).
*Этот коэффициент может быть снижен, если вы предоставите информацию о способе пополнения счёта в OpenAI с меньшей комиссией. Пожалуйста, свяжитесь с @trxxxxkov, если у вас есть такая информация!*""",
        "empty": """*Недостаточно средств для оплаты вашего запроса. Доступ к моделям OpenAI приостановлен до тех пор, пока счёт не будет пополнен.* Для получения информации о расценках и способах оплаты, введите команду /balance""",
        "draw": """Введите команду /draw и опишите изображение, которое желаете получить, например:```
/draw Теннисные мячики небес, которые соединяют и лупят, как захотят```""",
        "redraw": "Нарисовать похожие изображения!",
        "tokens": "Что такое токены?",
    },
    "en": {
        "auth": "You are not authorized. Contact @trxxxxkov to be allowed to chat.",
        "start": "Hello, ***{}***! Type /help to get started with this bot.",
        "help": """Sebastian provides access to OpenAI's GPT-4-Turbo and DALL-E. Its usage is pretty straightforward:

     *Just type any message to chat with GPT-4-Turbo.*

Only the last 20 messages of your conversation are stored. Sebastian remembers them for 2 hours and then forgets. You may use /forget command to explicitly clear Sebastian's memory.

`Note: it's recommended to run /forget when you want to change a topic of conversation because the less memory Sebastian uses, the cheaper your conversation is: stored messages can be considered as a "big single message" which is sent and processed together with each new message.`

*Sebastian is not free to use.*
OpenAI, whose models are used by this bot, charges processing of your messages so you should cover expenses if you want to preserve access, which means that you have to pay for all tokens that you used. *There isn't any subscription or annual payment.* You may find details about pricing, payment and your current expenses by typing /balance command.

If you have any wishes for adding new features, want to share this bot with your friends or encountered an error, please contact @trxxxxkov.

Btw, the following features will be added soon:
    `- Translation of this bot's commands and description into French;`""",
        "forget": "All previous messages have been forgotten!",
        "balance": """*You balance: ${} \u2248 {}*\u20bd. 

*Note that if your balance is empty, your access to GPT-4-Turbo will be paused until you add funds.*
Preferred payment method: Tinkoff, +7-900-656-08-59. 
Add your username in the payment comments or contact @trxxxxkov to inform about your fee.

Payment is calculated for each token (OpenAI's tokens pricing for GPT-4-Turbo can be found here: https://openai.com/pricing) and multiplied by ~1.6 as compensation for account top-up fees (20-30%) and taxes (VAT \u2248 19%).
*The coefficient will be decreased if you share a payment method with less fee. Contact @trxxxxkov if you have one!*""",
        "empty": """*Your access is paused because your balance is empty.*
You have to add funds to continue using this bot. 
For more details, type /balance""",
        "draw": """Describe the image you want to get after /draw command, for example:```
/draw The stars tennis-balls, struck and bandied which way please them```""",
        "redraw": "Draw similar images!",
        "tokens": "What are tokens?",
    },
}
