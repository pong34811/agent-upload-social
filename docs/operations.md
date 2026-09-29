# คู่มือใช้งาน

## อัปโหลด

คำสั่ง `upload` ตรวจไฟล์ระดับบนสุดในโฟลเดอร์ที่เลือกก่อนเริ่มส่ง, จับคู่ MOV/JPG, อ่านวิดีโอด้วย `ffprobe`, เติม metadata จากโปรไฟล์ที่เลือก และกันไฟล์ซ้ำด้วย hash

```powershell
kt404-youtube upload --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

ใช้ `dry-run` เฉพาะเมื่อต้องการดูผลตรวจโดยยังไม่เชื่อมต่อ YouTube:

```powershell
kt404-youtube dry-run --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

คำสั่งตรวจเฉพาะไฟล์ระดับบนสุด รองรับวิดีโอ `.mp4`/`.mov` และจับคู่กับภาพชื่อฐานเดียวกัน (`.jpg`, `.jpeg` หรือ `.png`), อ่านข้อมูลวิดีโอด้วย `ffprobe`, คำนวณ hash เพื่อกันส่งซ้ำ และแสดงไฟล์ที่ต้องแก้ ไม่มี OAuth หรือ request ไป YouTube ในขั้นนี้. ไม่ต้องอนุมัติแยกก่อน batch; ถ้าไฟล์ผิดพลาดให้แก้ไฟล์ต้นทางก่อนลองใหม่

## ตั้งเวลาเผยแพร่

ระบุเวลา RFC 3339 พร้อม UTC offset. โหมดตารางจะเรียงไฟล์ตามชื่อ แยกแนวนอน/แนวตั้ง แล้วจับคู่วันละหนึ่งคลิปต่อแนว:

```powershell
kt404-youtube upload --profile katy404 --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "UCckWRGExmxGqjWjGZgmZypg" --schedule-from "2026-10-01T07:30:00+07:00"
```

คลิปในโฟลเดอร์นี้ 12 คู่จะได้กำหนดการ 12 วัน ตั้งแต่ 1 ถึง 12 ต.ค. 2026 เวลา 07:30 น. ตามเวลาไทย. คลิปใหม่จะอัปโหลดเป็น Private พร้อม `publishAt`; คลิปที่ส่งเสร็จแล้วจะตั้งเวลาผ่าน YouTube โดยไม่ส่งวิดีโอซ้ำ

การตั้งเวลาต้องมี OAuth scope สำหรับแก้ metadata. คำสั่ง `upload --schedule-from` จะเปิด Google OAuth เองเมื่อยังขาด scope; ยืนยันสิทธิ์บนหน้า Google แล้วโปรแกรมทำงานต่อ. โปรแกรมตรวจช่อง, เวลาในอนาคต และไฟล์ก่อนเริ่ม และอ่าน `private` + `publishAt` กลับจาก API ก่อนรายงานสำเร็จ

ค่า `api_audit_passed` เดิมไม่บล็อกคำขอและไม่ใช่ผลตรวจจาก Google. ข้อจำกัด API project เป็นการบังคับใช้ของ YouTube; ถ้า API ปฏิเสธหรือไม่ยืนยันเวลา โปรแกรมหยุดพร้อมเก็บ video ID ที่ได้รับไว้เพื่อแก้ตารางคลิปเดิมโดยไม่อัปโหลดซ้ำ

## OAuth และโปรไฟล์

ใช้ `kt404-youtube profile list` เพื่อดูชื่อโปรไฟล์ แล้วระบุ `--profile <ชื่อ>` ในคำสั่งที่ทำงานกับช่อง เช่น `upload`, `dry-run`, `schedule`, `profile show` และ `auth login`. ถ้ามีหลายโปรไฟล์และไม่เลือกชื่อ คำสั่งจะหยุดก่อนทำงาน. ถ้า `profile.json` เป็นช่องที่ไม่ซ้ำกับไฟล์แยก จะแสดงในรายการด้วยชื่อ OAuth account; การติดตั้งรุ่นเดิมที่ยังไม่มี `profiles/` ก็ยังใช้ไฟล์นี้ต่อได้

ตั้งโปรไฟล์แยกสำหรับช่องใหม่:

```powershell
kt404-youtube profile setup --profile new-channel --oauth-account new-account
```

ค่าช่อง, metadata, privacy และ OAuth account จะถูกบันทึกใน `profiles/<ชื่อ>.json`; OAuth credentials ยังคงแยกตามค่า `oauth_account_key`

เชื่อม OAuth ครั้งแรก:

```powershell
kt404-youtube auth token --client-secrets ".\client_secrets.json" --account waritnan34811
```

ถ้ายังไม่มี credential ตอนรัน `upload` โปรแกรมจะเปิด Google OAuth ให้ลงชื่อเข้าใช้และบันทึกใน account ที่โปรไฟล์กำหนด. โปรแกรมตรวจว่า credential เข้าถึง channel ที่ระบุก่อนส่งคลิป

`profile show --profile armigon` แสดงค่าที่ตั้งไว้โดยไม่แสดง secret. เปลี่ยน visibility เริ่มต้นได้ด้วย `kt404-youtube profile set-privacy --profile armigon private`. การยอมรับ visibility และตารางขึ้นกับผลจริงจาก YouTube API ไม่ต้องบันทึกสถานะ audit ในโปรไฟล์ก่อน

## ลองงานที่ล้มเหลวอีกครั้ง

หลังแก้สาเหตุของงานที่ล้มเหลว ให้ระบุไฟล์นั้นและเรียก upload โฟลเดอร์เดิม:

```powershell
kt404-youtube profile retry-failed --profile armigon --path "<พาธไฟล์วิดีโอ>"
kt404-youtube upload --profile armigon --folder "<โฟลเดอร์คลิป>" --channel "<ชื่อช่องหรือ channel ID>"
```

ก่อนส่งซ้ำ โปรแกรมตรวจ channel และ hash ของวิดีโอ/thumbnail กับงานเดิม หากไฟล์เปลี่ยนต้องเตรียมงานใหม่ให้ตรงกับไฟล์ปัจจุบัน

## จัดการ OAuth และข้อมูลในเครื่อง

```powershell
kt404-youtube profile delete-account-data --profile armigon --channel-id CHANNEL_ID
kt404-youtube profile revoke-authorization --profile armigon --channel-id CHANNEL_ID
kt404-youtube auth accounts
```

การลบ account data ลบเฉพาะ job state และข้อมูล YouTube ที่เก็บในเครื่อง ไม่ลบวิดีโอบน YouTube. การ revoke ยกเลิก OAuth และลบ credential ของบัญชีที่โปรไฟล์ใช้

`maintenance refresh --profile armigon` ใช้ตรวจ OAuth/channel และล้างข้อมูล API ที่หมดอายุตามรอบ หากตั้ง Windows Task Scheduler ให้เรียกเฉพาะคำสั่งนี้; อย่าตั้ง scheduler ให้เรียก `upload` หรือเฝ้าดูโฟลเดอร์
