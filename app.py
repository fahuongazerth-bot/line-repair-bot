import threading
import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextSendMessage
import google.generativeai as genai
from io import BytesIO
from PIL import Image

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = 'I1tVyY+ii/Alj5oITsOdfZF1esFzlNY4j8NKvsUYBtw6Gnq3S4Py+kryy/I4I26EnCQizM83zc8g1Ol3hSHqEDnksODMZXOV5d2zrkFVzIUYgSg/MU6TgEdulyS9X9rEoj4xeqzSrP2aU7Lqy1eUzQdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '4d6fa3edc845273ddb6fb8be0494246a'
GEMINI_API_KEY = 'AQ.Ab8RN6LBhuU9c6rIF47VAG3zGMSIQu9wHPY3WcTO2x9Ca49G1A'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# เรียกใช้โมเดล Gemini สำหรับวิเคราะห์ภาพบิล
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        # สั่งให้บอทแยกไปทำงานเบื้องหลัง (Thread) LINE จะได้ไม่รอจน Timeout
        thread = threading.Thread(target=handler.handle, args=(body, signature))
        thread.start()
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ฟังก์ชันทำงานอัตโนมัติเมื่อมีคนส่ง "รูปภาพ" เข้ามาในกลุ่ม
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if event.source.type == 'group':
        group_id = event.source.group_id
        user_id = event.source.user_id
        
        # ดึงชื่อไลน์ของคนส่งบิล
        try:
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
            sender_name = profile.display_name
        except:
            sender_name = "ไม่สามารถระบุชื่อไลน์ได้"

        # ดาวน์โหลดรูปภาพบิลจาก LINE เข้ามาในระบบแบบชั่วคราว
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = BytesIO(message_content.content)
        img = Image.open(image_bytes)

        # สั่งให้ AI อ่านภาษาไทยและตัวเลขในบิลซ่อมรถ
        prompt = """
        คุณคือผู้เชี่ยวชาญด้านบัญชีและการจัดการยานพาหนะ 
        นี่คือรูปภาพบิลหรือใบเสร็จค่าซ่อมรถ/บำรุงรักษารถ กรุณาอ่านและสรุปข้อมูลต่อไปนี้เป็นภาษาไทย:
        1. ทะเบียนรถ: (เช่น กข 1234 หรือระบุว่า "ไม่พบในบิล")
        2. วันที่ในบิล: (ระบุวันที่ที่ซ่อม)
        3. รายการซ่อม: (สรุปสั้นๆ ว่าทำอะไรบ้าง เช่น เปลี่ยนน้ำมันเครื่อง, สลับยาง)
        4. ราคารวมทั้งหมด: (ระบุจำนวนเงินรวมเป็นบาท เช่น 1,500 บาท)
        
        เน้นเฉพาะข้อมูลที่ปรากฏจริงบนบิลเท่านั้น หากส่วนไหนไม่มีให้เขียนว่า "ไม่ระบุในบิล"
        """
        
        try:
            # ส่งรูปและคำสั่งไปให้ Gemini ประมวลผล
            response = model.generate_content([prompt, img])
            ai_result = response.text
            
            # รูปแบบข้อความที่จะส่งกลับเข้ากลุ่ม LINE
            report_message = (
                f"📊 [รายงานการส่งบิลซ่อมรถ]\n"
                f"👤 ผู้แจ้งซ่อม: {sender_name}\n"
                f"-----------------------------\n"
                f"{ai_result}"
            )
            
            # ส่งข้อความกลับเข้ากลุ่ม
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=report_message)
            )

        except Exception as e:
            print("Error:", e)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ เกิดข้อผิดพลาด: AI ไม่สามารถอ่านรูปภาพบิลนี้ได้ กรุณาลองส่งใหม่อีกครั้ง หรือตรวจสอบความชัดเจนของรูปภาพ")
            )

if __name__ == "__main__":
    app.run(port=8080)
