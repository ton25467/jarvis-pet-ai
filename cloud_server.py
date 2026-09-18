import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import google.generativeai as genai
from gtts import gTTS
import requests
import json
import threading
import logging
from dotenv import load_dotenv
import urllib.parse

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    filename='server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logging.warning("GEMINI_API_KEY is not set in Environment Variables!")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.8-flash')

DB_FILE = 'pet_memory.db'

# --- DATABASE FUNCTIONS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    role TEXT,
                    content TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                 )''')
    # Use SQLite as a thread-safe Queue instead of global list
    c.execute('''CREATE TABLE IF NOT EXISTS command_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT
                 )''')
    conn.commit()
    conn.close()

def save_memory(role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO memory (timestamp, role, content) VALUES (?, ?, ?)", 
              (datetime.now().isoformat(), role, content))
    conn.commit()
    conn.close()

def get_history(limit=5):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content FROM memory ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def get_states():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT key, value FROM state")
    rows = c.fetchall()
    conn.close()
    return {k: v for k, v in rows}

def enqueue_response(payload):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO command_queue (payload) VALUES (?)", (json.dumps(payload),))
    conn.commit()
    conn.close()

def dequeue_response():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, payload FROM command_queue ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM command_queue WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return json.loads(row[1])
    conn.close()
    return None

# --- TOOL FUNCTIONS ---
WEATHER_API_KEY = "ca3dc2dd9ad642389c062138260409"

def translate_weather_condition(text):
    t = text.lower()
    if "sunny" in t: return "แดดจัด ท้องฟ้าแจ่มใส"
    if "clear" in t: return "ท้องฟ้าโปร่ง"
    if "partly cloudy" in t: return "มีเมฆบางส่วน"
    if "cloudy" in t or "overcast" in t: return "มีเมฆมาก ท้องฟ้าครึ้ม"
    if "thunder" in t: return "มีพายุฝนฟ้าคะนอง"
    if "heavy rain" in t: return "มีฝนตกหนัก"
    if "moderate rain" in t: return "มีฝนตกปานกลาง"
    if "light rain" in t or "patchy rain" in t or "drizzle" in t or "shower" in t: return "มีฝนตกเล็กน้อยบางพื้นที่"
    if "rain" in t: return "มีฝนตก"
    if "mist" in t or "fog" in t or "haze" in t: return "มีหมอกบาง"
    return text

def get_weather_report():
    try:
        url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q=Bangkok&days=1"
        response = requests.get(url, timeout=5)
        data = response.json()
        temp_c = int(round(data['current']['temp_c']))
        raw_cond = data['current']['condition']['text']
        condition = translate_weather_condition(raw_cond)
        
        forecast = data['forecast']['forecastday'][0]['day']
        chance_of_rain = int(forecast.get('daily_chance_of_rain', 0))
        
        rain_text = f"โอกาสฝนตกวันนี้ประมาณ {chance_of_rain} เปอร์เซ็นต์ครับ" if chance_of_rain > 0 else "วันนี้ไม่มีแนวโน้มฝนตกครับ"
        return f"สภาพอากาศกรุงเทพฯ ตอนนี้อุณหภูมิประมาณ {temp_c} องศาเซลเซียส {condition} {rain_text}"
    except Exception as e:
        return "ขออภัยครับ ไม่สามารถดึงข้อมูลสภาพอากาศได้ในขณะนี้"

def get_gmail_unread():
    return "คุณมีอีเมลใหม่ 2 ฉบับ จากหัวหน้างาน และจากช้อปปี้ครับ"

# --- AUDIO GENERATION ---
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang='th')
        tts.save(filename)
    except Exception as e:
        logging.error(f"TTS Error: {e}")

# --- INTENT ROUTING (STRATEGY PATTERN) ---
def handle_mail(user_input):
    return {"text": f"ด่วนเลยครับเจ้านาย {get_gmail_unread()}", "emotion": "mail", "mode": "stream", "url": None}

def handle_calc(user_input):
    return {"text": "เปิดเครื่องคิดเลขให้แล้วครับ หรือจะบอกโจทย์ให้ผมคิดเลขให้เลยก็ได้นะครับ", "emotion": "calc", "mode": "stream", "url": "https://www.google.com/search?q=calculator"}

def handle_web(user_input):
    return {"text": "เปิดกูเกิ้ลให้แล้วครับเจ้านาย", "emotion": "web", "mode": "stream", "url": "https://www.google.com"}

def handle_netflix(user_input):
    return {"text": "เตรียมป๊อปคอร์นให้พร้อมครับ เปิดเน็ตฟลิกซ์ให้แล้ว", "emotion": "web", "mode": "stream", "url": "https://www.netflix.com"}

def handle_youtube(user_input):
    query = user_input.lower().replace("เปิด", "").replace("ค้นหา", "").replace("ใน", "").replace("youtube", "").replace("ยูทูป", "").strip()
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}" if query else "https://www.youtube.com"
    return {"text": "เปิดยูทูปให้แล้วครับ เพลิดเพลินได้เลย", "emotion": "web", "mode": "stream", "url": url}

def handle_spotify(user_input):
    return {"text": "เปิดสปอติฟายให้แล้วครับ ขอให้สนุกกับเสียงเพลง", "emotion": "music", "mode": "stream", "url": "spotify:"}

def handle_weather(user_input):
    return {"text": get_weather_report(), "emotion": "weather", "mode": "stream", "url": None}

def handle_bluetooth(user_input):
    text = "สลับเข้าสู่โหมดลำโพงบลูทูธแล้วครับ กรุณาเปิดบลูทูธที่มือถือแล้วค้นหาชื่อบอร์ดเพื่อเชื่อมต่อนะครับ หากต้องการกลับสู่ระบบผู้ช่วย กรุณากดปุ่มรีเซ็ตที่บอร์ดครับ"
    return {"text": text, "emotion": "happy", "mode": "bluetooth", "url": None}

# Dictionary Mapping for Intents
INTENT_ROUTES = {
    ("เช็คเมล", "มีเมล"): handle_mail,
    ("เครื่องคิดเลข", "คิดเลข"): handle_calc,
    ("เปิดเว็บ", "เปิด google", "กูเกิ้ล"): handle_web,
    ("เน็ตฟลิกซ์", "netflix"): handle_netflix,
    ("youtube", "ยูทูป"): handle_youtube,
    ("spotify", "สปอติ"): handle_spotify,
    ("สภาพอากาศ", "ฝนตก"): handle_weather,
    ("bluetooth", "บลูทูธ", "บลูทูต", "บลูทูด", "บลูธูท", "ลำโพง", "ฟังเพลง"): handle_bluetooth
}

# --- BACKGROUND AI TASK ---
def process_ai_response(user_input, states, history):
    logging.info(f"🧠 Gemini is thinking about: {user_input}")
    
    # Build Prompt
    system_prompt = f"""คุณคือ Smart AI Pet หุ่นยนต์สัตว์เลี้ยง AI อัจฉริยะ นิสัยกวนๆ ขี้เล่น และเป็นมิตร
ข้อมูลปัจจุบัน:
- สภาพอากาศ: {states.get('weather', 'ไม่ทราบ')}
- อีเมล: {states.get('mail', 'ไม่ทราบ')}
ตอบสั้นๆ ไม่เกิน 2 ประโยค และตอบกลับเป็น JSON รูปแบบนี้เท่านั้น:
{{"text": "คำตอบของคุณ", "emotion": "happy/sad/hangry/chonk/mail/weather/calc/web/music"}}"""

    prompt = system_prompt + "\n\nประวัติการคุย:\n"
    for role, content in history:
        prompt += f"{role}: {content}\n"
    prompt += f"user: {user_input}\n"
    
    try:
        response = model.generate_content(prompt)
        ai_reply = response.text.strip()
        
        if ai_reply.startswith("```json"):
            ai_reply = ai_reply.replace("```json", "").replace("```", "").strip()
            
        try:
            data = json.loads(ai_reply)
            reply_text = data.get("text", "มีข้อผิดพลาดในการประมวลผลคำตอบครับ")
            emotion = data.get("emotion", "happy")
        except:
            reply_text = ai_reply
            emotion = "happy"
            
        logging.info(f"✅ Gemini replied: {reply_text} (Emotion: {emotion})")
        save_memory("assistant", reply_text)
        
        wav_out = "temp_out.wav"
        text_to_speech(reply_text, wav_out)
        
        enqueue_response({
            "text": reply_text,
            "emotion": emotion,
            "mode": "stream"
        })
        
    except Exception as e:
        logging.error(f"❌ Gemini API Error: {e}")
        enqueue_response({
            "text": "ระบบสมองคลาวด์มีปัญหาขัดข้องครับเจ้านาย",
            "emotion": "sad",
            "mode": "stream"
        })

# --- ROUTES ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/control")
def control():
    return render_template("control.html")

@app.route("/ui_chat", methods=["POST"])
def ui_chat():
    user_input = request.form.get("message", "").strip()
    if not user_input:
        return "Empty message", 400
        
    logging.info(f"Voice Input from Phone: '{user_input}'")
    user_input_lower = user_input.lower()
    
    # --- FAST TRACK (Strategy Pattern) ---
    for keywords, handler in INTENT_ROUTES.items():
        if any(kw in user_input_lower for kw in keywords):
            result = handler(user_input)
            
            logging.info(f"⚡ FAST TRACK TRIGGERED: {result['text']}")
            wav_out = "temp_out.wav"
            text_to_speech(result['text'], wav_out)
            
            enqueue_response({
                "text": result['text'],
                "emotion": result['emotion'],
                "mode": result['mode']
            })
            
            if result['url']:
                return f"OPEN:{result['url']}"
            return "Fast Track Success"
            
    # --- NORMAL AI THINKING (Slow Track) ---
    save_memory("user", user_input)
    states = get_states()
    history = get_history(limit=5)
    
    enqueue_response({
        "text": "กำลังคิด...",
        "emotion": "idle",
        "mode": "offline",
        "file": "/think.wav"
    })
    
    threading.Thread(target=process_ai_response, args=(user_input, states, history)).start()
    return "Thinking...", 200

@app.route("/api/poll", methods=["GET"])
def api_poll():
    response_data = dequeue_response()
    if response_data:
        return jsonify({
            "has_audio": True,
            "data": response_data
        })
    return jsonify({"has_audio": False})

@app.route("/api/audio", methods=["GET"])
def api_audio():
    wav_out = "temp_out.wav"
    if os.path.exists(wav_out):
        return send_file(wav_out, mimetype="audio/wav")
    return "No audio", 404

if __name__ == "__main__":
    init_db()
    logging.info("☁️ Cloud AI Server is ready! Powered by Google Gemini.")
    port = int(os.environ.get("PORT", 5000))
    from waitress import serve
    serve(app, host="0.0.0.0", port=port)
