# คู่มือติดตั้งครั้งแรกบน Windows

ตั้งค่าทีละขั้นก่อนเรียก YouTube API ใช้บัญชี Google ที่เป็นเจ้าของหรือมีสิทธิ์จัดการช่อง Katy404 การใช้ project ID `mfk110...` เป็นเงื่อนไขของโปรแกรมเพื่อกัน OAuth JSON เก่าผิดโปรเจกต์

## 1. สร้าง Google Cloud Upload Project

1. เปิด [Google Cloud Console](https://console.cloud.google.com/) ด้วยบัญชีเจ้าของ แล้วสร้าง project ใหม่ เช่น `mfk110-katy404-upload-<suffix>` ชื่อและ ID ต้องไม่ซ้ำกับผู้ใช้อื่น; ตั้ง project ID ให้ขึ้นต้นด้วย `mfk110` ตั้งแต่สร้าง เพราะ ID เปลี่ยนภายหลังไม่ได้
2. เลือก project ใหม่และเปิด **APIs & Services → Library** แล้ว enable **YouTube Data API v3**
3. กรอกข้อมูลผู้พัฒนา/หน้าความยินยอมตามที่ Console ขอ ตั้งค่า audience ให้เหมาะกับบัญชี Google เจ้าของ ใช้ `External` หากบัญชีอยู่นอก Google Workspace organization ของ project
4. หาก Console หรือ YouTube API audit ถามกลุ่มผู้ใช้ของ API client ให้ระบุขอบเขตที่อนุมัติไว้ว่าตัวโปรแกรมนี้ใช้โดยเจ้าของ/ผู้ดูแลช่อง ไม่ได้ออกแบบมาให้เด็กใช้โดยตรง อย่าสับสนกับ audience `External/Internal` หรือคำประกาศ Made for Kids ของวิดีโอ ซึ่งเป็นคนละค่าและต้องตอบแยกกัน หากเปลี่ยนกลุ่มผู้ใช้ในอนาคตให้ทบทวนคำตอบก่อนใช้ API ต่อ

ค่า `mfk110` เป็นเงื่อนไขตรวจในโปรแกรมนี้ ไม่ใช่รูปแบบ project ID ที่ Google สงวนให้

## 2. ตั้ง OAuth Desktop client ใหม่

1. ทำ privacy policy ใน [ฉบับร่าง](privacy-policy.md) ให้พร้อมก่อน: ใส่ช่องทางติดต่อจริง, เผยแพร่บน URL HTTPS ที่ทุกคนเปิดอ่านได้ และแก้ placeholder ใน [terms](terms-of-use.md) ให้ครบ
2. ใน OAuth consent screen ให้ลงทะเบียนบัญชีเจ้าของเป็น test user หากสถานะ app เป็น **Testing**
3. สร้าง OAuth client แบบ **Desktop app** แล้วดาวน์โหลด JSON ใหม่
4. เก็บไฟล์ไว้ใน `%LOCALAPPDATA%\Katy404\YouTubeUploader\client_secrets.json` ไม่เก็บใน repo, `D:\agent-upload-social\`, โฟลเดอร์ Google Drive, chat หรือ ticket
5. อย่าใช้ `D:\agent-upload-social\client_secrets.json` ไฟล์เดิมกับ uploader นี้: project ID ของไฟล์เดิมไม่ตรง `mfk110` และตัวตรวจจะปฏิเสธตั้งแต่ก่อน OAuth

แอปขอ OAuth scope สำหรับ `youtube.upload` และ `youtube.readonly` เพื่ออัปโหลดวิดีโอและตรวจช่อง/สถานะวิดีโอเท่าที่จำเป็น ในการอนุญาตครั้งแรก browser จะแสดงบัญชีที่จะเชื่อมต่อ ให้เลือกบัญชีเจ้าของ Katy404 และอ่าน scope ที่ Google แสดงก่อนกดยินยอม

การยืนยัน OAuth ของ Google กับการตรวจ YouTube API Services (API compliance audit) เป็นคนละขั้นตอน หากคง app ไว้ใน **Testing**, การอนุญาต scope อื่นนอกเหนือจาก basic profile อาจหมดอายุ 7 วันหลังยินยอม รวมถึง refresh token; ต้อง authorize ใหม่ตามที่ Console กำหนด หากจะเผยแพร่ app หรือ verify scopes ให้ทำขั้นตอนที่ Console ขอแยกจาก API audit

## 3. ติดตั้งตัวโปรแกรมและ ffprobe

ติดตั้ง Python 3.13 หรือ 3.14 และ FFmpeg ที่มี `ffprobe.exe` จากแหล่งที่เชื่อถือได้ จาก PowerShell ที่ root ของ repo:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\Activate.ps1
ffprobe -version
kt404-youtube --help
```

แอปเก็บ `profile.json` และ `state.sqlite3` ไว้ที่ `%LOCALAPPDATA%\Katy404\YouTubeUploader\`; token อยู่ใน Windows Credential Manager ไม่ต้องสร้าง `token.json`

## 4. สร้าง profile และ consent

```powershell
kt404-youtube profile setup
kt404-youtube profile show
kt404-youtube profile accept-policy
```

กรอกชื่อ/handle ช่อง, คำอธิบาย, Shorts suffix, category ID, tags, privacy และ declarations ตามข้อเท็จจริงของช่องและชุดไฟล์

- **Privacy:** เลือก `private`, `unlisted`, หรือ `public` ให้ชัด อย่าให้ agent เดา; pilot บังคับ Private
- **Category / tags / description:** ใช้ metadata ที่เจ้าของยืนยัน ชื่อวิดีโอมาจากชื่อไฟล์ตามกติกาในโปรแกรม
- **Made for Kids:** ตอบตามกลุ่มเป้าหมายที่ตั้งใจ ไม่ใช่ตามการมีเกมหรือภาพการ์ตูนอย่างเดียว
- **Synthetic media:** ตอบตามเนื้อหาจริง; โปรแกรมไม่วิเคราะห์เพื่อเดาแทนเจ้าของ
- **Official Artist Channel:** ตอบตามสถานะจริงของช่อง
- **Asset rights:** ยืนยันเฉพาะเมื่อมีสิทธิ์ใช้เสียง, ภาพ, game footage และ overlay ในคลิปทั้งชุด; หากยังไม่ยืนยันให้ตั้งเป็น not-confirmed และอย่าอัปโหลดจนกว่าจะยืนยันได้

`profile setup` ไม่ยอมรับ policy หรือเปิด browser ให้เอง ตรวจ URL/ข้อความที่แสดงใน `profile accept-policy`, อ่าน privacy policy และ [YouTube Terms of Service](https://www.youtube.com/t/terms), แล้วพิมพ์ `ยอมรับ` ด้วยตนเอง

### หน้าเข้าสู่ระบบในเครื่อง

เมื่อเจ้าของสั่ง `upload` หลัง profile และ policy ผ่านแล้ว โปรแกรมจะเปิดหน้า local เฉพาะกรณีที่ Windows Credential Manager ยังไม่มี OAuth credential หน้าแสดง `waiting`, `connected` หรือ `stopped` และเปิด Google OAuth Desktop flow ให้ลงชื่อเข้าใช้/ยินยอมบนหน้า Google

หน้า local ใช้ดูสถานะเท่านั้น ไม่รับรหัสผ่านหรือ OTP และไม่แสดง access/refresh token เมื่อ credential บันทึกใน Windows Credential Manager สำเร็จ หน้าแสดง `connected`; จากนั้น CLI ยังต้องตรวจ channel name/handle/ID ที่สั่ง หากบัญชีไม่เข้าถึงช่องเป้าหมายหรือชื่อกำกวม โปรแกรมหยุดก่อนส่งวิดีโอ โดย credential ที่เชื่อมสำเร็จยังเก็บไว้ตามปกติ หากยกเลิกหรือ OAuth/การบันทึก credential ล้มเหลว หน้านี้แสดง `stopped` และคำสั่ง upload รอบนั้นหยุด

ถ้ามี credential อยู่แล้ว หน้า local จะไม่เปิดและโปรแกรมใช้ flow refresh เดิมตามปกติ การตรวจ `dry-run` เป็น offline และไม่เปิด OAuth หรือหน้านี้

## 5. แยก OAuth verification ออกจาก YouTube API audit

Google OAuth verification ใช้กับ consent screen/scopes ของ OAuth app ส่วน YouTube API compliance audit เป็นการตรวจการใช้งาน YouTube API และใช้พิจารณา quota extension หรือกรณีที่ YouTube ขอ audit; การมีอย่างใดอย่างหนึ่งไม่ได้แปลว่าอีกอย่างผ่าน

โปรแกรมรุ่นนี้เพิ่ม app-specific safety gate: **Unlisted/Public ถูกปิดจนกว่าเจ้าของจะตรวจผล audit และรันคำสั่งนี้เอง**:

```powershell
kt404-youtube profile set-api-audit-status passed
```

ห้ามใช้คำสั่งนี้เพียงเพราะสร้าง Google Cloud project, เปิด API, หรือผ่าน OAuth verification แล้ว การเปลี่ยน privacy ทำได้ด้วย `profile set-privacy private|unlisted|public`

## 6. ตรวจ quota ก่อน batch เต็ม

ณ วันที่เขียนเอกสาร quota calculator แสดง `videos.insert` ใน bucket แยก จำกัดเริ่มต้น 100 calls/day โดยแต่ละ call คิด 1 quota; `thumbnails.set` คิดประมาณ 50 units ต่อ call ใน bucket ของ endpoint อื่น ดังนั้น 24 คลิปนี้ต้องใช้ 24 `videos.insert` calls และประมาณ 1,200 units สำหรับ JPG 24 ภาพ รวมคำขออ่านช่อง/refresh เพิ่มเล็กน้อยและ retries ที่อาจต้องเปิด session ใหม่ ตรวจหน้า **Google Cloud Console → YouTube Data API → Quotas** ของ project จริงก่อน batch; quota อาจถูกปรับได้

การขอ quota เพิ่มอาจต้องยื่น [YouTube API Services Audit and Quota Extension Form](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) และผ่าน audit ตามเงื่อนไขของ Google ไม่ควรตั้งสถานะ audit ใน profile จนกว่าจะมีผลอนุมัติจริง

## 7. ตรวจและปล่อยคลิปนำร่อง

รันคำสั่ง `dry-run` และตรวจชื่อไฟล์, JPG คู่กัน, metadata และ privacy ก่อน จากนั้นสั่ง Private pilot หนึ่งคลิป ดู URL/visibility ที่ CLI รายงาน แล้วตรวจวิดีโอและ thumbnail ใน YouTube Studio หากต้องการ batch เต็ม เจ้าของต้องอนุมัติ video ID ที่ตรวจแล้วด้วย `profile approve-pilot --video-id ID` และส่งคำสั่ง batch เต็มแยกอีกครั้ง ขั้นตอนทั้งหมดพร้อม path อยู่ใน [คู่มือปฏิบัติงาน](operations.md)

## แหล่งอ้างอิงทางการ

- [Manage app audience and Testing status](https://support.google.com/cloud/answer/15549945?hl=en)
- [YouTube API quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube API quota/compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)
- [YouTube Developer Policies](https://developers.google.com/youtube/terms/developer-policies)
- [YouTube resumable upload protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [YouTube video upload guide](https://developers.google.com/youtube/v3/guides/uploading_a_video)
