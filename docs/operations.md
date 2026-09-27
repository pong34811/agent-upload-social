# คู่มือใช้งาน

## อัปโหลด

คำสั่ง `upload` ตรวจไฟล์ระดับบนสุดในโฟลเดอร์ที่เลือกก่อนเริ่มส่ง, จับคู่ MOV/JPG, อ่านวิดีโอด้วย `ffprobe`, เติม metadata จาก `profile.json` และกันไฟล์ซ้ำด้วย hash

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

ใช้ `dry-run` เฉพาะเมื่อต้องการดูผลตรวจโดยยังไม่เชื่อมต่อ YouTube:

```powershell
kt404-youtube dry-run --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "waritnan34811"
```

ไม่ต้องอัปโหลดคลิปนำร่องหรืออนุมัติแยกก่อน batch. ถ้าไฟล์บางรายการผิดพลาด โปรแกรมจะแสดงรายการและหยุด/ข้ามตามผลของ CLI; แก้ไฟล์ต้นทางก่อนลองใหม่

## ตั้งเวลาเผยแพร่

ระบุเวลา RFC 3339 พร้อม UTC offset. โหมดตารางจะเรียงไฟล์ตามชื่อ แยกแนวนอน/แนวตั้ง แล้วจับคู่วันละหนึ่งคลิปต่อแนว:

```powershell
kt404-youtube upload --folder "G:\My Drive\Projects\Katy404\2026-09\vdo" --channel "UCckWRGExmxGqjWjGZgmZypg" --schedule-from "2026-10-01T07:30:00+07:00"
```

คลิปในโฟลเดอร์นี้ 12 คู่จะได้กำหนดการ 12 วัน ตั้งแต่ 1 ถึง 12 ต.ค. 2026 เวลา 07:30 น. ตามเวลาไทย. คลิปใหม่จะอัปโหลดเป็น Private พร้อม `publishAt`; คลิปที่ส่งเสร็จแล้วจะตั้งเวลาผ่าน YouTube โดยไม่ส่งวิดีโอซ้ำ

การตั้งเวลาต้องมี OAuth scope สำหรับแก้ metadata. คำสั่ง `upload --schedule-from` จะเปิด Google OAuth เองเมื่อยังขาด scope; ยืนยันสิทธิ์บนหน้า Google แล้วโปรแกรมทำงานต่อ. โปรแกรมตรวจช่อง, เวลาในอนาคต และไฟล์ก่อนเริ่ม และอ่าน `private` + `publishAt` กลับจาก API ก่อนรายงานสำเร็จ

ค่า `api_audit_passed` เดิมไม่บล็อกคำขอและไม่ใช่ผลตรวจจาก Google. ข้อจำกัด API project เป็นการบังคับใช้ของ YouTube; ถ้า API ปฏิเสธหรือไม่ยืนยันเวลา โปรแกรมหยุดพร้อมเก็บ video ID ที่ได้รับไว้เพื่อแก้ตารางคลิปเดิมโดยไม่อัปโหลดซ้ำ

## OAuth และโปรไฟล์

ค่าช่อง, metadata, privacy และ account label อ่านจาก `profile.json`. โดยปกติไม่ต้องรัน `profile setup` ซ้ำ หากโปรไฟล์และ OAuth ใช้งานได้แล้ว

เชื่อม OAuth ครั้งแรก:

```powershell
kt404-youtube auth token --client-secrets ".\client_secrets.json" --account waritnan34811
```

ถ้ายังไม่มี credential ตอนรัน `upload` โปรแกรมจะเปิด Google OAuth ให้ลงชื่อเข้าใช้และบันทึกใน account ที่โปรไฟล์กำหนด. โปรแกรมตรวจว่า credential เข้าถึง channel ที่ระบุก่อนส่งคลิป

`profile show` แสดงการตั้งค่าปัจจุบันโดยไม่แสดง secret. เปลี่ยน visibility เริ่มต้นได้ด้วย `kt404-youtube profile set-privacy private`. การยอมรับ visibility และตารางขึ้นกับผลจริงจาก YouTube API ไม่ต้องบันทึกสถานะ audit ในโปรไฟล์ก่อน

## ลองงานที่ล้มเหลวอีกครั้ง

หลังแก้สาเหตุของงานที่ล้มเหลว ให้ระบุไฟล์นั้นและเรียก upload โฟลเดอร์เดิม:

```powershell
kt404-youtube profile retry-failed --path "<พาธไฟล์วิดีโอ>"
kt404-youtube upload --folder "<โฟลเดอร์คลิป>" --channel "<ชื่อช่องหรือ channel ID>"
```

ก่อนส่งซ้ำ โปรแกรมตรวจ channel และ hash ของวิดีโอ/thumbnail กับงานเดิม หากไฟล์เปลี่ยนต้องเตรียมงานใหม่ให้ตรงกับไฟล์ปัจจุบัน

## จัดการ OAuth และข้อมูลในเครื่อง

```powershell
kt404-youtube profile delete-account-data --channel-id CHANNEL_ID
kt404-youtube profile revoke-authorization --channel-id CHANNEL_ID
kt404-youtube auth accounts
```

การลบ account data ลบเฉพาะ job state และข้อมูล YouTube ที่เก็บในเครื่อง ไม่ลบวิดีโอบน YouTube. การ revoke ยกเลิก OAuth และลบ credential ของบัญชีที่โปรไฟล์ใช้

`maintenance refresh` ใช้ตรวจ OAuth/channel และล้างข้อมูล API ที่หมดอายุตามรอบ หากตั้ง Windows Task Scheduler ให้เรียกเฉพาะคำสั่งนี้; อย่าตั้ง scheduler ให้เรียก `upload` หรือเฝ้าดูโฟลเดอร์
