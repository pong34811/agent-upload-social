# Katy404 YouTube Upload Agent

เครื่องมือ CLI ในเครื่อง Windows สำหรับเตรียม metadata และอัปโหลดวิดีโอ `.mp4`/`.mov` พร้อมภาพปกไปยัง YouTube ช่องที่เจ้าของระบุ ปัจจุบันรองรับ YouTube เท่านั้น ไม่มี Facebook/TikTok หรือ backend/cloud hosting ของโปรแกรม; เรียก Google/YouTube API เฉพาะเมื่อเจ้าของยินยอมและสั่งงาน ไม่อ่าน parent folder และไม่เฝ้าดูโฟลเดอร์เพื่ออัปโหลดเอง

## สถานะ

- ตรวจไฟล์ให้อัตโนมัติก่อนส่ง, กันอัปโหลดซ้ำ และส่งต่อได้เมื่อการเชื่อมต่อขัดข้อง
- ตั้งเวลาเผยแพร่บน YouTube ได้จากคำสั่งที่เจ้าของเรียก โดยวิดีโอจะเป็น Private จนถึงเวลาที่กำหนด
- เก็บค่าช่องแยกใน `profiles/<ชื่อ>.json`; ระบุ `--profile <ชื่อ>` เมื่อมีหลายช่อง และรองรับ `profile.json` รุ่นเดิมด้วย หากเป็นช่องแยกจากโปรไฟล์อื่นจะแสดงใน `profile list` ด้วย
- หลัง clone ให้วาง OAuth Desktop JSON เป็น `client_secrets.json` ใน root ของ repo; credentials และ token ไม่ถูกส่งขึ้น Git. ขั้นตอนสำหรับเครื่องใหม่อยู่ใน [คู่มือติดตั้ง](docs/setup.md)

## ติดตั้งและเริ่มต้น

ต้องใช้ Windows, Python 3.13/3.14, Git และ `ffprobe` (ติดตั้งได้จาก FFmpeg). จาก PowerShell:

```powershell
git clone git@github.com:pong34811/agent-upload-social.git
Set-Location .\agent-upload-social
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
ffprobe -version
```

วาง OAuth Desktop JSON ที่ `client_secrets.json` ใน root ของ repo. ดูโปรไฟล์ที่มีด้วย `profile list`; เมื่อมีหลายช่องให้ระบุชื่อโปรไฟล์ในทุกคำสั่งที่ใช้งานช่อง เช่น `--profile armigon`. หากยังไม่มี credential โปรแกรมจะเปิด Google OAuth ให้เอง.

อ่าน [คู่มือติดตั้ง](docs/setup.md) ก่อนตั้ง Google Cloud/OAuth

## ตรวจคลิปและอัปโหลด

สั่งอัปโหลดทั้งโฟลเดอร์ด้วยคำสั่งเดียว; `upload` ตรวจไฟล์ให้เองก่อนเริ่มส่ง:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --profile "<ชื่อโปรไฟล์>" --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>"
```

ใช้ `dry-run` เฉพาะเมื่อต้องการตรวจล่วงหน้าโดยไม่เชื่อมต่อ YouTube:

```powershell
.\.venv\Scripts\kt404-youtube.exe dry-run --profile "<ชื่อโปรไฟล์>" --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>"
```

เมื่อสั่ง `upload` หากยังไม่มี OAuth credential โปรแกรมจะเปิดหน้า **local status page** และ Google OAuth ให้เจ้าของลงชื่อเข้าใช้/ยินยอมบนหน้า Google เท่านั้น; หน้าสถานะไม่รับรหัสผ่านและไม่แสดง token หลังบันทึก credential ในไฟล์ของบัญชีที่โปรไฟล์เลือกแล้ว CLI จะตรวจว่าบัญชีนั้นเข้าถึงช่องที่ระบุก่อนเริ่มส่งวิดีโอ

คู่มือสำหรับ agent อยู่ที่ [.agents/skills/kt404-youtube-upload/SKILL.md](.agents/skills/kt404-youtube-upload/SKILL.md). คำสั่งดูแล OAuth และข้อมูลในเครื่องอยู่ใน [คู่มือปฏิบัติงาน](docs/operations.md)

### ตั้งเวลาเผยแพร่

การตั้งเวลาส่ง `private` + `publishAt` ผ่าน YouTube API โดยตรง; เวลาต้องมี UTC offset และอยู่ในอนาคต โปรแกรมอ่านสถานะกลับจาก API เพื่อยืนยันช่อง, privacy และเวลา ก่อนรายงานสำเร็จ หาก OAuth ยังไม่มี scope สำหรับตั้งเวลา คำสั่ง batch จะเปิด Google OAuth ให้ยืนยันเอง

โปรแกรมไม่ใช้ค่า `api_audit_passed` ในเครื่องเป็นด่านก่อนเรียก API และไม่เปลี่ยนค่านี้เอง Google อาจจำกัดวิดีโอจาก API project ที่ยังไม่ผ่านการตรวจสอบให้เป็น Private ตามข้อกำหนดของ [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert); หาก API ปฏิเสธหรือไม่ยืนยันตาราง โปรแกรมจะรายงานผลจริงและหยุด การยืนยันตารางในปัจจุบันยังไม่ใช่หลักฐานว่าเผยแพร่แล้วในอนาคต

ตั้งเวลาให้วิดีโอ Private ที่โปรแกรมจัดการไว้แล้ว:

```powershell
.\.venv\Scripts\kt404-youtube.exe schedule --profile "<ชื่อโปรไฟล์>" --video-id VIDEO_ID --publish-at "2026-10-01T07:30:00+07:00"
```

ตั้งเวลา batch โดยจับคู่ไฟล์แนวนอนและแนวตั้งที่เรียงตามชื่อไฟล์ วันละหนึ่งคู่ เวลาเดียวกัน:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --profile "<ชื่อโปรไฟล์>" --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>" --schedule-from "2026-10-01T07:30:00+07:00"
```

โหมดนี้ตรวจไฟล์ทั้งหมดก่อนเริ่ม, ปฏิเสธวิดีโอจัตุรัสหรือจำนวนแนวนอน/แนวตั้งไม่เท่ากัน, และไม่ใช้ `--limit`/`--force-private`; คลิปที่อัปโหลดครบอยู่แล้วจะถูกตั้งเวลาผ่าน API โดยไม่อัปโหลดซ้ำ

## พื้นที่เก็บข้อมูล

- โปรไฟล์ช่อง: `profiles/<ชื่อ>.json`; ใช้ `profile list` เพื่อดูชื่อ และ `profile.json` เป็นค่าเริ่มต้นสำหรับการติดตั้งรุ่นเดิมที่ยังไม่มีไฟล์แยก
- SQLite job state: `state.sqlite3` ที่โฟลเดอร์โปรเจกต์
- OAuth token ของ account ใน preset `waritnan34811`: `token_waritnan34811.json`; บัญชีอื่นเก็บแยกใน `token_NAME.json`; `.gitignore` กันไฟล์ token ที่ขึ้นต้น `token_` ไม่ให้เข้า Git
- OAuth Desktop JSON: `client_secrets.json` ที่โฟลเดอร์โปรเจกต์; `.gitignore` กันไฟล์ credentials และฐานข้อมูลไม่ให้เข้า Git
- วิดีโอต้นฉบับ/ภาพ JPG ยังคงอยู่ในโฟลเดอร์ที่เจ้าของเลือก

ใช้ Google YouTube Data API v3; ผู้ใช้เป็นผู้เลือก visibility, audience, synthetic media และ metadata ของแต่ละโปรไฟล์
