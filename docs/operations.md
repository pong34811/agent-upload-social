# คู่มือใช้งานประจำวัน

คำสั่งทั้งหมดทำงานในเครื่อง Windows และรับเฉพาะโฟลเดอร์ที่ระบุ ไม่เฝ้าดูโฟลเดอร์และไม่อัปโหลดตามเวลาเอง

## ตั้งค่าโปรไฟล์และยอมรับนโยบาย

เปิด PowerShell ในโฟลเดอร์โปรเจกต์ แล้วเรียก:

```powershell
kt404-youtube profile setup
kt404-youtube profile show
kt404-youtube profile accept-policy
```

`profile setup` ถามชื่อช่อง, คำอธิบาย/Tags, category, privacy, Made for Kids, synthetic media, Official Artist Channel, การรับรองสิทธิ์ assets, พาธ OAuth Desktop JSON และ URL privacy policy ที่เผยแพร่แล้ว การตั้งค่าโปรไฟล์ไม่ได้เปิด browser หรือเชื่อม OAuth

ก่อนใช้ `accept-policy` ให้อ่าน privacy policy ของโปรเจกต์และ YouTube Terms of Service ที่แสดงในคำสั่ง แล้วพิมพ์ `ยอมรับ` ด้วยตนเอง หากไม่ยอมรับ โปรแกรมจะยังไม่เปิด OAuth/API

## ตรวจคลิปโดยไม่เชื่อมต่อ YouTube

```powershell
kt404-youtube dry-run --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

คำสั่งตรวจเฉพาะไฟล์ระดับบนสุด จับคู่ MOV/JPG ด้วยชื่อเดียวกัน, อ่านข้อมูลวิดีโอด้วย `ffprobe`, คำนวณ hash เพื่อกันส่งซ้ำ และแสดงไฟล์ที่ต้องแก้ ไม่มี OAuth หรือ request ไป YouTube ในขั้นนี้

## คลิปนำร่องและ batch

เมื่อเจ้าของสั่งอัปโหลดอย่างชัดเจน คำสั่งแรกจะอัปโหลดคลิปแรกที่ผ่าน preflight เรียงตามชื่อไฟล์ บังคับเป็น Private และแสดงช่องที่ resolve ได้, จำนวนคลิป, จำนวนที่ข้าม, privacy, revision และ declarations ก่อนเริ่มส่ง bytes:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

เมื่อเสร็จ ให้ตรวจคลิปและ thumbnail ใน YouTube Studio จาก URL ที่คำสั่งรายงาน แล้วเจ้าของจึงบันทึกการอนุมัติ:

```powershell
kt404-youtube profile approve-pilot --video-id VIDEO_ID
```

การอนุมัติใช้ได้เฉพาะวิดีโอที่โปรแกรมบันทึกว่าอัปโหลดครบและยืนยัน visibility เป็น Private แล้ว หลังจากนั้นให้มีคำสั่งจากเจ้าของแยกอีกครั้งจึงอัปโหลด batch ที่เหลือ:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

แต่ละงานมี checkpoint resumable และกันซ้ำด้วย hash ของไฟล์กับ channel ID ถ้า thumbnail ล้มเหลว งานวิดีโอยังอยู่ในสถานะ retry thumbnail โดยไม่ส่งวิดีโอซ้ำ หาก quota หมด คิวที่เหลือจะหยุด

## เปลี่ยนค่าที่เจ้าของยืนยัน

```powershell
kt404-youtube profile set-privacy private
kt404-youtube profile set-api-audit-status passed
kt404-youtube profile set-asset-rights-status confirmed
```

ใช้ `set-api-audit-status passed` หลังจากแยกตรวจ YouTube API audit เรียบร้อยแล้วเท่านั้น Public และ Unlisted จะถูกปิดจนกว่าจะผ่าน audit ส่วนคำสั่งสิทธิ์ assets คือการยืนยันของเจ้าของ ไม่ใช่การตรวจลิขสิทธิ์อัตโนมัติ

## ลบข้อมูล API หรือยกเลิก OAuth

```powershell
kt404-youtube profile delete-account-data --channel-id CHANNEL_ID
kt404-youtube profile revoke-authorization --channel-id CHANNEL_ID
```

คำสั่งลบข้อมูลลบ job/API-derived records ที่ผูกกับ channel ID ในเครื่อง แต่ไม่ลบวิดีโอบน YouTube ส่วนคำสั่ง revoke ส่งคำขอยกเลิก grant กับ Google, ลบ OAuth token ใน Windows Credential Manager และลบข้อมูลของช่อง หากติดต่อ Google ไม่ได้ ให้ตรวจรายการแอปที่เชื่อมไว้ใน [Google Security permissions](https://security.google.com/settings/security/permissions)

## Maintenance รายสัปดาห์

`maintenance refresh` ตรวจว่า OAuth ยังใช้ได้และ channel ID ยังเป็นช่องที่บัญชีนี้เป็นเจ้าของ, อัปเดต YouTube API records ที่ครบกำหนด และลบข้อมูลที่หมดอายุ ห้ามใช้ scheduler เรียก `upload` หรือเฝ้าดู `vdo`

ตั้ง Windows Task Scheduler ด้วยผู้ใช้ Windows คนเดียวกับที่เก็บ OAuth token:

1. สร้าง Basic Task ชื่อ `Katy404 YouTube API maintenance` ให้ทำงานสัปดาห์ละครั้งในเวลาที่เครื่องเปิดอยู่
2. เลือก **Run only when user is logged on** เพื่อใช้ Windows Credential Manager ของบัญชีเจ้าของ
3. Action: Start a program; Program ใช้พาธเต็มของ `kt404-youtube.exe` ใน environment ที่ติดตั้ง เช่น `<project>\.venv\Scripts\kt404-youtube.exe`; Arguments คือ `maintenance refresh`; Start in คือโฟลเดอร์โปรเจกต์
4. อย่าตั้ง trigger แบบ file watcher และอย่าเพิ่มพาธวิดีโอหรือคำสั่ง `upload` ใน task

หาก OAuth ถูกเพิกถอนหรือช่องไม่อยู่ในบัญชีแล้ว maintenance หยุดและลบข้อมูล API-derived ของช่องนั้นเพื่อไม่ให้ประมวลผลต่อด้วยข้อมูลเก่า
