"""
F.R.I.D.A.Y. Machine Learning & Habit Analyzer for Ubuntu Server
---------------------------------------------------------------
สคริปต์วิเคราะห์พฤติกรรมเจ้านาย และรายงานสถานะ Protocol สำหรับรันบน Ubuntu Linux
อ่านข้อมูลจาก:
1. SQLite Database (database.db) ที่เก็บประวัติการสั่งงานผ่าน Web/Voice
2. SD Card Log (butler_log.csv) ที่บันทึกจากการสัมผัส Touch Sensor ของ ESP32
"""

import os
import sqlite3
import datetime
from collections import Counter

DB_PATH = "database.db"
CSV_PATH = "butler_log.csv"

def analyze_sqlite():
    if not os.path.exists(DB_PATH):
        print(f"[-] ไม่พบฐานข้อมูล {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\n" + "="*50)
    print("   F.R.I.D.A.Y. STARK OS - HABIT & TELEMETRY REPORT")
    print("="*50)

    # 1. Total chat memory
    cursor.execute("SELECT role, content FROM chat_memory")
    rows = cursor.fetchall()
    user_msgs = [r[1] for r in rows if r[0] == "user"]
    friday_msgs = [r[1] for r in rows if r[0] == "assistant"]

    print(f"\n[+] ประวัติการสนทนาทั้งหมด: {len(rows)} รายการ")
    print(f"    - คำสั่งจากเจ้านาย: {len(user_msgs)} ครั้ง")
    print(f"    - F.R.I.D.A.Y. ตอบสนอง: {len(friday_msgs)} ครั้ง")

    # 2. Command queue history
    cursor.execute("SELECT command, status FROM command_queue")
    cmd_rows = cursor.fetchall()
    if cmd_rows:
        cmd_counter = Counter([r[0] for r in cmd_rows])
        print(f"\n[+] โปรโตคอล Stark ที่ถูกสั่งบ่อยที่สุด:")
        for cmd, count in cmd_counter.most_common(5):
            pct = (count / len(cmd_rows)) * 100
            print(f"    * {cmd.upper():<12} : {count} ครั้ง ({pct:.1f}%)")

    conn.close()

def analyze_sd_csv():
    if not os.path.exists(CSV_PATH):
        print(f"\n[*] หมายเหตุ: หากต้องการนำไฟล์จาก SD Card มาวิเคราะห์ ให้คัดลอก 'butler_log.csv' มาวางในโฟลเดอร์นี้")
        return

    print(f"\n[+] กำลังวิเคราะห์ Blackbox Telemetry จาก SD Card ({CSV_PATH})...")
    events = []
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    events.append(parts[1].strip())

        counter = Counter(events)
        print(f"    - จำนวนเหตุการณ์ที่ ESP32 บันทึก: {len(events)} รายการ")
        for ev, cnt in counter.most_common():
            print(f"      * {ev}: {cnt} ครั้ง")
    except Exception as e:
        print(f"    [-] เกิดข้อผิดพลาดในการอ่าน CSV: {e}")

def generate_ai_advice():
    now = datetime.datetime.now()
    hour = now.hour
    print("\n" + "-"*50)
    print("   F.R.I.D.A.Y. HEURISTIC ADVICE (คำแนะนำตามเวลาปัจจุบัน)")
    print("-"*50)
    if 6 <= hour < 12:
        print(f"[*] ขณะนี้เวลา {now.strftime('%H:%M')} น. ช่วงเช้า")
        print("    F.R.I.D.A.Y. แนะนำ: เปิดโหมด STANDBY หรือตรวจสอบสรุปสภาพอากาศ/เมลงาน")
    elif 12 <= hour < 18:
        print(f"[*] ขณะนี้เวลา {now.strftime('%H:%M')} น. ช่วงบ่าย")
        print("    F.R.I.D.A.Y. แนะนำ: เปิดโหมด FOCUS (ไฟ LED นิ่ง) เพื่อให้บอสมีสมาธิทำงานสูงสุด")
    elif 18 <= hour < 22:
        print(f"[*] ขณะนี้เวลา {now.strftime('%H:%M')} น. ช่วงค่ำ")
        print("    F.R.I.D.A.Y. แนะนำ: เปิดโหมด RELAX (ไฟหายใจนุ่มนวล) หรือเปิดเพลง/Netflix ผ่อนคลาย")
    else:
        print(f"[*] ขณะนี้เวลา {now.strftime('%H:%M')} น. ช่วงดึก")
        print("    F.R.I.D.A.Y. แนะนำ: สแตนด์บายลดแสงไฟทั้งหมด (SLEEP MODE) เตรียมพร้อมสำหรับวันพรุ่งนี้ครับเจ้านาย")
    print("="*50 + "\n")

if __name__ == "__main__":
    analyze_sqlite()
    analyze_sd_csv()
    generate_ai_advice()
