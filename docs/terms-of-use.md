# ข้อกำหนดการใช้งาน — Katy404 YouTube Upload Agent (ฉบับร่าง)

**สถานะ: ยังไม่พร้อมเผยแพร่** — เจ้าของต้องใส่ช่องทางติดต่อจริง ตรวจเงื่อนไขให้ตรงกับการใช้งาน และเผยแพร่บน URL HTTPS ก่อนเปิดใช้ YouTube API

การใช้เครื่องมือนี้เพื่อเชื่อมต่อหรืออัปโหลดไปยัง YouTube หมายความว่าผู้ใช้ต้องอ่านและยอมรับทั้งข้อกำหนดนี้, [YouTube Terms of Service](https://www.youtube.com/t/terms) และ [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies). เครื่องมือนี้ใช้ YouTube API Services ในนามบัญชีที่เจ้าของอนุญาต

## ความรับผิดชอบของเจ้าของ

- เจ้าของเลือก channel, โฟลเดอร์, privacy status, category, tags, audience และ synthetic-media declarations; เครื่องมือไม่เดาค่าที่เกี่ยวกับผู้ชมและไม่รับรองความเหมาะสมของ metadata แทน
- เจ้าของรับรองว่ามีสิทธิ์ใช้เสียง ภาพ game footage และ overlay ในไฟล์ที่เลือก และรับผิดชอบการปฏิบัติตามลิขสิทธิ์/ข้อกำหนดของ YouTube
- คำสั่งอัปโหลดที่ได้รับอนุญาตจะเริ่ม private pilot ก่อน; เจ้าของต้องตรวจคลิปและ thumbnail ใน YouTube Studio ก่อนอนุมัติ batch เต็ม
- ห้ามใช้โปรแกรมเพื่อเข้าถึงช่องที่บัญชีไม่มีสิทธิ์จัดการ, หลบเลี่ยง quota, รบกวนระบบ YouTube หรือใช้ข้อมูลที่ scrape มา

## การเชื่อมต่อและผลลัพธ์

โปรแกรมเรียก API เมื่อเจ้าของยินยอม OAuth และสั่งงานเฉพาะ path ที่ระบุ YouTube อาจใช้เวลาประมวลผล, จำกัด quota, ปฏิเสธเนื้อหา/thumbnail หรือเปลี่ยนข้อกำหนดได้ โปรแกรมทำ resumable retries ตามสถานะที่ยืนยันได้ แต่ไม่รับประกันว่า YouTube จะเผยแพร่หรือแสดงวิดีโออย่างไร

การลบข้อมูลที่เก็บในเครื่องไม่ได้ลบวิดีโอหรือข้อมูลบน YouTube; หากต้องการลบ content ให้ใช้ YouTube Studio หรือเครื่องมือ YouTube ที่รองรับโดยตรง

## การถอนสิทธิ์และติดต่อ

ผู้ใช้ยกเลิก OAuth ได้ด้วย `kt404-youtube profile revoke-authorization` หรือหน้า [Google Security permissions](https://security.google.com/settings/security/permissions) และขอลบข้อมูลที่เก็บในเครื่องด้วย `kt404-youtube profile delete-account-data`

ช่องทางติดต่อเจ้าของโปรเจกต์: **[ใส่อีเมลหรือช่องทางติดต่อจริงก่อนเผยแพร่]**
