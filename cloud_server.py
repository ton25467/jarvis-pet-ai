import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import google.generativeai as genai
from gtts import gTTS
import urllib.request
import json
import threading

app = Flask(__name__)

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️ คำเตือน: ยังไม่ได้ตั้งค่า GEMINI_API_KEY ใน Environment Variables!")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

PENDING_RESPONSES = []
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

# --- TOOL FUNCTIONS ---
def get_weather():
    try:
        url = "https://wttr.in/Bangkok?format=%t+%C"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode('utf-8').strip()
    except Exception as e:
        return f"ไม่สามารถดึงข้อมูลสภาพอากาศได้: {e}"

def get_rain_forecast():
    try:
        url = "https://wttr.in/Bangkok?format=%p"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            rain = response.read().decode('utf-8').strip()
            if rain and rain != "0.0mm":
                return f"มีโอกาสฝนตก {rain}"
            return "ไม่มีแนวโน้มฝนตกหนัก"
    except:
        return "ดึงข้อมูลฝนไม่ได้"

def get_gmail_unread():
    return "คุณมีอีเมลใหม่ 2 ฉบับ จากหัวหน้างาน และจากช้อปปี้ครับ"

# --- AUDIO GENERATION ---
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang='th')
        tts.save(filename)
    except Exception as e:
        print(f"TTS Error: {e}")

# --- BACKGROUND AI TASK ---
def process_ai_response(user_input, states, history):
    print(f"🧠 Gemini is thinking about: {user_input}")
    
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
        # Generate content with Gemini
        response = model.generate_content(prompt)
        ai_reply = response.text.strip()
        
        # Clean JSON if it has markdown formatting
        if ai_reply.startswith("```json"):
            ai_reply = ai_reply.replace("```json", "").replace("```", "").strip()
            
        try:
            data = json.loads(ai_reply)
            reply_text = data.get("text", "มีข้อผิดพลาดในการประมวลผลคำตอบครับ")
            emotion = data.get("emotion", "happy")
        except:
            reply_text = ai_reply
            emotion = "happy"
            
        print(f"✅ Gemini replied: {reply_text} (Emotion: {emotion})")
        
        save_memory("assistant", reply_text)
        
        # Generate TTS
        wav_out = "temp_out.wav"
        text_to_speech(reply_text, wav_out)
        
        # Queue for ESP32
        PENDING_RESPONSES.append({
            "text": reply_text,
            "emotion": emotion,
            "mode": "stream"
        })
        
    except Exception as e:
        print(f"❌ Gemini API Error: {e}")
        PENDING_RESPONSES.append({
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
        
    print(f"\n🎙️ Voice Input from Phone: '{user_input}'")
    
    # --- FAST TRACK (ระบบคำสั่งด่วน ลัดคิว AI) ---
    fast_track_response = None
    fast_emotion = "happy"
    
    if "เช็คเมล" in user_input or "มีเมล" in user_input:
        mail_status = get_gmail_unread()
        fast_track_response = f"ด่วนเลยครับเจ้านาย {mail_status}"
        fast_emotion = "mail"
    
    elif "เปิดเครื่องคิดเลข" in user_input:
        # บน Cloud เราไม่สามารถ Popen("calc.exe") ในคอมของผู้ใช้ได้โดยตรง
        fast_track_response = "โหมดคลาวด์ไม่สามารถเปิดโปรแกรมในคอมพิวเตอร์ได้ครับเจ้านาย"
        fast_emotion = "sad"
        
    elif "เปิดเว็บ" in user_input or "เปิด google" in user_input.lower() or "กูเกิ้ล" in user_input:
        fast_track_response = "เปิดกูเกิ้ลให้แล้วครับเจ้านาย"
        fast_emotion = "web"

    elif "เน็ตฟลิกซ์" in user_input or "netflix" in user_input.lower():
        fast_track_response = "เตรียมป๊อปคอร์นให้พร้อมครับ เปิดเน็ตฟลิกซ์ให้แล้ว"
        fast_emotion = "web"

    elif "youtube" in user_input.lower() or "ยูทูป" in user_input:
        fast_track_response = "เปิดยูทูปให้แล้วครับ เพลิดเพลินได้เลย"
        fast_emotion = "web"
        
    elif "spotify" in user_input.lower() or "สปอติ" in user_input:
        fast_track_response = "เปิดสปอติฟายให้แล้วครับ ขอให้สนุกกับเสียงเพลง"
        fast_emotion = "music"
        
    elif "สภาพอากาศ" in user_input or "ฝนตก" in user_input:
        weather = get_weather()
        rain = get_rain_forecast()
        fast_track_response = f"รายงานด่วนครับ {weather} และ {rain}"
        fast_emotion = "weather"
        
    elif "บลูทูธ" in user_input.lower() or "ลำโพง" in user_input or "ฟังเพลง" in user_input:
        fast_track_response = "สลับเข้าสู่โหมดลำโพงบลูทูธแล้วครับ หากต้องการกลับสู่ระบบผู้ช่วย กรุณากดปุ่มรีเซ็ตที่บอร์ดนะครับ"
        fast_emotion = "happy"
        wav_out = "temp_out.wav"
        text_to_speech(fast_track_response, wav_out)
        response_payload = {
            "text": fast_track_response,
            "emotion": fast_emotion,
            "mode": "bluetooth"
        }
        PENDING_RESPONSES.append(response_payload)
        return "Fast Track Success"
        
    if fast_track_response:
        print(f"⚡ FAST TRACK TRIGGERED: {fast_track_response}")
        wav_out = "temp_out.wav"
        text_to_speech(fast_track_response, wav_out)
        response_payload = {
            "text": fast_track_response,
            "emotion": fast_emotion,
            "mode": "stream"
        }
        PENDING_RESPONSES.append(response_payload)
        
        # Determine if we should send an OPEN command to the client browser (for mobile)
        if "เปิดเว็บ" in user_input or "เปิด google" in user_input.lower() or "กูเกิ้ล" in user_input:
            return "OPEN:https://www.google.com"
        elif "เน็ตฟลิกซ์" in user_input or "netflix" in user_input.lower():
            return "OPEN:https://www.netflix.com"
        elif "youtube" in user_input.lower() or "ยูทูป" in user_input:
            # Extract search query if user says "ค้นหา...ในยูทูป" or "เปิด...ในยูทูป"
            import urllib.parse
            query = user_input.lower().replace("เปิด", "").replace("ค้นหา", "").replace("ใน", "").replace("youtube", "").replace("ยูทูป", "").strip()
            if query:
                encoded_query = urllib.parse.quote(query)
                return f"OPEN:https://www.youtube.com/results?search_query={encoded_query}"
            return "OPEN:https://www.youtube.com"
        elif "spotify" in user_input.lower() or "สปอติ" in user_input:
            return "OPEN:spotify:"
            
        return "Fast Track Success"
        
    # --- NORMAL AI THINKING (Slow Track) ---
    save_memory("user", user_input)
    states = get_states()
    history = get_history(limit=5)
    
    # แจ้ง ESP32 ให้เล่นเสียง offline filler (เช่น "ขอคิดแป๊บนะครับ") ระหว่างรอคลาวด์ประมวลผล
    PENDING_RESPONSES.append({
        "text": "กำลังคิด...",
        "emotion": "idle",
        "mode": "offline",
        "file": "/think.wav"
    })
    
    # Run Gemini in background thread
    threading.Thread(target=process_ai_response, args=(user_input, states, history)).start()
    
    return "Thinking...", 200

@app.route("/api/poll", methods=["GET"])
def api_poll():
    if PENDING_RESPONSES:
        response_data = PENDING_RESPONSES.pop(0)
        return jsonify({
            "has_audio": True,
            "data": response_data
        })
    else:
        return jsonify({"has_audio": False})

@app.route("/api/audio", methods=["GET"])
def api_audio():
    wav_out = "temp_out.wav"
    if os.path.exists(wav_out):
        return send_file(wav_out, mimetype="audio/wav")
    return "No audio", 404

if __name__ == "__main__":
    init_db()
    print("☁️ Cloud AI Server is ready! Powered by Google Gemini.")
    # For local testing, we run on 5000. When on Render, it uses PORT env var.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
