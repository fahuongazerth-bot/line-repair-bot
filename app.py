import os
import threading
import logging
from io import BytesIO

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextSendMessage
from PIL import Image

from google import genai

# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# -----------------------------------------------------------------------
# 🔴 อ่านค่า config จาก Environment Variables (ห้าม hardcode ในไฟล์นี้)
#
# ตั้งค่าก่อนรัน เช่น:
#   export LINE_CHANNEL_ACCESS_TOKEN="..."
#   export LINE_CHANNEL_SECRET="..."
#   export GEMINI_API_KEY="AQ...."     <-- key รูปแบบใหม่ (Auth key)
#
# หมายเหตุ: ตั้งแต่ปี 2026 Google เปลี่ยนมาออก key แบบ "AQ." (Auth key)
# แทนแบบเดิม "AIza..." (Standard key ซึ่งกำลังถูกเลิกใช้ทั้งหมดใน
# ก.ย. 2026) ต้องใช้ library ใหม่ "google-genai" เท่านั้นถึงจะรองรับ
# key แบบนี้ — library เก่า "google-generativeai" ใช้ไม่ได้แล้ว
#
# ติดตั้ง dependency ที่ถูกต้อง:
#   pip uninstall google-generativeai
#   pip install google-genai
# -----------------------------------------------------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("I1tVyY+ii/Alj5oITsOdfZF1esFzlNY4j8NKvsUYBtw6Gnq3S4Py+kryy/I4I26EnCQizM83zc8g1Ol3hSHqEDnksODMZXOV5d2zrkFVzIUYgSg/MU6TgEdulyS9X9rEoj4xeqzSrP2aU7Lqy1eUzQdB04t89/1O/w1cDnyilFU=")
LINE_CHANNEL_SECRET = os.environ.get("4d6fa3edc845273ddb6fb8be0494246a")
GEMINI_API_KEY = os.environ.get("AQ.Ab8RN6LnHLT69ybwrdHPPnFQJbDLEaTtDfL6opgp59Ue7Fuldw")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-3.5-flash")

missing = [
    name
    for name, val in [
        ("LINE_CHANNEL_ACCESS_TOKEN", LINE_CHANNEL_ACCESS_TOKEN),
        ("LINE_CHANNEL_SECRET", LINE_CHANNEL_SECRET),
        ("GEMINI_API_KEY", GEMINI_API_KEY),
    ]
    if not val
]
if missing:
    raise RuntimeError(
        f"❌ ขาด Environment Variable: {', '.join(missing)} "
        f"กรุณาตั้งค่าก่อนรันแอป"
    )

if not (GEMINI_API_KEY.startswith("AQ.") or GEMINI_API_KEY.startswith("AIza")):
    logger.warning(
        "⚠️ GEMINI_API_KEY ดูเหมือนจะไม่ใช่รูปแบบที่รู้จัก "
        "(ปกติขึ้นต้นด้วย 'AQ.' สำหรับ key รุ่นใหม่ หรือ 'AIza' สำหรับ key รุ่นเก่า)"
    )

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Client ตัวใหม่ของ google-genai รองรับทั้ง key แบบเก่า (AIza) และใหม่ (AQ.)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """
คุณคือผู้เชี่ยวชาญด้านบัญชีและการจัดการยานพาหนะ
นี่คือรูปภาพบิลหรือใบเสร็จค่าซ่อมรถ/บำรุงรักษารถ กรุณาอ่านและสรุปข้อมูลต่อไปนี้เป็นภาษาไทย:
1. ทะเบียนรถ: (เช่น กข 1234 หรือระบุว่า "ไม่พบในบิล")
2. วันที่ในบิล: (ระบุวันที่ที่ซ่อม)
3. รายการซ่อม: (สรุปสั้นๆ ว่าทำอะไรบ้าง เช่น เปลี่ยนน้ำมันเครื่อง, สลับยาง)
4. ราคารวมทั้งหมด: (ระบุจำนวนเงินรวมเป็นบาท เช่น 1,500 บาท)

เน้นเฉพาะข้อมูลที่ปรากฏจริงบนบิลเท่านั้น หากส่วนไหนไม่มีให้เขียนว่า "ไม่ระบุในบิล"
""".strip()


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    if signature is None:
        abort(400)

    body = request.get_data(as_text=True)

    try:
        thread = threading.Thread(target=handler.handle, args=(body, signature))
        thread.start()
    except InvalidSignatureError:
        logger.error("Invalid signature ในการเรียก webhook")
        abort(400)
    except Exception:
        logger.exception("เกิดข้อผิดพลาดตอนเริ่ม thread จัดการ event")
        abort(500)

    return "OK"


def get_sender_name(event) -> str:
    """พยายามดึงชื่อผู้ส่ง ถ้าหาไม่ได้ให้คืนค่า fallback"""
    try:
        if event.source.type == "group":
            return line_bot_api.get_group_member_profile(
                event.source.group_id, event.source.user_id
            ).display_name
        if event.source.type == "room":
            return line_bot_api.get_room_member_profile(
                event.source.room_id, event.source.user_id
            ).display_name
        return line_bot_api.get_profile(event.source.user_id).display_name
    except Exception:
        logger.warning("ดึงชื่อผู้ส่งไม่สำเร็จ", exc_info=True)
        return "ไม่ทราบชื่อผู้ส่ง"


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    sender_name = get_sender_name(event)

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = BytesIO(message_content.content)
        img = Image.open(image_bytes)

        # เรียก Gemini ผ่าน client ใหม่ (google-genai)
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=[PROMPT, img],
        )
        ai_result = (response.text or "").strip()

        if not ai_result:
            ai_result = "⚠️ AI ไม่สามารถอ่านข้อมูลจากภาพนี้ได้ กรุณาลองส่งภาพที่ชัดเจนกว่านี้"

        report_message = (
            f"📊 [รายงานการส่งบิลซ่อมรถ]\n"
            f"👤 ผู้แจ้งซ่อม: {sender_name}\n"
            f"-----------------------------\n"
            f"{ai_result}"
        )

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report_message))

    except Exception as e:
        logger.exception("เกิดข้อผิดพลาดระหว่างประมวลผลภาพ")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ เกิดข้อผิดพลาด: {str(e)[:200]}"),
            )
        except Exception:
            logger.exception("ส่ง error message กลับ LINE ไม่สำเร็จ (อาจเป็นเพราะ reply token หมดอายุ)")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
