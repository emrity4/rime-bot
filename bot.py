#!/usr/bin/env python3
"""
🤖 QUIZ BOT - Enhanced Version
- Admin-only quiz creation
- Message-based quiz display (each question as new message)
- Multi-quiz CSV import
- Contact system
- Catalog command
"""

import os
import json
import logging
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import asyncio

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

ADMIN_ID = 980838324  # Only this user can create/import quizzes
DATA_FILE = "quiz_data.json"
CONTACT_FILE = "contact_messages.json"

logging.basicConfig(
    format="%(asctime)s - %name)s - %levelname)s - %message)s",
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
        self.user_quiz_messages: Dict[str, List[int]] = {}  # Track message IDs for cleanup
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
    
    def parse_multi_quiz_csv(self, csv_content: str) -> List[Tuple[str, List[Dict]]]:
        """
        Parse CSV that can contain multiple quizzes.
        Format: [QUIZ:Quiz Name], then questions, then empty line or next [QUIZ:...]
        """
        lines = csv_content.strip().split('\n')
        quizzes = []
        current_quiz_name = None
        current_questions = []
        
        for line in lines:
            line = line.strip()
            if not line:
                # Empty line separates quizzes
                if current_quiz_name and current_questions:
                    quizzes.append((current_quiz_name, current_questions))
                    current_quiz_name = None
                    current_questions = []
                continue
            
            # Check for quiz header: [QUIZ:Quiz Name]
            if line.startswith('[QUIZ:') and line.endswith(']'):
                if current_quiz_name and current_questions:
                    quizzes.append((current_quiz_name, current_questions))
                current_quiz_name = line[6:-1].strip()
                current_questions = []
                continue
            
            # Parse as CSV question row
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
                    current_questions.append({
                        'text': question_text,
                        'options': options,
                        'correct': correct
                    })
        
        # Add last quiz
        if current_quiz_name and current_questions:
            quizzes.append((current_quiz_name, current_questions))
        
        return quizzes
    
    def parse_single_csv(self, csv_content: str) -> Tuple[List[Dict], str]:
        """Parse single CSV for backward compatibility"""
        lines = csv_content.strip().split('\n')
        if len(lines) < 2:
            return [], "Not enough data"
        
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
        return f"✅ Quiz '{title}' created with {len(questions)} questions!\n📌 Quiz ID: `{quiz_id}`"
    
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
            'start_time': datetime.now().isoformat(),
            'message_ids': []  # Store message IDs for cleanup
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
            'results': results
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


# ============ CONTACT MESSAGES ============
class ContactManager:
    def __init__(self, contact_file: str):
        self.contact_file = contact_file
        self.messages = []
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.contact_file):
                with open(self.contact_file, 'r') as f:
                    self.messages = json.load(f)
        except Exception as e:
            logger.error(f"Error loading contacts: {e}")
    
    def save(self):
        try:
            with open(self.contact_file, 'w') as f:
                json.dump(self.messages, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving contacts: {e}")
    
    def add_message(self, user_id: int, username: str, message: str):
        msg = {
            'id': len(self.messages) + 1,
            'user_id': user_id,
            'username': username,
            'message': message,
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        self.messages.append(msg)
        self.save()
        return msg
    
    def get_unread(self) -> List[Dict]:
        return [m for m in self.messages if not m.get('read', False)]
    
    def mark_read(self, msg_id: int):
        for m in self.messages:
            if m['id'] == msg_id:
                m['read'] = True
        self.save()


# ============ BOT INSTANCE ============
quiz_manager = QuizManager(DATA_FILE)
contact_manager = ContactManager(CONTACT_FILE)


# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with Rime University intro"""
    user = update.effective_user
    
    intro_text = f"""
🎓 *RIME UNIVERSITY*

Welcome {user.first_name}!

Rime University is a private academic platform for course notes, course quizzes, progress tracking, and feedback. It's built to help students study efficiently, track quiz performance, and receive announcements from the academic team. Access is managed by the platform administrator.

*📋 Available Commands:*

/start - Show this introduction
/help - Detailed help
/catalog - List all available quizzes
/take <quiz_id> - Take a quiz
/stats - View your performance
/contact <message> - Send support message to admin
/cancel - Exit current quiz

* For Admins:*
/new - Create new quiz (CSV upload or paste)
/multinew - Import multiple quizzes at once
/broadcast <message> - Send announcement to all users

* Quick Start:*
Use `/catalog` to see available quizzes, then `/take QUIZ_ID` to start!

Questions or issues? Use `/contact` to reach the admin.
    """
    
    await update.message.reply_text(intro_text, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed help"""
    help_text = """
* Quiz Bot Help*

*Taking a Quiz:*
1. Use `/catalog` to see available quizzes
2. Use `/take QUIZ_ID` to start
3. Each question appears as a new message
4. Click A/B/C/D buttons to answer
5. Get score at the end!

*Creating Quizzes (Admin Only):*
• `/new` - Upload or paste a single quiz CSV
• `/multinew` - Import multiple quizzes at once

*CSV Format:*
`question,optionA,optionB,optionC,optionD,correct`

*Multiple Quiz Format:*
```

[QUIZ:Science Quiz]
question,optionA,optionB,optionC,optionD,correct
...
[QUIZ:History Quiz]
question,optionA,optionB,optionC,optionD,correct

```

*Support:*
Use `/contact Your message here` to send feedback to the admin.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def catalog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available quizzes"""
    quizzes = quiz_manager.list_quizzes()
    
    if not quizzes:
        await update.message.reply_text(
            "📭 *No quizzes available*\n\n"
            "Check back later or contact the administrator.",
            parse_mode='Markdown'
        )
        return
    
    text = "*📚 Available Quizzes:*\n\n"
    for q in quizzes:
        text += f"• *{q['title']}*\n  `ID: {q['id']}` | {q['total_questions']} questions\n\n"
    
    text += "Use `/take QUIZ_ID` to start a quiz."
    await update.message.reply_text(text, parse_mode='Markdown')


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user contact messages"""
    user = update.effective_user
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "📧 *How to contact admin*\n\n"
            "Use: `/contact Your message here`\n\n"
            "Example: `/contact I need help with quiz timing`",
            parse_mode='Markdown'
        )
        return
    
    message = ' '.join(args)
    
    # Save message
    contact_manager.add_message(user.id, user.username or user.first_name, message)
    
    # Forward to admin
    try:
        admin_text = f"""
📨 *New Contact Message*

*From:* {user.first_name} (@{user.username or 'No username'})
*User ID:* `{user.id}`
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*Message:*
{message}

Reply directly to this user via DM.
        """
        await context.bot.send_message(ADMIN_ID, admin_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Could not forward to admin: {e}")
    
    await update.message.reply_text(
        "✅ *Message sent!*\n\n"
        "The administrator has been notified and will respond shortly.\n"
        "Thank you for reaching out.",
        parse_mode='Markdown'
    )


async def new_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: Create new quiz from CSV"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Only the platform administrator can create quizzes.")
        return
    
    await update.message.reply_text(
        "📤 *Create a New Quiz (Admin)*\n\n"
        "Send me a CSV file with your questions OR paste CSV text.\n\n"
        "Format: `question,optionA,optionB,optionC,optionD,correct`\n\n"
        "Example:\n"
        "`What is 2+2?,3,4,5,6,B`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_csv'] = True
    context.user_data['multi_quiz_mode'] = False


async def multinew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: Import multiple quizzes at once"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Only the platform administrator can create quizzes.")
        return
    
    await update.message.reply_text(
        "📚 *Import Multiple Quizzes (Admin)*\n\n"
        "Send me a CSV file with multiple quizzes.\n\n"
        "*Format:*\n"
        "```\n[QUIZ:Quiz Name 1]\nquestion,optionA,optionB,optionC,optionD,correct\nquestion,optionA,optionB,optionC,optionD,correct\n\n[QUIZ:Quiz Name 2]\nquestion,optionA,optionB,optionC,optionD,correct\n```\n\n"
        "Separate quizzes with an empty line.",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_csv'] = True
    context.user_data['multi_quiz_mode'] = True


async def handle_csv_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle CSV file upload or paste"""
    if not context.user_data.get('awaiting_csv'):
        return
    
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can import quizzes.")
        context.user_data.clear()
        return
    
    # Get CSV content
    csv_text = ""
    if update.message.document:
        file = await update.message.document.get_file()
        csv_content = await file.download_as_bytearray()
        csv_text = csv_content.decode('utf-8')
    elif update.message.text:
        csv_text = update.message.text
    else:
        await update.message.reply_text("❌ Please send a CSV file or paste CSV text.")
        return
    
    multi_mode = context.user_data.get('multi_quiz_mode', False)
    
    if multi_mode:
        # Parse multiple quizzes
        quizzes = quiz_manager.parse_multi_quiz_csv(csv_text)
        
        if not quizzes:
            await update.message.reply_text("❌ No valid quizzes found in the file.")
            context.user_data.clear()
            return
        
        created = []
        failed = []
        
        for quiz_name, questions in quizzes:
            if not questions:
                failed.append(quiz_name)
                continue
            
            quiz_id = hashlib.md5(f"{quiz_name}{time.time()}{len(created)}".encode()).hexdigest()[:8]
            result = quiz_manager.create_quiz(quiz_id, quiz_name, questions)
            created.append(f"• *{quiz_name}* → `{quiz_id}` ({len(questions)} questions)")
        
        response = f"✅ *Imported {len(created)} quizzes!*\n\n"
        if created:
            response += "\n".join(created)
        if failed:
            response += f"\n\n⚠️ Failed: {', '.join(failed)}"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        # Parse single quiz
        questions, msg = quiz_manager.parse_single_csv(csv_text)
        
        if not questions:
            await update.message.reply_text(f"❌ {msg}")
            context.user_data.clear()
            return
        
        context.user_data['temp_questions'] = questions
        context.user_data['awaiting_quiz_name'] = True
        
        await update.message.reply_text(
            f"{msg}\n\n📝 *What should we name this quiz?*\nSend me a name.",
            parse_mode='Markdown'
        )
    
    context.user_data.clear()


async def handle_quiz_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz name input"""
    if not context.user_data.get('awaiting_quiz_name'):
        return
    
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    quiz_name = update.message.text.strip()
    questions = context.user_data.get('temp_questions')
    
    if not questions:
        await update.message.reply_text("❌ No questions found.")
        context.user_data.clear()
        return
    
    quiz_id = hashlib.md5(f"{quiz_name}{time.time()}".encode()).hexdigest()[:8]
    result = quiz_manager.create_quiz(quiz_id, quiz_name, questions)
    
    context.user_data.clear()
    
    await update.message.reply_text(result, parse_mode='Markdown')


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: Broadcast message to all users"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can broadcast messages.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "📢 *Broadcast*\n\n"
            "Usage: `/broadcast Your message here`\n\n"
            "This will send your message to all users who have taken quizzes.",
            parse_mode='Markdown'
        )
        return
    
    message = ' '.join(args)
    
    # Get all unique users from stats
    all_users = list(quiz_manager.user_stats.keys())
    
    if not all_users:
        await update.message.reply_text("No users to broadcast to yet.")
        return
    
    sent = 0
    failed = 0
    
    broadcast_text = f"""
📢 *ANNOUNCEMENT FROM ADMIN*

{message}

---
*Rime University*
_You received this because you've used the quiz bot._
    """
    
    for uid in all_users:
        try:
            await context.bot.send_message(int(uid), broadcast_text, parse_mode='Markdown')
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send to {uid}: {e}")
            failed += 1
        await asyncio.sleep(0.05)  # Rate limiting
    
    await update.message.reply_text(
        f"✅ *Broadcast complete!*\n\n"
        f"Sent: {sent}\n"
        f"Failed: {failed}",
        parse_mode='Markdown'
    )


async def take_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a quiz - each question as new message"""
    user_id = str(update.effective_user.id)
    
    if user_id in quiz_manager.user_sessions:
        await update.message.reply_text(
            "⚠️ You have an active quiz! Use `/cancel` first."
        )
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Usage: `/take QUIZ_ID`\nUse `/catalog` to see available quizzes.",
            parse_mode='Markdown'
        )
        return
    
    quiz_id = args[0]
    quiz = quiz_manager.get_quiz(quiz_id)
    
    if not quiz:
        await update.message.reply_text(f"❌ Quiz '{quiz_id}' not found.")
        return
    
    session = quiz_manager.start_session(user_id, quiz_id)
    
    await update.message.reply_text(
        f"🎯 *{quiz['title']}*\n"
        f"Total Questions: {len(quiz['questions'])}\n\n"
        f"Each question will appear as a new message.\n"
        f"Type `/cancel` to quit anytime.",
        parse_mode='Markdown'
    )
    
    # Send first question
    await send_question_message(update, context, user_id)


async def send_question_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    """Send current question as a new message"""
    question_data = quiz_manager.get_current_question(user_id)
    
    if not question_data:
        return
    
    keyboard = []
    options = question_data['options']
    for letter, text in options.items():
        keyboard.append([InlineKeyboardButton(
            f"{letter}. {text[:60]}",
            callback_data=f"ans_{user_id}_{letter}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    question_text = (
        f"📋 *Question {question_data['index']}/{question_data['total']}*\n\n"
        f"{question_data['text']}"
    )
    
    sent_msg = await update.message.reply_text(
        question_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    # Store message ID for potential cleanup
    session = quiz_manager.user_sessions.get(user_id)
    if session:
        if 'message_ids' not in session:
            session['message_ids'] = []
        session['message_ids'].append(sent_msg.message_id)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's answer"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith('ans_'):
        return
    
    parts = data.split('_')
    if len(parts) != 3:
        return
    
    user_id = parts[1]
    answer = parts[2]
    
    # Record answer
    has_next, session = quiz_manager.answer_question(user_id, answer)
    
    if has_next:
        # Send next question as new message
        question_data = quiz_manager.get_current_question(user_id)
        if question_data:
            keyboard = []
            for letter, text in question_data['options'].items():
                keyboard.append([InlineKeyboardButton(
                    f"{letter}. {text[:60]}",
                    callback_data=f"ans_{user_id}_{letter}"
                )])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            question_text = (
                f"📋 *Question {question_data['index']}/{question_data['total']}*\n\n"
                f"{question_data['text']}"
            )
            
            await query.message.reply_text(
                question_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            # Delete the old message with buttons (optional cleanup)
            try:
                await query.message.delete()
            except:
                pass
    else:
        # Quiz completed
        if session:
            score = quiz_manager.calculate_score(session)
            quiz_manager.save_session_result(user_id, session, score)
            quiz_manager.end_session(user_id)
            
            result_text = (
                f"🎉 *Quiz Completed!*\n\n"
                f"📊 *Score: {score['correct']}/{score['total']}*\n"
                f"📈 *Percentage: {score['percentage']:.1f}%*\n"
                f"{'✅ PASSED!' if score['passed'] else '❌ FAILED'}\n\n"
            )
            
            wrong = [r for r in score['results'] if not r['is_correct']]
            if wrong:
                result_text += f"*Mistakes ({len(wrong)}):*\n"
                for w in wrong[:5]:
                    result_text += f"• {w['question'][:50]}...\n"
                if len(wrong) > 5:
                    result_text += f"... and {len(wrong) - 5} more.\n"
            
            result_text += "\nUse `/catalog` to take another quiz!"
            
            await query.message.reply_text(result_text, parse_mode='Markdown')
            
            # Delete the last question message
            try:
                await query.message.delete()
            except:
                pass
        else:
            await query.message.reply_text("❌ Error completing quiz.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel active quiz session"""
    user_id = str(update.effective_user.id)
    
    if user_id in quiz_manager.user_sessions:
        quiz_manager.end_session(user_id)
        await update.message.reply_text("❌ Quiz cancelled. Use `/catalog` to start a new one.")
    else:
        await update.message.reply_text("ℹ️ You don't have an active quiz session.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user_id = str(update.effective_user.id)
    stats = quiz_manager.get_user_stats(user_id)
    
    if not stats or stats['quizzes_taken'] == 0:
        await update.message.reply_text(
            "📊 *Your Statistics*\n\n"
            "No quizzes taken yet!\n"
            "Use `/catalog` to take your first quiz.",
            parse_mode='Markdown'
        )
        return
    
    avg = (stats['total_correct'] / stats['total_questions']) * 100 if stats['total_questions'] > 0 else 0
    
    text = (
        f"📊 *Your Statistics*\n\n"
        f"📝 Quizzes Taken: {stats['quizzes_taken']}\n"
        f"✅ Total Correct: {stats['total_correct']}\n"
        f"📋 Total Questions: {stats['total_questions']}\n"
        f"📈 Average Score: {avg:.1f}%\n\n"
        f"*Recent Activity:*\n"
    )
    
    for entry in stats['history'][-5:][::-1]:
        date = datetime.fromisoformat(entry['date']).strftime('%Y-%m-%d')
        status = "✅" if entry['passed'] else "❌"
        text += f"{status} {entry['quiz_title'][:25]} - {entry['score']}/{entry['total']} ({entry['percentage']:.0f}%)\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    if context.user_data.get('awaiting_quiz_name'):
        await handle_quiz_name(update, context)
    elif context.user_data.get('awaiting_csv'):
        await handle_csv_document(update, context)


# ============ MAIN ============
def main():
    """Start the bot"""
    application = Application.builder().token(TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("catalog", catalog_command))
    application.add_handler(CommandHandler("take", take_quiz_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("contact", contact_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Admin commands
    application.add_handler(CommandHandler("new", new_quiz_command))
    application.add_handler(CommandHandler("multinew", multinew_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    # Handlers
    application.add_handler(MessageHandler(filters.Document.ALL, handle_csv_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_answer))
    
    logger.info("🤖 Quiz Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
