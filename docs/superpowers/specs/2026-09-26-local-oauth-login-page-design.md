# หน้า local สำหรับเชื่อม YouTube OAuth

สถานะ: ออกแบบและอนุมัติในแชตเมื่อ 2026-09-26; รอผู้ใช้ตรวจเอกสารฉบับนี้

## เป้าหมาย

เมื่อเจ้าของสั่งอัปโหลดไปยังช่อง YouTube และโปรแกรมไม่พบ OAuth credential ที่ยังใช้ได้ ให้เปิดหน้า local แสดงสถานะการเชื่อมต่อ พร้อมเปิด Google OAuth Desktop flow เพื่อให้เจ้าของลงชื่อเข้าใช้และยินยอมด้วยตนเอง เมื่อบันทึก credential สำเร็จและยืนยันช่องเป้าหมายได้ จึงดำเนินการอัปโหลดตามคำสั่งเดิมต่อ

คำว่า token ของช่องในงานนี้หมายถึง OAuth grant ของบัญชี Google ที่มีสิทธิ์จัดการช่อง โปรแกรมต้องตรวจช่องที่บัญชีนั้นเป็นเจ้าของจาก YouTube API แล้วจับคู่กับชื่อ, handle หรือ channel ID ที่เจ้าของสั่งก่อนอัปโหลด

## ความเข้าใจและข้อกำหนดที่ตกลงกัน

- ผู้ใช้คนเดียว ใช้บน Windows ภายในเครื่อง `D:\agent-upload-social`
- หน้า local เปิดอัตโนมัติเฉพาะเมื่อ flow อัปโหลดไม่พบ credential; ถ้ามี credential ที่ใช้ได้ให้ข้ามหน้าและใช้ flow เดิม
- หน้า local เป็นหน้าสถานะ ไม่ใช่แบบฟอร์มรับรหัสผ่าน และไม่แสดง access/refresh token
- Google เป็นผู้แสดงหน้าลงชื่อเข้าใช้และ consent เอง ใช้ OAuth Desktop client ของโปรเจกต์ใหม่ที่ `project_id` ขึ้นต้น `mfk110`
- ใช้ scope เดิมเท่านั้น: `youtube.upload` และ `youtube.readonly`
- บันทึก OAuth credential ใน Windows Credential Manager ตาม implementation ปัจจุบัน; ห้ามเขียน token ลงไฟล์, log, URL หรือ HTML
- ตรวจ policy/configuration ก่อนเปิด browser เหมือน flow ปัจจุบัน; ใช้โฟลเดอร์และ channel ที่ผู้ใช้ระบุเท่านั้น
- หาก consent ถูกปฏิเสธ, OAuth ล้มเหลว, เก็บ credential ไม่สำเร็จ, หรือไม่พบ channel เป้าหมายที่ตรงกัน ให้หยุดก่อนส่งวิดีโอ
- ไม่เปลี่ยนข้อกำหนด Private pilot และการอนุมัติแยกก่อน batch เต็ม

## สถานะปัจจุบัน

`CliApp._upload` ตรวจโปรไฟล์และ policy ก่อนอ่าน credential จากนั้นเรียก `OAuthService.authorize` เมื่อไม่มี credential. `authorize_desktop` ตรวจรูปแบบ Desktop client และ prefix `mfk110`, เปิด `InstalledAppFlow.run_local_server`, และบันทึก credential ผ่าน `CredentialStore` ไปยัง Windows Credential Manager. หลัง OAuth โปรแกรมเรียก YouTube API และ runner ตรวจ ownership/match ของ channel ก่อนเริ่ม upload

จุดที่ขาดคือหน้า local ของโปรแกรมสำหรับบอกสถานะขณะรอผู้ใช้ทำ Google OAuth. ข้อเสนอนี้เพิ่มเฉพาะ status surface โดยคง flow, scopes, credential backend, channel verification และ upload gates เดิม

## แนวทางสถาปัตยกรรม

เพิ่มโมดูล local status UI ด้วย Python standard library. เมื่อ credential หาย หลังจากผ่าน validation ปัจจุบันแล้ว:

1. เริ่ม HTTP server อายุสั้นที่ bind เฉพาะ `127.0.0.1` บนพอร์ตว่างจากระบบ
2. เปิดหน้า status ใน browser หนึ่งแท็บ โดยหน้าเริ่มในสถานะรอ consent และอ่านสถานะจาก endpoint แบบ read-only ของ origin เดียวกัน
3. เรียก OAuth Desktop flow เดิม ซึ่งเปิด Google sign-in/consent ใน browser; ผู้ใช้กรอกรหัสผ่านหรือยืนยันตัวตนบนโดเมน Google เท่านั้น
4. อัปเดตสถานะเป็น connected เมื่อ credential ถูกบันทึกสำเร็จ จากนั้นสร้าง API client และให้ runner ตรวจ channel ตามที่สั่ง
5. เมื่อ channel ตรงกัน แสดงว่าเชื่อมต่อและยืนยัน channel แล้ว จากนั้นหยุด polling และดำเนิน upload ตามคำสั่งเดิม; เมื่อ flow ล้มเหลวหรือ channel ไม่ตรง แสดงข้อความปลอดภัยและจบคำสั่งโดยไม่ upload
6. ปิด local server เสมอเมื่อ auth/channel verification จบหรือเกิด exception

ตัวหน้าใช้ HTML/CSS/JavaScript แบบ static ที่ส่งจาก server ภายในเครื่อง ไม่มี dependency frontend, CDN, analytics หรือ resource จาก third party. หน้าไม่ทำหน้าที่จัดการอัปโหลดหรือแก้ profile

## สถานะหน้าจอ

- `waiting`: รอผู้ใช้ทำขั้นตอน OAuth บน Google
- `connected`: OAuth สำเร็จและ credential ถูกบันทึกแล้ว
- `verifying_channel`: โปรแกรมตรวจว่าบัญชีเข้าถึง channel ที่ผู้ใช้ระบุ
- `channel_verified`: ยืนยัน channel แล้ว; upload จะเดินหน้าต่อในโปรเซสเดิม สถานะนี้ไม่ได้แปลว่า upload เสร็จแล้ว
- `stopped`: ยกเลิก consent, ตรวจ channel ไม่ผ่าน, หรือเกิดข้อผิดพลาดที่หยุดงาน

หน้าไม่แสดง email/token/ข้อมูล API ดิบ เว้นแต่ข้อมูลชื่อช่องที่ผู้ใช้ระบุและจำเป็นต่อการยืนยันสถานะ

## ขอบเขตความปลอดภัย

- รับ HTTP เฉพาะ loopback; ปิด server โดยเร็วเมื่อจบ flow
- ใช้ status endpoint แบบ read-only; response เป็น enum และข้อความคงที่ที่ allowlist ไว้ ไม่ส่ง raw exception, OAuth URL, response body หรือ credential
- ใช้ route/session identifier สุ่มต่อการทำงานหนึ่งครั้ง และป้องกันไม่ให้หน้าอื่นอ่านสถานะของ session โดยเดา URL ได้
- ใส่ security headers ที่เหมาะสมกับหน้า static (เช่น CSP แบบไม่มี external source และ `Cache-Control: no-store`)
- คงการตรวจ OAuth client prefix, policy acceptance, profile validity, privacy gate และ pilot gate ที่มีอยู่
- การ consent ยังคงเป็นการกระทำของผู้ใช้ในหน้า Google; ตัวโปรแกรมไม่ยอมรับ consent แทนเจ้าของ

## การจัดการข้อผิดพลาด

- config หรือ policy ยังไม่พร้อม: แสดงข้อความใน CLI ตามเดิมและไม่เปิด local page หรือ Google OAuth
- Google OAuth ถูกปฏิเสธ/ล้มเหลว/หมดเวลา: สถานะเป็น `stopped`, ไม่เริ่ม upload และไม่บันทึก credential ที่ไม่สมบูรณ์
- Windows Credential Manager ใช้ไม่ได้: แสดงข้อความทั่วไปในหน้าและ CLI; ไม่ fallback ไปเก็บ token แบบ plaintext
- บัญชีไม่มี channel เป้าหมายหรือชื่อกำกวม: หยุดก่อน upload; ใช้กติกาจับคู่ชื่อ/handle/ID เดิม หาก OAuth consent สำเร็จแล้ว credential ยังคงอยู่ใน Credential Manager เพราะเป็นสิทธิ์ของบัญชี Google; หน้าและ CLI ต้องแจ้งว่าช่องเป้าหมายไม่ตรงโดยไม่แสดง token
- อัปโหลดถูกยกเลิกหรือโปรเซสจบ: ปิด server และหยุด polling จากหน้า

## เกณฑ์ยอมรับ

1. เมื่อมี credential ที่ยังใช้ได้ flow อัปโหลดไม่เปิดหน้า local เพิ่ม
2. เมื่อไม่มี credential และ profile ผ่าน validation หน้า local แสดงสถานะรอ และ Google OAuth Desktop flow เปิดขึ้น
3. เมื่อผู้ใช้อนุมัติและบันทึก credential ได้ หน้า local แสดง connected โดยไม่แสดง token; flow เดิมตรวจ channel ก่อน upload และหน้าแสดง `channel_verified` เมื่อยืนยันสำเร็จ
4. เมื่อผู้ใช้ปฏิเสธ/ยกเลิก, client ผิด project, credential backend ล้มเหลว หรือ channel ไม่ตรง จะไม่มีการเรียก upload endpoint
5. หลังคำสั่งจบ ไม่เหลือ local HTTP server เปิดค้าง และไม่มี token ในไฟล์/log/HTML/URL
6. dry-run ยังคง offline ไม่เปิด OAuth หรือ local login page
7. Pilot/batch behavior และข้อกำหนดว่าต้องสั่ง upload อย่างชัดเจนยังคงเดิม

## นอกขอบเขต

- เว็บที่เผยแพร่บนอินเทอร์เน็ตหรือรับการ login จากเครื่องอื่น
- แบบฟอร์มที่รับ Google password, OTP หรือแสดง/ดาวน์โหลด token
- dashboard จัดการคลิป, browser automation เพื่อกด consent แทนผู้ใช้, หรือการอัปโหลดอัตโนมัติหลังผู้ใช้ยังไม่ได้สั่ง
- เปลี่ยน OAuth scopes, Credential Manager backend, policy gate, channel ownership rules, หรือ upload/retry/pilot logic
