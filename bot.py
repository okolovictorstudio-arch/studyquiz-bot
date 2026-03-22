import os
import json
from dotenv import load_dotenv
from google import genai
import fitz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

client = genai.Client(api_key=GEMINI_API_KEY)

user_quizzes = {}

def extract_text_from_pdf(file_path):
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text[:15000]

async def generate_quiz(text):
    prompt = f"""
You are a quiz generator. Read the following notes and generate exactly 10 multiple choice questions.

Rules:
- Each question must have exactly 4 options labeled A, B, C, D
- Only one option is correct
- Return ONLY valid JSON, no extra text, no markdown, no code blocks
- Use this exact format:

[
  {{
    "question": "Question text here?",
    "options": {{
      "A": "First option",
      "B": "Second option",
      "C": "Third option",
      "D": "Fourth option"
    }},
    "answer": "A",
    "explanation": "Brief explanation of why this is correct"
  }}
]

Notes:
{text}
"""
    response = client.models.generate_content(
        model="gemini-1.5-flash-latest",
        contents=prompt
    )
    raw = response.text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    questions = json.loads(raw)
    return questions

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *StudyQuiz Bot*!\n\n"
        "I turn your notes into quizzes so you can study smarter.\n\n"
        "📄 *How to use:*\n"
        "1. Send me a PDF or paste your notes as text\n"
        "2. I'll generate 10 quiz questions\n"
        "3. Answer each question\n"
        "4. Get your score and explanations\n\n"
        "Send your notes to get started! 🚀",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *StudyQuiz Help*\n\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/cancel - Cancel current quiz\n\n"
        "Just send a PDF or text and I'll handle the rest!",
        parse_mode="Markdown"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_quizzes:
        del user_quizzes[user_id]
    await update.message.reply_text(
        "Quiz cancelled. Send new notes whenever you're ready! 📚"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if text.startswith("/"):
        return

    if len(text) < 30:
        await update.message.reply_text(
            "⚠️ Your notes seem too short. Please send more detailed notes for better questions!"
        )
        return

    await update.message.reply_text("⚡ Generating your quiz, please wait...")

    try:
        questions = await generate_quiz(text)
        user_quizzes[user_id] = {
            "questions": questions,
            "current": 0,
            "score": 0,
            "wrong": []
        }
        await send_question(update, context, user_id)
    except Exception as e:
        print(f"Error generating quiz: {e}")
        await update.message.reply_text(
            "❌ Something went wrong generating your quiz. Please try again!"
        )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text("📄 Reading your PDF, please wait...")

    file = await update.message.document.get_file()
    file_path = f"temp_{user_id}.pdf"
    await file.download_to_drive(file_path)

    try:
        text = extract_text_from_pdf(file_path)
        os.remove(file_path)

        if len(text) < 100:
            await update.message.reply_text(
                "⚠️ Couldn't extract enough text from this PDF. Try a text-based PDF or paste your notes directly."
            )
            return

        await update.message.reply_text("⚡ Generating your quiz, please wait...")
        questions = await generate_quiz(text)
        user_quizzes[user_id] = {
            "questions": questions,
            "current": 0,
            "score": 0,
            "wrong": []
        }
        await send_question(update, context, user_id)

    except Exception as e:
        print(f"Error handling PDF: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        await update.message.reply_text(
            "❌ Something went wrong reading your PDF. Please try again!"
        )

async def send_question(update, context, user_id):
    quiz = user_quizzes[user_id]
    current = quiz["current"]
    question = quiz["questions"][current]
    total = len(quiz["questions"])

    text = (
        f"📝 *Question {current + 1} of {total}*\n\n"
        f"{question['question']}\n\n"
        f"🅐 {question['options']['A']}\n"
        f"🅑 {question['options']['B']}\n"
        f"🅒 {question['options']['C']}\n"
        f"🅓 {question['options']['D']}"
    )

    keyboard = [
        [
            InlineKeyboardButton("A", callback_data="answer_A"),
            InlineKeyboardButton("B", callback_data="answer_B"),
            InlineKeyboardButton("C", callback_data="answer_C"),
            InlineKeyboardButton("D", callback_data="answer_D"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.callback_query.message.reply_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in user_quizzes:
        await query.message.reply_text(
            "No active quiz. Send your notes to start!"
        )
        return

    quiz = user_quizzes[user_id]
    current = quiz["current"]
    question = quiz["questions"][current]
    selected = query.data.replace("answer_", "")
    correct = question["answer"]
    total = len(quiz["questions"])

    if selected == correct:
        quiz["score"] += 1
        feedback = f"✅ *Correct!*\n\n💡 {question['explanation']}"
    else:
        quiz["wrong"].append(current + 1)
        feedback = (
            f"❌ *Wrong!* The correct answer is *{correct}*\n\n"
            f"💡 {question['explanation']}"
        )

    await query.message.reply_text(feedback, parse_mode="Markdown")
    quiz["current"] += 1

    if quiz["current"] >= total:
        await show_results(query, user_id)
    else:
        await send_question(update, context, user_id)

async def show_results(query, user_id):
    quiz = user_quizzes[user_id]
    score = quiz["score"]
    total = len(quiz["questions"])
    wrong = quiz["wrong"]
    percentage = int((score / total) * 100)

    if percentage >= 80:
        emoji = "🏆"
        message = "Excellent work!"
    elif percentage >= 60:
        emoji = "👏"
        message = "Good job! Keep studying!"
    elif percentage >= 40:
        emoji = "📚"
        message = "Keep practicing, you'll get there!"
    else:
        emoji = "💪"
        message = "Don't give up! Review your notes and try again!"

    result_text = (
        f"{emoji} *Quiz Complete!*\n\n"
        f"Score: *{score}/{total}* ({percentage}%)\n"
        f"{message}\n\n"
    )

    if wrong:
        result_text += f"❌ Questions you missed: {', '.join(map(str, wrong))}\n\n"

    result_text += "📄 Send new notes to start another quiz!"

    del user_quizzes[user_id]
    await query.message.reply_text(result_text, parse_mode="Markdown")

def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^answer_"))

    print("🤖 StudyQuiz Bot is running...")

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=8080,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="webhook",
            drop_pending_updates=True
        )
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
