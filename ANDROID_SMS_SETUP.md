# NEYRON SMS — o‘qituvchi telefonini ulash

## Hozirgi holat
Bu loyiha feature/neyron-auto-sms branchida ishlab chiqilmoqda. Hali main ga qo‘shilmagan va Render production xizmatiga deploy qilinmagan. GitHub Actions build tekshiruvi muvaffaqiyatli tugamaguncha APK tayyor deb hisoblanmaydi.

## O‘rnatish tartibi
1. GitHub Actions ichida Build NEYRON SMS APK workflow muvaffaqiyatli tugasin.
2. Workflow natijasidagi neyron-sms-debug-apk artifact ZIP faylini yuklab oling va ichidan app-debug.apk ni ajrating.
3. APK ni o‘qituvchining Android telefoniga o‘rnating.
4. NEYRON Telegram Mini App → Sozlama → Avtomatik SMS → Telefonni ulash kodini olish ni bosing.
5. 6 xonali, 10 daqiqalik bir martalik kodni Android ilovasiga kiriting.
6. SMS va bildirishnoma ruxsatlarini bering, so‘ng SMS XIZMATINI YOQISH ni bosing.
7. Android sozlamalarida standart SMS SIM-kartasi to‘g‘ri tanlanganini tekshiring.

## Muhim cheklovlar
- SMS o‘qituvchining telefonidagi standart SMS SIM-kartasidan yuboriladi; to‘lov mobil operator balansidan yechiladi.
- Ota-onaning telefon raqami o‘quvchi yozuvidagi students.phone maydonida bo‘lishi kerak.
- Telefon internetga ulangan va ilovaning old fondagi xizmati faol bo‘lishi kerak.
- Android 15+ da dataSync old fondagi xizmatiga 24 soat ichida jami 6 soatlik limit qo‘yilgan. Limit tugasa, o‘qituvchi ilovani qayta ochib xizmatni qayta yoqishi kerak.
- Serverdagi sent holati Android SMS yuborish so‘rovini qabul qilganini bildiradi; operator tomonidan ota-onaga yetkazilganini kafolatlamaydi.
- SMS xabari Unicode matn bo‘lgani uchun operator tarifiga qarab bitta xabar bir nechta SMS segmentiga bo‘linishi mumkin.
- O‘qituvchi Mini App orqali SMS ni serverda o‘chirishi mumkin. Android ilovasidagi VAQTINCHA TO‘XTATISH faqat shu telefondagi tekshirish xizmatini to‘xtatadi.

## Texnik
- Android package: uz.itkoders.neyron.sms
- Server: https://neuron-v2.onrender.com
- Pairing code: 10 daqiqa amal qiladi, bir marta ishlatiladi.
- Qurilma tokeni serverda faqat SHA-256 xesh ko‘rinishida saqlanadi.