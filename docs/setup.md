# ติดตั้งโปรเจกต์บนเครื่องใหม่หลัง `git clone`

คู่มือนี้ครอบคลุมการติดตั้งบน Windows ตั้งแต่ clone repo จนถึงการเตรียม OAuth และโปรไฟล์ช่อง การติดตั้งหรือ OAuth ไม่ได้สั่งอัปโหลดวิดีโอ

## อะไรอยู่ใน Git และอะไรต้องเตรียมเอง

เมื่อ clone repo จะได้ source code, คู่มือ และ preset ช่องใน `profile.json` รวมถึงการตั้งค่าที่เจ้าของบันทึกไว้ เช่น description, tags, category และ `made_for_kids: false` ไฟล์ต่อไปนี้ถูกกันออกจาก Git และจะไม่มากับ clone:

- `client_secrets.json`: OAuth Desktop JSON ที่เจ้าของดาวน์โหลดจาก Google Cloud
- `token_<account>.json`: OAuth credential ของแต่ละบัญชี Google
- `state.sqlite3`: ประวัติงานและ hash ที่ใช้ป้องกันการส่งคลิปซ้ำ
- `.venv`: Python environment ของเครื่องเดิม

ดังนั้น clone มี source และ preset แต่ยังไม่มี credentials หรือประวัติการอัปโหลด ต้องสร้าง virtual environment ใหม่ วาง OAuth JSON ลงในโฟลเดอร์โปรเจกต์ และทำ OAuth บนเครื่องนั้นเอง อย่าส่ง credentials หรือ token ขึ้น Git

`profile.json` ที่ commit ไว้ใช้ path `client_secrets.json` แบบ relative กับ root ของโปรเจกต์ รันคำสั่งจาก root ตามตัวอย่างด้านล่างเพื่อให้ path นี้ชี้ไปยังไฟล์ใน clone ปัจจุบัน

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

## 4. สร้าง OAuth credential

ใน preset ปัจจุบัน `profile.json` ระบุ OAuth account label เป็น `waritnan34811` จึงต้องใช้ label เดียวกันเพื่อให้ uploader เจอ credential นั้น:

```powershell
.\.venv\Scripts\kt404-youtube.exe auth token --client-secrets ".\client_secrets.json" --account waritnan34811
```

ครั้งแรกโปรแกรมจะเปิด Google OAuth ใน browser ให้เจ้าของเลือกบัญชีและยินยอม scope ที่แสดง หลังสำเร็จจะสร้าง `token_waritnan34811.json` ใน root ของโปรเจกต์ คำสั่งนี้ไม่เรียก YouTube API และไม่อัปโหลดวิดีโอ ถ้าบัญชีนี้มี credential ที่ยังใช้ได้ โปรแกรมจะนำกลับมาใช้โดยไม่เปิด browser ซ้ำ

ดูเฉพาะชื่อบัญชีที่มี credential โดยไม่แสดง token ได้ด้วย:

```powershell
.\.venv\Scripts\kt404-youtube.exe auth accounts
```

หากเชื่อมบัญชี Google อื่น ให้ตั้ง account label ใหม่และเลือก label เดียวกันตอนตั้งโปรไฟล์ เช่น:

```powershell
.\.venv\Scripts\kt404-youtube.exe auth token --client-secrets ".\client_secrets.json" --account channel2
```

OAuth JSON และ token เป็นข้อมูลเฉพาะเครื่องและไม่ถูก clone จาก Git

## 5. ตรวจ preset และกรอกค่าที่ยังขาด

แสดง preset ปัจจุบันโดยไม่แสดง OAuth token:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile show
```

โปรไฟล์ที่อยู่ใน repo มี preset ของช่อง `waritnan34811` พร้อม description, tags, category `22` และ Made for Kids = `no` ตามที่เจ้าของระบุ ค่า privacy, synthetic media และ Official Artist Channel ต้องยืนยันตามข้อเท็จจริงก่อนใช้อัปโหลด; ห้ามเดาหรือรับรองแทนเจ้าของ

ถ้าต้องกรอก/ยืนยันข้อมูลเหล่านี้ผ่าน CLI ให้รันคำสั่งตั้งค่าใหม่ คำสั่งนี้เรียก YouTube API เพื่อแสดงช่องที่บัญชี OAuth จัดการได้ แต่ไม่อัปโหลดคลิป และจะสำรอง `profile.json` เดิมก่อนแทนที่:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile setup --client-secrets ".\client_secrets.json" --oauth-account waritnan34811 --replace-existing
```

เลือกช่องที่ถูกต้อง แล้วกรอก metadata และ declarations ตามความจริง ค่า Unlisted/Public ต้องอาศัยสถานะ YouTube API audit ที่ผ่านจริง; อย่าตั้งสถานะ audit จากการผ่าน OAuth เพียงอย่างเดียว

ตรวจค่าที่บันทึกไว้อีกครั้งด้วย `profile show`. สำหรับการแก้เฉพาะค่า privacy มีคำสั่ง:

```powershell
.\.venv\Scripts\kt404-youtube.exe profile set-privacy private
```

## 6. ตรวจคลิปก่อนสั่งอัปโหลด

ติดตั้ง/เชื่อม Google Drive หรือคัดลอกคลิปกับ JPG ไว้ในโฟลเดอร์ที่ต้องการ ตรวจชื่อและไฟล์คู่ตามรูปแบบที่โปรแกรมรองรับ ดูรายละเอียดใน [คู่มือปฏิบัติงาน](operations.md). จากนั้นแทน `<โฟลเดอร์คลิป>` ด้วย path จริง:

```powershell
.\.venv\Scripts\kt404-youtube.exe dry-run --folder "<โฟลเดอร์คลิป>" --channel "waritnan34811"
```

`dry-run` เป็นการตรวจไฟล์แบบ offline และอ่านเฉพาะไฟล์ระดับบนสุดของโฟลเดอร์ที่ระบุ ตรวจจำนวนคลิป ชื่อไฟล์ วิดีโอ/ภาพปกคู่กัน และรายการที่ต้องแก้ให้เรียบร้อยก่อนส่งคำสั่ง `upload`

การติดตั้ง, clone, สร้าง OAuth หรือ dry-run ไม่ได้อัปโหลดคลิป การอัปโหลดต้องเป็นคำสั่งแยกที่เจ้าของสั่งอย่างชัดเจน หากยังไม่มี pilot ที่เจ้าของอนุมัติ โปรแกรมเริ่มด้วย Private pilot หนึ่งคลิป หลังเจ้าของตรวจใน YouTube Studio และอนุมัติ video ID แล้ว จึงสั่ง batch เต็มแยกอีกครั้ง ดูลำดับเต็มใน [คู่มือปฏิบัติงาน](operations.md)

## ที่เก็บข้อมูลในเครื่อง

- `profile.json`: preset และค่าประจำช่องที่อยู่ใน Git
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
