# ติดตั้งโปรเจกต์บนเครื่องใหม่หลัง `git clone`

คู่มือนี้ครอบคลุมการติดตั้งบน Windows ตั้งแต่ clone repo จนถึงการเตรียม OAuth และโปรไฟล์ช่อง การติดตั้งหรือ OAuth ไม่ได้สั่งอัปโหลดวิดีโอ

## อะไรอยู่ใน Git และอะไรต้องเตรียมเอง

โปรไฟล์แต่ละช่องเก็บใน `profiles/<ชื่อ>.json`; การติดตั้งรุ่นเดิมที่ยังไม่มีโฟลเดอร์นี้ใช้ `profile.json` ได้. โปรไฟล์เก็บ metadata เช่น description, tags, category และ `made_for_kids: false`; OAuth credentials แยกเก็บตาม account และไม่อยู่ในไฟล์โปรไฟล์. ไฟล์ต่อไปนี้ถูกกันออกจาก Git และจะไม่มากับ clone:

- `client_secrets.json`: OAuth Desktop JSON ที่เจ้าของดาวน์โหลดจาก Google Cloud
- `token_<account>.json`: OAuth credential ของแต่ละบัญชี Google
- `state.sqlite3`: ประวัติงานและ hash ที่ใช้ป้องกันการส่งคลิปซ้ำ
- `.venv`: Python environment ของเครื่องเดิม

ดังนั้น clone มี source และ preset แต่ยังไม่มี credentials หรือประวัติการอัปโหลด ต้องสร้าง virtual environment ใหม่ วาง OAuth JSON ลงในโฟลเดอร์โปรเจกต์ และทำ OAuth บนเครื่องนั้นเอง อย่าส่ง credentials หรือ token ขึ้น Git

โปรไฟล์ใช้ path `client_secrets.json` แบบ relative กับ root ของโปรเจกต์ รันคำสั่งจาก root ตามตัวอย่างด้านล่างเพื่อให้ path นี้ชี้ไปยังไฟล์ใน clone ปัจจุบัน

## 1. Clone repo

ติดตั้ง Git และ Python 3.13 หรือ 3.14 ก่อน จาก PowerShell ไปยังโฟลเดอร์ที่ต้องการเก็บโปรเจกต์ แล้วรัน:

```powershell
git clone git@github.com:pong34811/agent-upload-social.git
Set-Location .\agent-upload-social
```

ถ้าใช้ HTTPS แทน SSH:

```powershell
git clone https://github.com/pong34811/agent-upload-social.git
Set-Location .\agent-upload-social
```

ยืนยันว่าอยู่ที่ root ของ repo และ Python launcher มองเห็น Python รุ่นที่รองรับ:

```powershell
git status --short --branch
py -0p
```

## 2. สร้าง environment และติดตั้งโปรแกรม

ใช้ Python 3.13:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

หากต้องการรันชุดทดสอบภายหลัง ให้ติดตั้ง optional dependency เพิ่มด้วย `.\.venv\Scripts\python.exe -m pip install -e ".[test]"`

ติดตั้ง FFmpeg ที่มี `ffprobe.exe` และเพิ่มตำแหน่ง executable ใน `PATH` จากนั้นเปิด PowerShell ใหม่และตรวจ:

```powershell
ffprobe -version
.\.venv\Scripts\kt404-youtube.exe --help
```

ถ้า `ffprobe` ไม่พบ ให้ติดตั้ง/ตั้ง `PATH` ให้ถูกก่อนตรวจหรืออัปโหลดคลิป

## 3. วาง OAuth Desktop JSON ใน clone

ดาวน์โหลด Desktop OAuth JSON จาก Google Cloud project ที่เจ้าของเลือก แล้วคัดลอกไฟล์ไว้ที่:

```text
<โฟลเดอร์ที่ clone>\agent-upload-social\client_secrets.json
```

ตัวอย่างเมื่อ clone ไว้ใน Desktop:

```text
C:\Users\warit\Desktop\agent-upload-social\client_secrets.json
```

ตรวจว่าไฟล์เป็น JSON แบบ Desktop/Installed (`installed` object มี `client_id` และ `client_secret`) อย่าแก้ค่าภายในไฟล์เอง ไฟล์นี้ถูก `.gitignore` กันไว้อยู่แล้ว

## 4. OAuth

ไม่ต้องสร้าง token แยกก่อนอัปโหลด. เมื่อรัน `upload` ครั้งแรก โปรแกรมจะเปิด Google OAuth เองและบันทึก credential ใน account `waritnan34811` ตามโปรไฟล์. OAuth JSON และ token เป็นข้อมูลเฉพาะเครื่องและไม่ถูก clone จาก Git

คำสั่ง `auth token` ใช้เฉพาะเมื่อต้องการเชื่อมบัญชีก่อนเริ่มอัปโหลด

## 5. เลือกหรือตั้งโปรไฟล์ช่อง

แสดงรายการโปรไฟล์และค่าโปรไฟล์โดยไม่แสดง OAuth token:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile list
.\.venv\Scripts\kt404-youtube.exe profile show --profile armigon
```

เมื่อมีหลายโปรไฟล์ ให้ระบุ `--profile <ชื่อ>` ในแต่ละคำสั่งที่ใช้งานช่อง. ถ้ามีไฟล์แยกเพียงไฟล์เดียว โปรแกรมเลือกให้อัตโนมัติได้; ถ้า `profile.json` เป็นอีกช่องหนึ่ง โปรแกรมจะแสดงช่องนั้นใน `profile list` ด้วยชื่อ OAuth account

ถ้ามีเฉพาะไฟล์ legacy `profile.json` ให้ใช้ `profile show` โดยไม่ต้องส่ง `--profile`.

หากต้องตั้งโปรไฟล์สำหรับช่องอื่น คำสั่งนี้จะแสดงช่องที่บัญชี OAuth จัดการได้และบันทึกค่าประจำช่อง:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile setup --profile new-channel --client-secrets ".\client_secrets.json" --oauth-account new-account
```

เลือกช่องที่ตรงกับชื่อโปรไฟล์ แล้วกรอก metadata และค่าที่ YouTube ต้องใช้ตามข้อเท็จจริง. หากโปรไฟล์ชื่อนั้นมีอยู่แล้ว ให้เพิ่ม `--replace-existing` เพื่อเก็บสำเนาก่อนแทนค่า. ไม่ต้องกรอกสถานะ audit ก่อนอัปโหลด; ค่า `api_audit_passed` เดิมไม่มีผลต่อการส่งคำขอ. Google อาจจำกัด project ที่ยังไม่ผ่านการตรวจสอบให้วิดีโอเป็น Private; โปรแกรมใช้ผลจริงจาก API และอ่านตาราง `private` + `publishAt` กลับก่อนรายงานสำเร็จ

## 6. อัปโหลด

ระบุโฟลเดอร์และช่องในคำสั่งเดียว; uploader ตรวจไฟล์ก่อนส่งให้อยู่แล้ว:

```powershell
.\.venv\Scripts\kt404-youtube.exe upload --profile armigon --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>"
```

ถ้าต้องการดูผลก่อนส่ง ใช้ `dry-run` เพิ่มเติมได้ แต่ไม่จำเป็น. รูปแบบชื่อไฟล์วิดีโอและภาพปกที่รองรับ:

```text
vdo_ชื่อคลิป.mov          vdo_ชื่อคลิป.jpg
vdo_ชื่อคลิป_9x16.mov     vdo_ชื่อคลิป_9x16.jpg
```

รองรับวิดีโอ `.mp4`/`.mov` และภาพ `.jpg`, `.jpeg` หรือ `.png`; ชื่อ `_9x16` ใช้กับคู่ไฟล์แนวตั้ง ส่วนไฟล์แนวนอนใช้ชื่อฐานโดยไม่มี suffix นี้. `dry-run` อ่านเฉพาะไฟล์ระดับบนสุดในโฟลเดอร์ที่ระบุ ไม่ค้นหาโฟลเดอร์ย่อย:

```powershell
.\.venv\Scripts\kt404-youtube.exe dry-run --profile armigon --folder "<โฟลเดอร์คลิป>" --channel "<handle หรือ channel ID>"
```

ทั้ง `upload` และ `dry-run` อ่านเฉพาะไฟล์ระดับบนสุดของโฟลเดอร์ที่ระบุ

ถ้าไม่มี OAuth credential โปรแกรมจะเปิด Google OAuth ระหว่างคำสั่ง upload แล้วทำงานต่อหลังยืนยันสำเร็จ ดูตารางการเผยแพร่ได้ใน [คู่มือปฏิบัติงาน](operations.md)

## ที่เก็บข้อมูลในเครื่อง

- `profiles/<ชื่อ>.json`: preset และค่าประจำช่อง; `profile.json` เป็น fallback สำหรับการติดตั้งรุ่นเดิม
- `client_secrets.json`: OAuth Desktop JSON เฉพาะเครื่อง; ถูก ignore
- `token_<account>.json`: OAuth credential เฉพาะเครื่อง; ถูก ignore
- `state.sqlite3`: job state เฉพาะเครื่อง; ถูก ignore และจะถูกสร้างใหม่เมื่อเริ่มทำงาน
- `profile.json.backup-<timestamp>`: สำเนาโปรไฟล์ก่อนใช้ `profile setup --replace-existing`; ถูก ignore

การ clone บนเครื่องใหม่ไม่ได้ย้าย token หรือฐานข้อมูล state มาด้วย หากต้องการย้ายประวัติ job/hash เดิม ให้คัดลอก `state.sqlite3` ด้วยวิธีที่เจ้าของควบคุมและปิดโปรแกรมก่อนคัดลอก โดยห้าม commit ไฟล์นี้

## แหล่งอ้างอิง

- [Google Cloud: OAuth consent screen และสถานะ Testing](https://support.google.com/cloud/answer/15549945?hl=en)
- [YouTube Data API quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube API compliance audit และ quota extension](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)
- [YouTube resumable upload protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
