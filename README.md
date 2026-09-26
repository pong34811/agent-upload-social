# Katy404 YouTube Upload Agent

เครื่องมือ CLI ในเครื่อง Windows สำหรับเตรียม metadata และอัปโหลดวิดีโอพร้อม JPG thumbnail ไปยัง YouTube ช่องที่เจ้าของระบุ ปัจจุบันรองรับ YouTube เท่านั้น ไม่มี Facebook/TikTok หรือ backend/cloud hosting ของโปรแกรม; เรียก Google/YouTube API เฉพาะเมื่อเจ้าของยินยอมและสั่งงาน ไม่อ่าน parent folder และไม่เฝ้าดูโฟลเดอร์เพื่ออัปโหลดเอง

## สถานะ

- มีเส้นทางตรวจไฟล์แบบ offline, hash กันส่งซ้ำ, OAuth Desktop, resumable upload, thumbnail retry, Private pilot และคำสั่งลบ/ตรวจอายุข้อมูล
- ต้องมี Google Cloud Upload Project ใหม่ที่ project ID ขึ้นต้นด้วย `mfk110`, Desktop OAuth JSON, privacy policy ที่เผยแพร่แล้ว และการยืนยันค่าประจำช่องก่อนเริ่ม API
- ไฟล์ `D:\agent-upload-social\client_secrets.json` ที่มีอยู่เป็น OAuth client คนละโปรเจกต์กับเส้นทางอนุมัติของ uploader นี้ อย่าใช้หรือคัดลอกไฟล์เดิมไปเป็น production client; ให้ดาวน์โหลด JSON ใหม่จากโปรเจกต์ `mfk110` ตาม [คู่มือติดตั้ง](docs/setup.md)
- privacy policy และ terms ใน repo เป็นฉบับร่าง มี placeholder สำหรับช่องทางติดต่อจริง จึงยังห้ามนำ URL ไปใช้ OAuth จนกว่าเจ้าของจะเติมข้อมูลและเผยแพร่

## ติดตั้งและเริ่มต้น

ต้องใช้ Windows, Python 3.13/3.14, Git และ `ffprobe` (ติดตั้งได้จาก FFmpeg). จาก PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\Activate.ps1
kt404-youtube profile setup
kt404-youtube profile show
kt404-youtube profile accept-policy
```

อ่าน [คู่มือติดตั้ง](docs/setup.md) ก่อนตั้ง Google Cloud/OAuth และ [นโยบายความเป็นส่วนตัวฉบับร่าง](docs/privacy-policy.md) ก่อนเผยแพร่

## ตรวจคลิปและอัปโหลด

ตรวจไฟล์โดยไม่เชื่อมต่อ YouTube:

```powershell
kt404-youtube dry-run --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

เมื่อสั่งอัปโหลดอย่างชัดเจน ครั้งแรกจะทำ Private pilot หนึ่งคลิป:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404" --limit 1 --force-private
```

ตรวจผลใน YouTube Studio แล้วเจ้าของอนุมัติ video ID ก่อน:

```powershell
kt404-youtube profile approve-pilot --video-id VIDEO_ID
```

คำสั่งอัปโหลด batch เต็มต้องเป็นคำสั่งแยกจากเจ้าของ:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "Katy404"
```

ดูคำสั่งลบข้อมูล, revoke OAuth และตั้ง maintenance รายสัปดาห์ใน [คู่มือปฏิบัติงาน](docs/operations.md)

## พื้นที่เก็บข้อมูล

- โปรไฟล์และ SQLite job state: `%LOCALAPPDATA%\Katy404\YouTubeUploader\`
- OAuth token: Windows Credential Manager; ไม่สร้าง `token.json`
- OAuth Desktop JSON: เก็บใน `%LOCALAPPDATA%\Katy404\YouTubeUploader\` และอย่าใส่ใน Git หรือ Google Drive
- วิดีโอต้นฉบับ/ภาพ JPG ยังคงอยู่ในโฟลเดอร์ที่เจ้าของเลือก

ใช้ Google YouTube Data API v3 ตาม Terms of Service และ Developer Policies ที่ลิงก์ใน privacy/terms; ผู้ใช้เป็นผู้เลือก visibility และยืนยัน rights, audience, synthetic media และ metadata ของแต่ละโปรไฟล์
