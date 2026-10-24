# คู่มือใช้งาน

## อัปโหลด

คำสั่ง `upload` ตรวจไฟล์ระดับบนสุดในโฟลเดอร์ที่เลือกก่อนเริ่มส่ง, จับคู่ MOV/JPG, อ่านวิดีโอด้วย `ffprobe`, เติม metadata จากโปรไฟล์ที่เลือก และกันไฟล์ซ้ำด้วย hash

```powershell
yt-upload upload --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

ใช้ `dry-run` เฉพาะเมื่อต้องการดูผลตรวจโดยยังไม่เชื่อมต่อ YouTube:

```powershell
yt-upload dry-run --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

คำสั่งตรวจเฉพาะไฟล์ระดับบนสุด รองรับวิดีโอ `.mp4`/`.mov` และจับคู่กับภาพชื่อฐานเดียวกัน (`.jpg`, `.jpeg` หรือ `.png`), อ่านข้อมูลวิดีโอด้วย `ffprobe`, คำนวณ hash เพื่อกันส่งซ้ำ และแสดงไฟล์ที่ต้องแก้ ไม่มี OAuth หรือ request ไป YouTube ในขั้นนี้. ไม่ต้องอนุมัติแยกก่อน batch; ถ้าไฟล์ผิดพลาดให้แก้ไฟล์ต้นทางก่อนลองใหม่

## ผลแบบ JSON สำหรับ agent

เติม `--json` ท้ายคำสั่งใดก็ได้ เช่น `yt-upload upload --profile katy404 --folder "<โฟลเดอร์>" --channel "<ช่อง>" --json`. stdout จะเป็น JSON หนึ่งก้อน ส่วนข้อความความคืบหน้าและข้อผิดพลาดภาษาไทยไป stderr:

```json
{
  "ok": false,
  "exit_code": 1,
  "command": "upload",
  "profile": "katy404",
  "channel": {"id": "UC...", "name": "KATY_404"},
  "privacy_status": "private",
  "summary": {"ready": 0, "uploaded": 1, "scheduled": 0, "skipped": 0, "failed": 0, "pending": 1},
  "stopped_reason": "quota",
  "items": [
    {"file": "vdo_a.mov", "status": "uploaded", "video_url": "https://www.youtube.com/watch?v=...", "error_code": null}
  ]
}
```

`ok` เป็น `true` เฉพาะเมื่อ exit code เป็น 0; ถ้ามีปัญหาจะมี `error` เป็นข้อความเดียวกับที่แสดงใน stderr. `dry-run --json` ใส่ `title` ที่จะใช้ของแต่ละไฟล์ที่พร้อม. JSON ไม่มี OAuth token, client secret, resumable session URL หรือ API response body. ในโหมด `--json` ถ้าชื่อช่องซ้ำกัน โปรแกรมจะหยุดแทนการถาม; ให้ถามผู้ใช้หา handle หรือ channel ID

## Hashtag ของคลิปแนวตั้ง

คลิปแนวตั้ง (`_9x16`) ใช้ `vertical_short_hashtags` ในโปรไฟล์ถ้าระบุไว้. ถ้าว่าง จะใช้ `shorts_hashtag_template` (ค่าเริ่มต้น `["#{channel}", "#vtuberth", "#{game}", "#วันว่างๆ", "#shorts"]`) โดย `{channel}` คือ `channel_alias` แบบ hashtag และ `{game}` คือคำหลัง `_` ตัวสุดท้ายในชื่อไฟล์ (ตัดทิ้งถ้าไม่มี). เปลี่ยน hashtag ของช่องโดยแก้ไฟล์โปรไฟล์นั้น ไม่ต้องแก้โค้ด

## ตั้งเวลาเผยแพร่

ระบุเวลา RFC 3339 พร้อม UTC offset. โหมดตารางจะเรียงไฟล์ตามชื่อ แยกแนวนอน/แนวตั้ง แล้วจับคู่วันละหนึ่งคลิปต่อแนว:

```powershell
yt-upload upload --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "UCckWRGExmxGqjWjGZgmZypg" --schedule-from "2026-10-01T07:30:00+07:00"
```

คลิปในโฟลเดอร์นี้ 12 คู่จะได้กำหนดการ 12 วัน ตั้งแต่ 1 ถึง 12 ต.ค. 2026 เวลา 07:30 น. ตามเวลาไทย. คลิปใหม่จะอัปโหลดเป็น Private พร้อม `publishAt`; คลิปที่ส่งเสร็จแล้วจะตั้งเวลาผ่าน YouTube โดยไม่ส่งวิดีโอซ้ำ

การตั้งเวลาต้องมี OAuth scope สำหรับแก้ metadata. คำสั่ง `upload --schedule-from` จะเปิด Google OAuth เองเมื่อยังขาด scope; ยืนยันสิทธิ์บนหน้า Google แล้วโปรแกรมทำงานต่อ. โปรแกรมตรวจช่อง, เวลาในอนาคต และไฟล์ก่อนเริ่ม และอ่าน `private` + `publishAt` กลับจาก API ก่อนรายงานสำเร็จ

ค่า `api_audit_passed` เดิมไม่บล็อกคำขอและไม่ใช่ผลตรวจจาก Google. ข้อจำกัด API project เป็นการบังคับใช้ของ YouTube; ถ้า API ปฏิเสธหรือไม่ยืนยันเวลา โปรแกรมหยุดพร้อมเก็บ video ID ที่ได้รับไว้เพื่อแก้ตารางคลิปเดิมโดยไม่อัปโหลดซ้ำ

## OAuth และโปรไฟล์

ใช้ `yt-upload profile list` เพื่อดูชื่อโปรไฟล์ แล้วระบุ `--profile <ชื่อ>` ในคำสั่งที่ทำงานกับช่อง เช่น `upload`, `dry-run`, `schedule`, `profile show` และ `auth login`. ถ้ามีหลายโปรไฟล์และไม่เลือกชื่อ คำสั่งจะหยุดก่อนทำงาน. ถ้า `profile.json` เป็นช่องที่ไม่ซ้ำกับไฟล์แยก จะแสดงในรายการด้วยชื่อ OAuth account; การติดตั้งรุ่นเดิมที่ยังไม่มี `profiles/` ก็ยังใช้ไฟล์นี้ต่อได้

ตั้งโปรไฟล์แยกสำหรับช่องใหม่:

```powershell
yt-upload profile setup --profile new-channel --oauth-account new-account
```

ค่าช่อง, metadata, privacy และ OAuth account จะถูกบันทึกใน `profiles/<ชื่อ>.json`; OAuth credentials ยังคงแยกตามค่า `oauth_account_key`

เชื่อม OAuth ครั้งแรก:

```powershell
yt-upload auth token --client-secrets ".\client_secrets.json" --account waritnan34811
```

ถ้ายังไม่มี credential ตอนรัน `upload` โปรแกรมจะเปิด Google OAuth ให้ลงชื่อเข้าใช้และบันทึกใน account ที่โปรไฟล์กำหนด. โปรแกรมตรวจว่า credential เข้าถึง channel ที่ระบุก่อนส่งคลิป

`profile show --profile armigon` แสดงค่าที่ตั้งไว้โดยไม่แสดง secret. เปลี่ยน visibility เริ่มต้นได้ด้วย `yt-upload profile set-privacy --profile armigon private`. การยอมรับ visibility และตารางขึ้นกับผลจริงจาก YouTube API ไม่ต้องบันทึกสถานะ audit ในโปรไฟล์ก่อน

## ลองงานที่ล้มเหลวอีกครั้ง

หลังแก้สาเหตุของงานที่ล้มเหลว ให้ระบุไฟล์นั้นและเรียก upload โฟลเดอร์เดิม:

```powershell
yt-upload profile retry-failed --profile armigon --path "<พาธไฟล์วิดีโอ>"
yt-upload upload --profile armigon --folder "<โฟลเดอร์คลิป>" --channel "<ชื่อช่องหรือ channel ID>"
```

ก่อนส่งซ้ำ โปรแกรมตรวจ channel และ hash ของวิดีโอ/thumbnail กับงานเดิม หากไฟล์เปลี่ยนต้องเตรียมงานใหม่ให้ตรงกับไฟล์ปัจจุบัน

## จัดการ OAuth และข้อมูลในเครื่อง

```powershell
yt-upload profile delete-account-data --profile armigon --channel-id CHANNEL_ID
yt-upload profile revoke-authorization --profile armigon --channel-id CHANNEL_ID
yt-upload auth accounts
```

การลบ account data ลบเฉพาะ job state และข้อมูล YouTube ที่เก็บในเครื่อง ไม่ลบวิดีโอบน YouTube. การ revoke ยกเลิก OAuth และลบ credential ของบัญชีที่โปรไฟล์ใช้

`maintenance refresh --profile armigon` ใช้ตรวจ OAuth/channel และล้างข้อมูล API ที่หมดอายุตามรอบ หากตั้ง Windows Task Scheduler ให้เรียกเฉพาะคำสั่งนี้; อย่าตั้ง scheduler ให้เรียก `upload` หรือเฝ้าดูโฟลเดอร์
