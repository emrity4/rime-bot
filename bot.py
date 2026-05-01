#!/usr/bin/env python3
"""
🤖 QUIZ BOT - Telegram Bot for CSV-based Quiz Generation
Deploy on Railway via GitHub
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import io

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ============ CONFIGURATION ============
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

DATA_FILE = "quiz_data.json"
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============ DATA MANAGEMENT ============
class QuizManager:
    """Manages quiz data and user sessions"""
    
    def __init__(self, data_file: str):
        self.data_file = data_file
        self.quizzes: Dict[str, Dict] = {}
        self.user_sessions: Dict[str, Dict] = {}
        self.user_stats: Dict[str, Dict] = {}
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.quizzes = data.get('quizzes', {})
                    self.user_stats = data.get('user_stats', {})
                    logger.info(f"Loaded {len(self.quizzes)} quizzes")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump({
                    'quizzes': self.quizzes,
                    'user_stats': self.user_stats
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def parse_csv(self, csv_content: str) -> Tuple[List[Dict], str]:
        """Parse CSV content into questions list"""
        lines = csv_content.strip().split('\n')
        if len(lines) < 2:
            return [], "Not enough data (need header + at least 1 question)"
        
        questions = []
        errors = []
        
        for i, line in enumerate(lines[1:], start=1):
            if not line.strip():
                continue
            
            parts = []
            current = ''
            in_quotes = False
            
            for char in line:
                if char == '"':
                    in_quotes = not in_quotes
                elif char == ',' and not in_quotes:
                    parts.append(current.strip())
                    current = ''
                else:
                    current += char
            parts.append(current.strip())
            parts = [p.strip('"') for p in parts]
            
            if len(parts) >= 6:
                question_text = parts[0]
                options = {
                    'A': parts[1] if len(parts) > 1 else '',
                    'B': parts[2] if len(parts) > 2 else '',
                    'C': parts[3] if len(parts) > 3 else '',
                    'D': parts[4] if len(parts) > 4 else ''
                }
                correct = parts[5].upper()
                
                if correct in ['A', 'B', 'C', 'D'] and all(options.values()):
                    questions.append({
                        'text': question_text,
                        'options': options,
                        'correct': correct
                    })
                else:
                    errors.append(f"Line {i}: Invalid format")
            else:
                errors.append(f"Line {i}: Not enough columns")
        
        if not questions:
            return [], "No valid questions found.\n" + "\n".join(errors[:3])
        
        msg = f"✅ Loaded {len(questions)} questions"
        if errors:
            msg += f"\n⚠️ Skipped {len(errors)} invalid rows"
        
        return questions, msg
    
    def create_quiz(self, quiz_id: str, title: str, questions: List[Dict]) -> str:
        """Create a new quiz"""
        self.quizzes[quiz_id] = {
            'id': quiz_id,
            'title': title,
            'questions': questions,
            'created_at': datetime.now().isoformat(),
            'total_questions': len(questions)
        }
        self.save_data()
        return f"✅ Quiz '{title}' created with {len(questions)} questions!"
    
    def get_quiz(self, quiz_id: str) -> Optional[Dict]:
        return self.quizzes.get(quiz_id)
    
    def list_quizzes(self) -> List[Dict]:
        return list(self.quizzes.values())
    
    def start_session(self, user_id: str, quiz_id: str) -> Optional[Dict]:
        quiz = self.quizzes.get(quiz_id)
        if not quiz:
            return None
        
        session = {
            'quiz_id': quiz_id,
            'quiz_title': quiz['title'],
            'questions': quiz['questions'],
            'current_index': 0,
            'answers': {},
            'start_time': datetime.now().isoformat()
        }
        self.user_sessions[user_id] = session
        return session
    
    def answer_question(self, user_id: str, answer: str) -> Tuple[bool, Optional[Dict]]:
        session = self.user_sessions.get(user_id)
        if not session:
            return False, None
        
        current_idx = session['current_index']
        session['answers'][str(current_idx)] = answer
        
        if current_idx + 1 < len(session['questions']):
            session['current_index'] += 1
            return True, session
        else:
            return False, session
    
    def get_current_question(self, user_id: str) -> Optional[Dict]:
        session = self.user_sessions.get(user_id)
        if not session:
            return None
        
        idx = session['current_index']
        if idx < len(session['questions']):
            q = session['questions'][idx]
            return {
                'index': idx + 1,
                'total': len(session['questions']),
                'text': q['text'],
                'options': q['options'],
                'question_data': q
            }
        return None
    
    def calculate_score(self, session: Dict) -> Dict:
        questions = session['questions']
        answers = session['answers']
        
        correct = 0
        results = []
        
        for i, q in enumerate(questions):
            user_answer = answers.get(str(i))
            is_correct = (user_answer == q['correct'])
            if is_correct:
                correct += 1
            results.append({
                'question': q['text'],
                'user_answer': user_answer,
                'correct_answer': q['correct'],
                'correct_option_text': q['options'][q['correct']],
                'is_correct': is_correct
            })
        
        total = len(questions)
        percentage = (correct / total) * 100 if total > 0 else 0
        
        return {
            'correct': correct,
            'total': total,
            'percentage': percentage,
            'passed': percentage >= 60,
            'results': results,
            'start_time': session['start_time']
        }
    
    def save_session_result(self, user_id: str, session: Dict, score: Dict):
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                'quizzes_taken': 0,
                'total_correct': 0,
                'total_questions': 0,
                'history': []
            }
        
        stats = self.user_stats[user_id]
        stats['quizzes_taken'] += 1
        stats['total_correct'] += score['correct']
        stats['total_questions'] += score['total']
        stats['history'].append({
            'quiz_title': session['quiz_title'],
            'score': score['correct'],
            'total': score['total'],
            'percentage': score['percentage'],
            'passed': score['passed'],
            'date': datetime.now().isoformat()
        })
        
        if len(stats['history']) > 20:
            stats['history'] = stats['history'][-20:]
        
        self.save_data()
    
    def end_session(self, user_id: str):
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
    
    def get_user_stats(self, user_id: str) -> Optional[Dict]:
        return self.user_stats.get(user_id)


# ============ BOT HANDLERS ============
quiz_manager = QuizManager(DATA_FILE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🤖 *Quiz Bot*\n\nWelcome {user.first_name}!\n\n"
        f"📋 *Commands:*\n"
        f"/start - This message\n"
        f"/new - Create a quiz from CSV\n"
        f"/list - Show available quizzes\n"
        f"/take <id> - Take a quiz\n"
        f"/stats - Your performance\n"
        f"/cancel - Exit current quiz\n\n"
        f"📊 *CSV Format:*\n"
        f"`question,optionA,optionB,optionC,optionD,correct`\n\n"
        f"Example:\n"
        f"`What is 2+2?,3,4,5,6,B`",
        parse_mode='Markdown'
    )


async def new_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 *Create a Quiz*\n\n"
        "Send me a CSV file with your questions.\n\n"
        "Format: `question,optionA,optionB,optionC,optionD,correct`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_csv'] = True


async def handle_csv_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_csv'):
        return
    
    document = update.message.document
    if not document.file_name.endswith('.csv'):
        await update.message.reply_text("❌ Please send a valid CSV file.")
        return
    
    file = await document.get_file()
    csv_content = await file.download_as_bytearray()
    csv_text = csv_content.decode('utf-8')
    
    questions, msg = quiz_manager.parse_csv(csv_text)
    
    if not questions:
        await update.message.reply_text(f"❌ {msg}")
        return
    
    context.user_data['temp_questions'] = questions
    context.user_data['awaiting_quiz_name'] = True
    
    await update.message.reply_text(
        f"{msg}\n\n📝 *What should we name this quiz?*\nSend me a name.",
        parse_mode='Markdown'
    )


async def handle_quiz_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_quiz_name'):
        return
    
    quiz_name = update.message.text.strip()
    questions = context.user_data.get('temp_questions')
    
    if not questions:
        await update.message.reply_text("❌ No questions found.")
        context.user_data.clear()
        return
    
    import hashlib
    import time
    quiz_id = hashlib.md5(f"{quiz_name}{time.time()}".encode()).hexdigest()[:8]
    
    result = quiz_manager.create_quiz(quiz_id, quiz_name, questions)
    
    context.user_data.clear()
    
    await update.message.reply_text(
        f"{result}\n\n📌 *Quiz ID:* `{quiz_id}`\n\n"
        f"Use `/take {quiz_id}` to start.",
        parse_mode='Markdown'
    )


async def list_quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = quiz_manager.list_quizzes()
    
    if not quizzes:
        await update.message.reply_text(
            "📭 *No quizzes available*\n\nCreate one with `/new`",
            parse_mode='Markdown'
        )
        return
    
    text = "*📚 Available Quizzes:*\n\n"
    for q in quizzes[:10]:
        text += f"• *{q['title']}*\n  `ID: {q['id']}` | {q['total_questions']} questions\n\n"
    
    text += "Use `/take QUIZ_ID` to start."
    await update.message.reply_text(text, parse_mode='Markdown')


async def take_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id in quiz_manager.user_sessions:
        await update.message.reply_text(
            "⚠️ You have an active quiz! Use `/cancel` first."
        )
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Usage: `/take QUIZ_ID`\nUse `/list` to see available quizzes.",
            parse_mode='Markdown'
        )
        return
    
    quiz_id = args[0]
    quiz = quiz_manager.get_quiz(quiz_id)
    
    if not quiz:
        await update.message.reply_text(f"❌ Quiz '{quiz_id}' not found.")
        return
    
    quiz_manager.start_session(user_id, quiz_id)
    
    await update.message.reply_text(
        f"🎯 *Quiz: {quiz['title']}*\n"
        f"Questions: {len(quiz['questions'])}\n\nLet's begin!",
        parse_mode='Markdown'
    )
    
    await send_question(update, context, user_id)


async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    question_data = quiz_manager.get_current_question(user_id)
    
    if not question_data:
        return
    
    keyboard = []
    for letter, text in question_data['options'].items():
        keyboard.append([InlineKeyboardButton(
            f"{letter}. {text[:50]}",
            callback_data=f"ans_{letter}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    question_text = (
        f"📋 *Q{question_data['index']}/{question_data['total']}*\n\n"
        f"{question_data['text']}"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            question_text, parse_mode='Markdown', reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            question_text, parse_mode='Markdown', reply_markup=reply_markup
        )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    data = query.data
    
    if data.startswith('ans_'):
        answer = data[4:]
        has_next, session = quiz_manager.answer_question(user_id, answer)
        
        if has_next:
            question_data = quiz_manager.get_current_question(user_id)
            if question_data:
                keyboard = []
                for letter, text in question_data['options'].items():
                    keyboard.append([InlineKeyboardButton(
                        f"{letter}. {text[:50]}",
                        callback_data=f"ans_{letter}"
                    )])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"📋 *Q{question_data['index']}/{question_data['total']}*\n\n"
                    f"{question_data['text']}",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        else:
            if session:
                score = quiz_manager.calculate_score(session)
                quiz_manager.save_session_result(user_id, session, score)
                quiz_manager.end_session(user_id)
                
                result_text = (
                    f"🎉 *Quiz Completed!*\n\n"
                    f"📊 *Score: {score['correct']}/{score['total']}*\n"
                    f"📈 *Percentage: {score['percentage']:.1f}%*\n"
                    f"{'✅ PASSED!' if score['passed'] else '❌ FAILED'}\n"
                )
                
                wrong = [r for r in score['results'] if not r['is_correct']]
                if wrong:
                    result_text += f"\n*Mistakes ({len(wrong)}):*\n"
                    for w in wrong[:3]:
                        result_text += f"• {w['question'][:50]}...\n"
                
                await query.edit_message_text(result_text, parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ Error completing quiz.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if user_id in quiz_manager.user_sessions:
        quiz_manager.end_session(user_id)
        await update.message.reply_text("❌ Quiz cancelled.")
    else:
        await update.message.reply_text("ℹ️ No active quiz session.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stats = quiz_manager.get_user_stats(user_id)
    
    if not stats or stats['quizzes_taken'] == 0:
        await update.message.reply_text(
            "📊 *Your Stats*\n\nNo quizzes taken yet!",
            parse_mode='Markdown'
        )
        return
    
    avg = (stats['total_correct'] / stats['total_questions']) * 100 if stats['total_questions'] > 0 else 0
    
    text = (
        f"📊 *Your Stats*\n\n"
        f"Quizzes: {stats['quizzes_taken']}\n"
        f"Correct: {stats['total_correct']}/{stats['total_questions']}\n"
        f"Average: {avg:.1f}%\n\n"
        f"*Recent:*\n"
    )
    
    for entry in stats['history'][-5:][::-1]:
        date = datetime.fromisoformat(entry['date']).strftime('%Y-%m-%d')
        status = "✅" if entry['passed'] else "❌"
        text += f"{status} {entry['quiz_title'][:20]} - {entry['score']}/{entry['total']}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_quiz_name'):
        await handle_quiz_name(update, context)
    elif context.user_data.get('awaiting_csv'):
        await update.message.reply_text("📤 Please send a CSV file.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


# ============ MAIN ============
def main():
    """Start the bot"""
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new", new_quiz_command))
    application.add_handler(CommandHandler("list", list_quizzes_command))
    application.add_handler(CommandHandler("take", take_quiz_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(MessageHandler(filters.Document.ALL, handle_csv_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_answer))
    
    application.add_error_handler(error_handler)
    
    # Use polling (works great on Railway)
    logger.info("🤖 Quiz Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
