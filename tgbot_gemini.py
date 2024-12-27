import logging
import google.generativeai as genai
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
import re
from io import BytesIO

# API 密钥和 Bot Token
GOOGLE_API_KEY = "YOUR GOOGLE_API_KEY"
TELEGRAM_BOT_TOKEN = "YOUR TELEGRAM_BOT_TOKEN"

# 设置 Gemini API
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# 设置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


# Markdown 转换
def telegram_markdown(text):
    # 粗体
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # 斜体
    text = re.sub(r'\*(.*?)\*', r'_\1_', text)
    # . - ( ) # > <
    text = re.sub(r'([!@#$%^&()+\-=\[\]{};\':"\\|,.<>?~])', r'\\\1', text)
    return text


# 处理 /start 命令
async def start(update: Update, context: CallbackContext):
    user_question = " ".join(context.args)
    logging.info(f"received message: /start {user_question} {update.effective_chat} {update.effective_user}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="你好! 发送 /ge [你的问题] 来使用 Gemini。",
                                   reply_to_message_id=update.message.message_id)


# 处理 /ge 命令
async def gemini(update: Update, context: CallbackContext):
    try:
        user_question = " ".join(context.args)
        if not user_question:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text="请输入你的问题。例如： `/ge 宇宙的奥秘是什么`", parse_mode="MarkdownV2",
                                           reply_to_message_id=update.message.message_id)
            return

        await send_gemini_response(update, context, user_question)


    except Exception as e:
        logging.error(f"error: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="发生错误, 请稍后再试",
                                       reply_to_message_id=update.message.message_id)


async def send_gemini_response(update: Update, context: CallbackContext, user_question):
    logging.info(f"received message: {user_question} from: {update.effective_chat} {update.effective_user}")
    if 'chat_history' not in context.chat_data:
        context.chat_data['chat_history'] = model.start_chat()
        logging.info(f"no history chat, start new chat")
    elif not update.message.reply_to_message:
        context.chat_data['chat_history'] = model.start_chat()
        logging.info(f"not reply, start new chat")
    else:
        logging.info(f"reply from: {update.message.reply_to_message.text}")

    chat = context.chat_data['chat_history']
    chat_id = update.effective_chat.id
    try:
        response = chat.send_message(user_question)
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
        if "SAFETY" in str(e) or "content_filter" in str(e):
            await context.bot.send_message(chat_id=chat_id, text="由于安全原因，无法生成回复，请尝试修改提问或更换问题",
                                           reply_to_message_id=update.message.message_id)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="生成回复时发生错误, 请再试一次看看",
                                           reply_to_message_id=update.message.message_id)
        return
    # 发送文本
    response_text = response.text
    if response_text:
        logging.info(f"received response text：{response_text}")
        try:
            formatted_text = telegram_markdown(response_text)
            sent_message = await context.bot.send_message(chat_id=chat_id, text=formatted_text,
                                                          parse_mode="MarkdownV2",
                                                          reply_to_message_id=update.message.message_id)
            context.chat_data['last_message_id'] = sent_message.message_id
            logging.info(f"reply md converted text：{formatted_text}")
        except Exception as e:
            logging.error(f"md conversion error, change to original text \n error info：{e}")
            sent_message = await context.bot.send_message(chat_id=chat_id, text=response_text,
                                                          reply_to_message_id=update.message.message_id)
            context.chat_data['last_message_id'] = sent_message.message_id

    # 发送图片（模型暂不支持）
    media_group = []
    for part in response.parts:
        if hasattr(part, 'blob') and part.blob is not None:
            if part.mime_type and part.mime_type.startswith("image/"):
                media_group.append(InputMediaPhoto(media=BytesIO(part.blob.data)))
    if media_group:
        if len(media_group) == 1:
            sent_message = await context.bot.send_photo(chat_id=chat_id,
                                                        photo=media_group[0].media,
                                                        reply_to_message_id=update.message.message_id)
        else:
            sent_message = await context.bot.send_media_group(chat_id=chat_id,
                                                              media=media_group,
                                                              reply_to_message_id=update.message.message_id)
        context.chat_data['last_message_id'] = sent_message[0].message_id if isinstance(sent_message,
                                                                                        list) else sent_message.message_id


# 处理其他消息 (用于连续对话)
async def echo(update: Update, context: CallbackContext):
    if update.message.reply_to_message and 'last_message_id' in context.chat_data and update.message.reply_to_message.message_id == \
            context.chat_data['last_message_id']:
        user_question = update.message.text
        await send_gemini_response(update, context, user_question)
    else:
        user_question = update.message.text
        logging.info(f"received message: {user_question} from: {update.effective_chat} {update.effective_user}")
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text="请发送 /ge [你的问题] 来使用 Gemini。",
                                       reply_to_message_id=update.message.message_id)


# 主函数
if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 添加命令处理器
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('ge', gemini))

    # 添加消息处理器 (用于处理其他文本)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

    # 启动 bot
    application.run_polling()
