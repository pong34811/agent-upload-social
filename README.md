# YouTube Upload Agent (`yt-upload`)

เครื่องมือ CLI บน Windows ให้ agent (หรือเจ้าของช่อง) อัปโหลดคลิป `.mp4`/`.mov` พร้อมภาพปกลง YouTube ช่องที่ผู้ใช้ระบุ ทีละโฟลเดอร์ตามที่ผู้ใช้ส่งมา รองรับหลายช่องผ่านโปรไฟล์ `profiles/<ชื่อ>.json`. ใช้ YouTube Data API v3 เท่านั้น ไม่มี backend/cloud ไม่อ่านโฟลเดอร์ข้างเคียง และไม่เฝ้าดูโฟลเดอร์เพื่ออัปโหลดเอง

- ตรวจไฟล์ก่อนส่งทุกครั้ง, กันอัปโหลดซ้ำด้วย hash และส่งต่อจากจุดเดิมเมื่อการเชื่อมต่อขัดข้อง
- ตั้งเวลาเผยแพร่ด้วย `private` + `publishAt` แล้วอ่านกลับจาก API ก่อนรายงานสำเร็จ
- `--json` ทุกคำสั่ง ให้ agent อ่านผลได้แน่นอน (stdout = JSON หนึ่งก้อน, ข้อความอื่นไป stderr)
- คำสั่งเดิม `kt404-youtube` ยังใช้ได้และเรียกโปรแกรมเดียวกัน

## ติดตั้ง

ต้องใช้ Windows, Python 3.13/3.14, Git และ `ffprobe` (จาก FFmpeg). จาก PowerShell:

```powershell
git clone git@github.com:pong34811/agent-upload-social.git
Set-Location .\agent-upload-social
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
ffprobe -version
```

วาง OAuth Desktop JSON ที่ `client_secrets.json` ใน root ของ repo แล้วอ่าน [คู่มือติดตั้ง](docs/setup.md) ก่อนตั้ง Google Cloud/OAuth

## อัปโหลด

```powershell
.\.venv\Scripts\yt-upload.exe profile list
.\.venv\Scripts\yt-upload.exe upload --profile "<ชื่อโปรไฟล์>" --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>"
```

`upload` ตรวจไฟล์ระดับบนสุดในโฟลเดอร์ให้เองก่อนส่ง; ใช้ `dry-run` (คำสั่งเดียวกัน) เฉพาะเมื่ออยากดูผลก่อนโดยไม่เชื่อมต่อ YouTube. เมื่อมีหลายโปรไฟล์ต้องระบุ `--profile` ทุกครั้ง

ตั้งเวลา batch โดยจับคู่คลิปแนวนอน/แนวตั้งตามชื่อไฟล์ วันละคู่ เวลาเดียวกัน (ต้องมี UTC offset):

```powershell
.\.venv\Scripts\yt-upload.exe upload --profile "<ชื่อโปรไฟล์>" --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>" --schedule-from "2026-10-01T07:30:00+07:00"
```

ตั้งเวลาวิดีโอ Private ที่อัปโหลดแล้ว:

```powershell
.\.venv\Scripts\yt-upload.exe schedule --profile "<ชื่อโปรไฟล์>" --video-id VIDEO_ID --publish-at "2026-10-01T07:30:00+07:00"
```

เมื่อยังไม่มี OAuth credential โปรแกรมจะเปิด **local status page** และ Google OAuth ให้เจ้าของยินยอมบนหน้า Google เท่านั้น; หน้าสถานะไม่รับรหัสผ่านและไม่แสดง token แล้วตรวจว่าบัญชีนั้นเข้าถึงช่องที่ระบุก่อนเริ่มส่ง. ค่า `api_audit_passed` เดิมไม่ใช่ด่านในเครื่อง; ถ้า YouTube จำกัด project หรือปฏิเสธคำขอ โปรแกรมรายงานผลจริงและหยุด

คู่มือสำหรับ agent: [.agents/skills/youtube-upload/SKILL.md](.agents/skills/youtube-upload/SKILL.md). รูปแบบ JSON, hashtag ของคลิปแนวตั้ง และคำสั่งดูแล OAuth อยู่ใน [คู่มือปฏิบัติงาน](docs/operations.md)

## โครงสร้างโค้ด (`src/yt_uploader/`)

| โมดูล | หน้าที่ |
| --- | --- |
| `cli/` | parser, `CliApp` และคำสั่งแยกกลุ่ม (`commands/`), การแสดงผล text/JSON (`output.py`) |
| `pipeline/` | `preflight.py` ตรวจโฟลเดอร์และเตรียมงาน, `upload.py` อัปโหลดทีละงานและหยุดคิวเมื่อไม่ปลอดภัย, `schedule.py` ตารางเผยแพร่ |
| `youtube/` | `client.py` YouTube API, `transport.py` resumable upload, `errors.py` |
| `auth/` | token ต่อบัญชี, Google OAuth, หน้า status page, การจับคู่ช่อง |
| `media/` | สแกนไฟล์ + จับคู่ปก, `ffprobe`, สร้าง title/description/hashtag |
| `config/`, `jobs/` | โปรไฟล์ช่อง และ SQLite job state |

## ข้อมูลในเครื่อง (ไม่อยู่ใน Git)

- `profiles/<ชื่อ>.json`: ค่าประจำช่อง (อยู่ใน Git); `profile.json` ใช้ได้กับการติดตั้งรุ่นเดิม
- `client_secrets.json`, `token_<account>.json`: OAuth ของเครื่องนี้; ถูก ignore
- `state.sqlite3`: job state และ hash กันส่งซ้ำ; ถูก ignore
- `archive/`: สำเนาเก่าที่เก็บไว้เผื่อย้อนดู; ถูก ignore และโปรแกรมไม่อ่าน
- วิดีโอต้นฉบับและภาพปกยังอยู่ในโฟลเดอร์ที่เจ้าของเลือก
