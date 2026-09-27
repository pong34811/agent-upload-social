# คู่มือใช้งานประจำวัน

คำสั่งทั้งหมดทำงานในเครื่อง Windows และรับเฉพาะโฟลเดอร์ที่ระบุ ไม่เฝ้าดูโฟลเดอร์และไม่อัปโหลดตามเวลาเอง

ก่อนงานชุดแรกหรือเมื่อ quota ใกล้เต็ม ตรวจ project ใน Google Cloud Console: 24 คลิปใช้ 24 `videos.insert` calls จาก bucket 100 calls/day ของเมธอดนี้ และ thumbnail 24 ภาพใช้ประมาณ 1,200 units จาก bucket ของ endpoint อื่นตาม [quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost) retries ที่เปิด session insert ใหม่อาจเพิ่มจำนวน calls ตัวเลขและ quota อาจเปลี่ยน ตรวจหน้า Quotas ของ project จริงก่อน batch เต็ม

## ตั้งค่า OAuth และโปรไฟล์

เปิด PowerShell ในโฟลเดอร์โปรเจกต์และเปิด virtual environment ก่อนเรียกคำสั่ง:

```powershell
.venv\Scripts\Activate.ps1
kt404-youtube profile setup
kt404-youtube profile show
```

`auth token --client-secrets <พาธ Desktop OAuth JSON>` สร้างหรือตรวจ OAuth credential โดยไม่เรียก YouTube API ส่วน `profile setup` ใช้ OAuth อ่านรายชื่อช่อง แล้วให้เจ้าของเลือกช่องและยืนยันคำอธิบาย/Tags, category, privacy, Made for Kids, synthetic media และ Official Artist Channel

ทั้งสองคำสั่งไม่อัปโหลดวิดีโอ

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

### เมื่อไม่มี OAuth credential

ถ้ายังไม่มี credential ในไฟล์ของ OAuth account ที่ผูกกับโปรไฟล์ คำสั่ง `upload` จะเปิดหน้า local แสดงสถานะ แล้วเปิด Google OAuth Desktop flow ให้เจ้าของยืนยันตัวตนบนหน้า Google หน้า local ไม่ขอรหัสผ่านและไม่แสดง token; เมื่อบันทึก credential สำเร็จ หน้าแจ้ง `connected` แล้ว CLI ตรวจช่องที่ระบุก่อนเริ่มส่งวิดีโอ หากช่องไม่ตรง/กำกวม, consent ถูกยกเลิก, ใช้เวลาเกิน 10 นาที หรือบันทึก credential ไม่สำเร็จ คำสั่งหยุดก่อน upload

credential ที่บันทึกสำเร็จยังอยู่ในไฟล์ token ของ account นั้น หากชื่อช่องไม่ตรง เพื่อให้เจ้าของใช้กับคำสั่งครั้งถัดไปได้ตามต้องการ; อ่านรายละเอียดที่ [คู่มือติดตั้ง](setup.md). `dry-run` ยังคงทำงาน offline และไม่เปิด OAuth

หากต้องการล็อกอินและยืนยันช่องโดยไม่เริ่ม pilot ให้ใช้ `kt404-youtube auth login --channel "Katy404"` คำสั่งนี้ตรวจโปรไฟล์และช่องจาก API แล้วหยุดโดยไม่มีการส่งคลิป

เมื่อเสร็จ ให้ตรวจคลิปและ thumbnail ใน YouTube Studio จาก URL ที่คำสั่งรายงาน แล้วเจ้าของจึงบันทึกการอนุมัติ:

```powershell
kt404-youtube profile approve-pilot --video-id VIDEO_ID
```

การอนุมัติใช้ได้เฉพาะวิดีโอที่โปรแกรมบันทึกว่าอัปโหลดครบและยืนยัน visibility เป็น Private แล้ว หลังจากนั้นให้มีคำสั่งจากเจ้าของแยกอีกครั้งจึงอัปโหลด batch ที่เหลือ:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

แต่ละงานมี checkpoint resumable และกันซ้ำด้วย hash ของไฟล์กับ channel ID ถ้า thumbnail ล้มเหลว งานวิดีโอยังอยู่ในสถานะ retry thumbnail โดยไม่ส่งวิดีโอซ้ำ หาก quota หมด คิวที่เหลือจะหยุด

ถ้า network/API ขัดข้องชั่วคราวจน retry ในรอบนั้นหมด ระบบจะหยุดคิวและเก็บ resumable session ไว้ ให้รันคำสั่ง `upload` เดิมอีกครั้งเพื่อทำต่อ หาก job ถูกบันทึกเป็น `failed` หลังข้อผิดพลาดถาวรและแก้สาเหตุแล้ว ให้เลือกไฟล์นั้นโดยตรงเพื่อเตรียม retry:

```powershell
kt404-youtube profile retry-failed --path "G:\My Drive\Projects\Katy404\2026-09\vdo\ชื่อไฟล์.mov"
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

คำสั่ง retry ตรวจ channel ในโปรไฟล์และ hash ของวิดีโอ/JPG ต้องยังตรงกับงานเดิม จากนั้นคำนวณ metadata ใหม่จากโปรไฟล์ปัจจุบัน และคง hash/channel key เดิมไว้เพื่อป้องกันการส่งซ้ำ หากยังไม่ได้อนุมัติ pilot ระบบจะตั้ง retry เป็น Private เสมอ และจะหยุดเมื่อพบ job/session เดิมที่มี visibility อื่น หากไฟล์เปลี่ยน ให้แก้ปัญหาในต้นฉบับเดิมก่อนหรือจัดการข้อมูลเดิมโดยเจ้าของ; คำสั่งนี้จะไม่เปลี่ยนงานที่ไม่ใช่ `failed`

## เปลี่ยนค่าที่เจ้าของยืนยัน

```powershell
kt404-youtube profile set-privacy private
kt404-youtube profile set-api-audit-status passed
```

ใช้ `set-api-audit-status passed` หลังจากแยกตรวจ YouTube API audit เรียบร้อยแล้วเท่านั้น Public และ Unlisted จะถูกปิดจนกว่าจะผ่าน audit

## ลบข้อมูล API หรือยกเลิก OAuth

```powershell
kt404-youtube profile delete-account-data --channel-id CHANNEL_ID
kt404-youtube profile revoke-authorization --channel-id CHANNEL_ID
```

คำสั่งลบข้อมูลลบ job/API-derived records, resumable state, channel ID และ pilot ID ที่ผูกกับ channel ID ในเครื่อง แต่คงการตั้งค่าปฏิบัติงานของโปรไฟล์ไว้ และไม่ลบวิดีโอบน YouTube การลบ state ทำให้ hash เดิมไม่ถูกกันซ้ำอีกในครั้งถัดไป คำสั่ง revoke ส่งคำขอยกเลิก grant กับ Google, ลบเฉพาะไฟล์ token ของ OAuth account ที่ผูกกับโปรไฟล์ และลบข้อมูลของช่อง หากติดต่อ Google ไม่ได้ ให้ตรวจรายการแอปที่เชื่อมไว้ใน [Google Security permissions](https://security.google.com/settings/security/permissions)

ตัวโปรแกรมเก็บ OAuth ได้หลายชุดเป็นไฟล์แยก เช่น `token_waritnan34811.json`; ตรวจชื่อที่มีได้ด้วย `kt404-youtube auth accounts`; คำสั่ง revoke ลบเฉพาะ credential ที่ผูกกับโปรไฟล์ปัจจุบัน

## Maintenance รายสัปดาห์

`maintenance refresh` ตรวจว่า OAuth ยังใช้ได้และ channel ID ยังเป็นช่องที่บัญชีนี้เป็นเจ้าของ, อัปเดต YouTube API records ที่ครบกำหนด และลบข้อมูลที่หมดอายุ ห้ามใช้ scheduler เรียก `upload` หรือเฝ้าดู `vdo`

ตั้ง Windows Task Scheduler ด้วยผู้ใช้ Windows คนเดียวกับที่เก็บ OAuth token:

1. เลือก **Create Task** ชื่อ `Katy404 YouTube API maintenance` ให้ทำงานสัปดาห์ละครั้งในเวลาที่เครื่องเปิดอยู่ และเปิดการตั้งค่าให้ Task Scheduler เริ่มงานโดยเร็วหากพลาดเวลาเริ่มตามกำหนด
2. เลือก **Run only when user is logged on** เพื่อให้โปรแกรมเข้าถึง `token_waritnan34811.json` และโปรไฟล์ของบัญชีเจ้าของ
3. Action: Start a program; Program ใช้พาธเต็มของ `kt404-youtube.exe` ใน environment ที่ติดตั้ง เช่น `<project>\.venv\Scripts\kt404-youtube.exe`; Arguments คือ `maintenance refresh`; Start in คือโฟลเดอร์โปรเจกต์
4. เพิ่ม trigger ตอนผู้ใช้ sign in เพื่อให้ตรวจข้อมูลหลังเครื่องกลับมาออนไลน์ อย่าตั้ง trigger แบบ file watcher หรือเพิ่มพาธวิดีโอ/คำสั่ง `upload` ใน task

maintenance ล้าง resumable session URL ที่ไม่ได้ใช้งาน 30 วัน แล้วให้การอัปโหลดครั้งถัดไปเริ่ม session ใหม่ หาก OAuth ถูกเพิกถอนหรือช่องไม่อยู่ในบัญชีแล้ว maintenance หยุด ลบข้อมูล API-derived ของช่อง และล้าง channel ID/pilot ID ในโปรไฟล์เพื่อไม่ให้ประมวลผลต่อด้วยข้อมูลเก่า

## ผลตรวจโฟลเดอร์ที่ผู้ใช้อนุมัติ

ตรวจแบบอ่านอย่างเดียวเมื่อ 2026-09-26 ที่ `G:\My Drive\Projects\Katy404\2026-09\vdo`:

- ไฟล์ระดับบนสุด: MOV 24 ไฟล์, JPG 24 ไฟล์
- scanner จับคู่ MOV/JPG ได้ 24 คู่, พบ issue 0 รายการ และอ่านเฉพาะโฟลเดอร์ `vdo` ไม่ไล่ parent folder
- `ffprobe` อ่านคลิปได้ครบ: แนวนอน 12, แนวตั้ง 12
- ไม่มี OAuth, YouTube API request หรือ upload ในการตรวจนี้

นี่เป็น **asset inventory** ไม่ใช่ CLI metadata dry-run เต็ม; ยังไม่ได้ตรวจ title/description/tags เทียบกับโปรไฟล์จริง เพราะเจ้าของยังไม่ได้ตั้ง category, description, Made for Kids, synthetic-media และ Official Artist Channel ในโปรไฟล์ ต้องตั้งค่า/ตรวจข้อเท็จจริงเหล่านี้ก่อน dry-run เต็ม

คลิปนำร่องและ batch ยังไม่ได้อัปโหลด: ขั้นต่อไปต้องมี Desktop OAuth JSON ที่เจ้าของเลือกจาก Google Cloud, ตั้งโปรไฟล์/ยืนยันค่า metadata ตามข้อเท็จจริง, แล้วรัน dry-run เต็มและ Private pilot; batch เต็มต้องรอเจ้าของตรวจ pilot แล้วอนุมัติ video ID ก่อน
