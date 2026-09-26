# นโยบายความเป็นส่วนตัว — Katy404 YouTube Upload Agent (ฉบับร่าง)

**สถานะ: ยังไม่พร้อมเผยแพร่หรือใช้กับ YouTube API**

ก่อนเผยแพร่ เจ้าของต้องแทนที่ช่องทางติดต่อ placeholder ด้านล่างด้วยข้อมูลจริง ตรวจรายละเอียดให้ตรงกับวิธีติดตั้ง/ใช้งานจริง และเผยแพร่เอกสารนี้บน URL HTTPS ที่เข้าถึงได้ทั่วไป จากนั้นจึงใส่ URL ใน `kt404-youtube profile setup` และให้เจ้าของอ่าน/ยอมรับก่อนใช้ OAuth/API

## เจ้าของและผู้ติดต่อ

เจ้าของโปรเจกต์: Katy404 / ผู้พัฒนาเครื่องมืออัปโหลดประจำช่อง

**ช่องทางติดต่อเจ้าของโปรเจกต์: [ใส่อีเมลหรือช่องทางติดต่อจริงก่อนเผยแพร่]**

ใช้ช่องทางนี้สอบถาม ขอสำเนาข้อมูล หรือขอลบข้อมูลที่โปรแกรมเก็บไว้

## ข้อมูลที่เครื่องมือนี้ใช้

เครื่องมือนี้ทำงานในเครื่อง Windows สำหรับเจ้าของช่องคนเดียว อ่านเฉพาะโฟลเดอร์วิดีโอระดับบนสุดที่เจ้าของระบุ ไม่ติดตามการใช้งาน YouTube, ไม่อ่าน browser cookie/รหัสผ่าน และไม่ส่ง metadata ไปยัง AI service

ข้อมูลและเหตุผลที่ใช้:

- ไฟล์วิดีโอต้นฉบับและ JPG ที่เจ้าของเลือก: ส่งไปยัง YouTube เพื่อสร้างวิดีโอและ custom thumbnail ตามคำสั่งอัปโหลด
- path, ชื่อไฟล์, ขนาด, เวลาแก้ไข และ SHA-256 ของวิดีโอ/JPG: เก็บในฐานข้อมูล LocalAppData เพื่อจับคู่ไฟล์, ตรวจการเปลี่ยนแปลง, กันส่งซ้ำ และกู้การอัปโหลดที่หยุดกลางคัน
- metadata ที่เจ้าของตั้งหรือโปรแกรมสร้างจากชื่อไฟล์: title, description, tags, category, privacy, Made for Kids และ synthetic-media declaration; ส่งไปกับคำขออัปโหลดตามค่าที่เจ้าของยืนยัน
- profile settings ที่เจ้าของกรอก: channel alias, OAuth JSON path, privacy-policy URL/เวลาและ revision ที่ยอมรับ, category, tags, description template, privacy default, Shorts suffix, rights/audience declarations, Official Artist Channel status, และ API-audit declaration
- OAuth token ช่อง waritnan34811: เก็บใน `token_waritnan34811.json` ภายในโฟลเดอร์โปรเจกต์เพื่อเรียก API ในนามบัญชีที่ยินยอม ไฟล์นี้ถูกกันออกจาก Git ด้วย `.gitignore`
- ข้อมูลที่อ่านจาก YouTube API: channel ID/name/handle เพื่อยืนยันช่อง และ video ID, title, description, privacy status, thumbnail URL, published time และเวลา refresh เพื่อยืนยันผล/ดูแลสถานะงาน
- resumable upload session URL และ offset: เก็บใน SQLite ภายในเครื่องเพื่อกลับไปทำ upload ที่ค้างต่อได้; URL นี้เป็นข้อมูลลับสำหรับ session, ไม่แสดงใน CLI, และ maintenance ล้าง session ที่ไม่มีกิจกรรม 30 วันเพื่อให้การอัปโหลดครั้งถัดไปเริ่ม session ใหม่

โปรไฟล์และ job state อยู่ที่ `%LOCALAPPDATA%\Katy404\YouTubeUploader\`; OAuth token อยู่ใน `token_waritnan34811.json` ภายในโฟลเดอร์โปรเจกต์ ข้อมูลเหล่านี้ไม่ถูก sync โดยโปรแกรมไปยัง Google Drive หรือบริการอื่น

## การส่งต่อข้อมูล

เมื่อเจ้าของเริ่ม OAuth หรือสั่ง upload โปรแกรมส่งคำขอและไฟล์ที่เลือกไปยัง Google/YouTube ผ่าน YouTube Data API Services เพื่อให้ Google ยืนยันบัญชีและจัดการ channel/video ตามคำสั่ง เครื่องมือไม่ส่งข้อมูลไปให้ผู้โฆษณาหรือผู้ให้บริการ AI และไม่ให้ third party เข้าถึง job database ในเครื่อง Google ประมวลผลตามนโยบายของ Google เอง

อ่าน [Google Privacy Policy](https://policies.google.com/privacy) และ [YouTube Terms of Service](https://www.youtube.com/t/terms)

## การเก็บรักษาและลบ

- OAuth token เก็บตราบเท่าที่เจ้าของยังต้องการเชื่อมต่อ และลบเมื่อ revoke ผ่านคำสั่งของแอปหรือเมื่อ Google ปฏิเสธ refresh grant
- API-derived snapshots จะถูกตรวจ refresh ทุก 29 วัน; ถ้า refresh ไม่สำเร็จหรือข้อมูลครบ 30 วัน ระบบ maintenance ลบ API fields และ video ID ที่หมดอายุ รายละเอียดกำหนดเวลาเป็นไปตาม [YouTube Developer Policies](https://developers.google.com/youtube/terms/developer-policies)
- เมื่อเจ้าของขอลบข้อมูลผ่าน `kt404-youtube profile delete-account-data --channel-id CHANNEL_ID` โปรแกรมลบ job records, API snapshots, resumable state, channel ID และ approved pilot ID ของช่องนั้นในเครื่องโดยเร็ว แต่คงค่าปฏิบัติงานของโปรไฟล์ไว้ คำสั่งนี้ **ไม่ลบวิดีโอที่อยู่บน YouTube** และการลบ job state ทำให้การส่งซ้ำในอนาคตไม่ถูกกันด้วย hash เดิมอีก
- เมื่อยกเลิกสิทธิ์ด้วย `kt404-youtube profile revoke-authorization --channel-id CHANNEL_ID` โปรแกรมส่งคำขอ revoke ไป Google, ลบ token และลบข้อมูลช่องในเครื่อง
- หากเจ้าของถอน consent จาก [Google Security permissions](https://security.google.com/settings/security/permissions) ให้รัน `kt404-youtube maintenance refresh` หลังจากนั้นเพื่อยืนยัน authorization; token ที่ refresh ไม่ได้จะถูกลบและ API data ของช่องถูกลบ
- ตามนโยบาย YouTube การลบ authorized data หลังถอนสิทธิ์ผ่านกลไกของแอปต้องทำโดยเร็วและไม่เกิน **7 วัน**; หากถอนผ่าน Google Security settings ต้องลบ API data ภายใน **30 วัน**; คำขอลบข้อมูลจากเจ้าของทำโดยเร็วและไม่เกิน **7 วัน**

นโยบายนี้อธิบายข้อมูล API เท่านั้น ไม่ได้ลบ source files ที่เจ้าของเก็บใน Google Drive/เครื่อง และไม่ได้ลบวิดีโอหรือ thumbnail ที่อัปโหลดแล้วจาก YouTube

## การเปลี่ยนแปลงนโยบาย

เจ้าของจะปรับเอกสารนี้เมื่อ data flow เปลี่ยน และให้ผู้ใช้ตรวจ/ยอมรับ policy revision ใหม่ก่อนใช้ API หากคำถามหรือคำขอลบข้อมูล ให้ติดต่อ **[ช่องทางติดต่อจริงที่ใส่ก่อนเผยแพร่]**
