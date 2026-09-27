# Katy404 YouTube Upload Agent

เครื่องมือ CLI ในเครื่อง Windows สำหรับเตรียม metadata และอัปโหลดวิดีโอพร้อม JPG thumbnail ไปยัง YouTube ช่องที่เจ้าของระบุ ปัจจุบันรองรับ YouTube เท่านั้น ไม่มี Facebook/TikTok หรือ backend/cloud hosting ของโปรแกรม; เรียก Google/YouTube API เฉพาะเมื่อเจ้าของยินยอมและสั่งงาน ไม่อ่าน parent folder และไม่เฝ้าดูโฟลเดอร์เพื่ออัปโหลดเอง

## สถานะ

- มีเส้นทางตรวจไฟล์แบบ offline, hash กันส่งซ้ำ, OAuth Desktop, resumable upload, thumbnail retry, Private pilot และคำสั่งลบ/ตรวจอายุข้อมูล
- ต้องมี Desktop OAuth JSON ที่เจ้าของเลือกใช้ และการยืนยันค่าประจำช่องก่อนเริ่มอัปโหลด
- หลัง clone ให้วาง OAuth Desktop JSON เป็น `client_secrets.json` ใน root ของ repo; credentials และ token ไม่ถูกส่งขึ้น Git. ขั้นตอนสำหรับเครื่องใหม่อยู่ใน [คู่มือติดตั้ง](docs/setup.md)

## ติดตั้งและเริ่มต้น

ต้องใช้ Windows, Python 3.13/3.14, Git และ `ffprobe` (ติดตั้งได้จาก FFmpeg). จาก PowerShell:

```powershell
git clone git@github.com:pong34811/agent-upload-social.git
Set-Location .\agent-upload-social
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
ffprobe -version
.\.venv\Scripts\kt404-youtube.exe auth token --client-secrets ".\client_secrets.json" --account waritnan34811
.\.venv\Scripts\kt404-youtube.exe profile show
```

ก่อนรัน OAuth ให้วาง OAuth Desktop JSON ที่เจ้าของเลือกไว้เป็น `client_secrets.json` ใน root ของ repo. `auth token` สร้างหรือตรวจ OAuth credential โดยไม่เรียก YouTube API หรืออัปโหลดวิดีโอ. Clone ได้ preset ใน `profile.json` แต่ต้องเตรียม OAuth JSON/token เองและยืนยันค่าที่ยังขาดตาม [คู่มือติดตั้ง](docs/setup.md)

อ่าน [คู่มือติดตั้ง](docs/setup.md) ก่อนตั้ง Google Cloud/OAuth

## ตรวจคลิปและอัปโหลด

ตรวจไฟล์โดยไม่เชื่อมต่อ YouTube (แทน `<โฟลเดอร์คลิป>` ด้วย path ในเครื่อง):

```powershell
.\.venv\Scripts\kt404-youtube.exe dry-run --folder "<โฟลเดอร์คลิป>" --channel "waritnan34811"
```

เมื่อสั่งอัปโหลดอย่างชัดเจน ครั้งแรกจะทำ Private pilot หนึ่งคลิป:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --folder "<โฟลเดอร์คลิป>" --channel "waritnan34811" --limit 1 --force-private
```

เมื่อสั่ง `upload` หากยังไม่มี OAuth credential โปรแกรมจะเปิดหน้า **local status page** และ Google OAuth ให้เจ้าของลงชื่อเข้าใช้/ยินยอมบนหน้า Google เท่านั้น; หน้าสถานะไม่รับรหัสผ่านและไม่แสดง token หลังบันทึก credential ในไฟล์ของบัญชีที่โปรไฟล์เลือกแล้ว CLI จะตรวจว่าบัญชีนั้นเข้าถึงช่องที่ระบุก่อนเริ่มส่งวิดีโอ

หากต้องการเชื่อมบัญชีและตรวจช่องโดยยังไม่อัปโหลดคลิป ใช้ `auth login --channel "waritnan34811"`; คำสั่งนี้บันทึก credential ในไฟล์ของ OAuth account ที่โปรไฟล์เลือกและจบหลังตรวจช่อง

ตรวจผลใน YouTube Studio แล้วเจ้าของอนุมัติ video ID ก่อน:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile approve-pilot --video-id VIDEO_ID
```

คำสั่งอัปโหลด batch เต็มต้องเป็นคำสั่งแยกจากเจ้าของ:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --folder "<โฟลเดอร์คลิป>" --channel "waritnan34811"
```

ดูคำสั่งลบข้อมูล, revoke OAuth และตั้ง maintenance รายสัปดาห์ใน [คู่มือปฏิบัติงาน](docs/operations.md)

## พื้นที่เก็บข้อมูล

- โปรไฟล์ช่องและ preset: `profile.json` ที่โฟลเดอร์โปรเจกต์
- SQLite job state: `state.sqlite3` ที่โฟลเดอร์โปรเจกต์
- OAuth token ของ account ใน preset `waritnan34811`: `token_waritnan34811.json`; บัญชีอื่นเก็บแยกใน `token_NAME.json`; `.gitignore` กันไฟล์ token ที่ขึ้นต้น `token_` ไม่ให้เข้า Git
- OAuth Desktop JSON: `client_secrets.json` ที่โฟลเดอร์โปรเจกต์; `.gitignore` กันไฟล์ credentials และฐานข้อมูลไม่ให้เข้า Git
- วิดีโอต้นฉบับ/ภาพ JPG ยังคงอยู่ในโฟลเดอร์ที่เจ้าของเลือก

ใช้ Google YouTube Data API v3; ผู้ใช้เป็นผู้เลือก visibility และยืนยัน audience, synthetic media และ metadata ของแต่ละโปรไฟล์
