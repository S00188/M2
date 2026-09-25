# Mafia v5 — o‘yin mantig‘i va ovoz berish oynasi

## Besh holat tuzatildi
1. Server qayta ishga tushsa, tasdiqlash bosqichining tanlangan nomzodi saqlangan holatdan tiklanadi. Tasdiqlash ovozlari avvalgidek saqlanadi.
2. Tasdiqlash rad etilsa, natijadagi chiqarilgan o‘yinchi maydoni tozalanadi; ovozlar hisobi saqlanadi.
3. Oxirgi qolgan o‘yinchi Mafia yoki Don bo‘lsa, g‘olib jamoa Mafia deb belgilanadi.
4. Sonlar tengligini tekshirishda neytral o‘yinchilar ham raqib sifatida hisoblanadi. Bu Mafia va mustaqil hujumchi uchun bir xil qo‘llanadi. Vaqtinchalik ovoz cheklovi g‘alabani sun’iy tezlashtirmaydi. Teng son holatidagi avvalgi g‘alaba qoidasi saqlandi.
5. Ovoz berish cheklovi asosiy va tasdiqlash bosqichlarida bir xil ishlaydi. Cheklangan o‘yinchini kutib taymer cho‘zilmaydi. UI ham server ruxsatlariga mos.

## Yangi ovoz oynasi
- Ismlar qisqartirilgan uch ustunli kataklar o‘rniga o‘qilishi qulay ro‘yxatda chiqadi.
- Tanlov belgilangan holda qoladi, boshqa o‘yinchining yangilanishi uni o‘chirmaydi.
- O‘ziga ovoz berish o‘chiq bo‘lsa, o‘zi nomzodlar orasida ko‘rinmaydi.
- Tasdiqlash va betaraf qolish tugmalari alohida; yuqoriga yopishuvchi boshqaruv paneli.
- Ovoz sarlavhasi, izoh va kutish xabarlari UZ/RU/EN tillarida.
- Yorug‘/qorong‘i ko‘rinishlar: preview-v5 papkasi. Rasmlardagi ismlar sinov uchun berilgan.

## Tekshiruv
Python: 343 test o‘tdi, jumladan 9 ta yangi regressiya holati. JavaScript sintaksisi va ulanish tekshiruvi o‘tdi.
Chromium: 320, 390 va 430px kenglik; uzun ismlar, tanlovning saqlanishi, cheklangan ovoz beruvchi, yorug‘/qorong‘i rejim tekshirildi. Sahifa JavaScript xatosi aniqlanmadi. Brauzer sinovi backend yaratgan sinov holati bilan bajarildi.
Oldingi SQLite test-yopilish va kutubxona deprecation ogohlantirishlari (2 ta) saqlanadi. Haqiqiy Telegram/iPhone va katta yuklama sinovi ushbu tekshiruvga kirmaydi.

Ishga tushirishda backend va frontendni birga yangilang; mavjud server bazasini arxivdagi baza bilan almashtirmang. Bir worker cheklovi saqlanadi. V3/V4 hisobotlari tarixiy; bu hisobot V5 holatini bayon qiladi.
