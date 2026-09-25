# v9 — bot ichidagi admin boshqaruvi

## Qayerdan ochiladi?

Bot shaxsiy chatida /start yuboring. Adminning pastki klaviaturasida
“Admin paneli” tugmasi ko‘rinadi. U bot ichidagi boshqaruv menyusini ochadi.
Oddiy foydalanuvchida bu tugma yo‘q. Har bir amal serverda ham ruxsat bilan
tekshiriladi. Eski klaviatura qolgan bo‘lsa /start yuboring.

## Murojaatlar

Foydalanuvchi “Admin bilan bog‘lanish”ni bosib, 3000 belgigacha matn yuboradi.
Admin uni shaxsiy chatida oladi; “Murojaatlar”dan javobsizlarini ko‘ra oladi.
“Javob yozish” tugmasi yoki Telegramdagi Reply orqali javob qaytariladi.
Javob yetib borgandan keyingina murojaat javob berilgan deb belgilanadi.
Murojaatlar bazada saqlanadi. Ketma-ket murojaatlar orasida 15 soniya bor.
Hozircha murojaat va javob matn shaklida ishlaydi.

## Bloklash

Murojaat yonidagi “Bloklash” tugmasi yoki panelda raqamli Telegram ID orqali.
“Blokdan chiqarish” ham mavjud. Blok bot xabarlari, Mini App sessiyasi va
o‘yin ulanishiga tatbiq qilinadi. Bu botdagi blok; Telegram guruhidan ban emas.
Admin hisoblarini bloklashdan oldin ularning admin huquqini olib tashlash kerak.

## Reklama

“Reklama yuborish” → matn, rasm yoki video → namuna → auditoriyani tanlash.
Auditoriya: bot foydalanuvchilari, bot biladigan faol guruhlar yoki ikkalasi.
Qabul qiluvchilar soni yuborishdan oldin ko‘rsatiladi.
Qoralamani bekor qilish mumkin. Ikki marta bosish ikki yuborish yaratmaydi.
Natija “Reklama tarixi”da: jami, yetkazilgan, xato/skip soni.
Bloklangan foydalanuvchilarga yuborilmaydi.

Navbat PostgreSQLda saqlanadi, webhook ichida uzoq kutmaydi. Server qayta
ishga tushganda qolgan navbat davom etadi. Agar server aynan Telegramga
yuborayotgan paytda uzilsa, natijasi noma’lum qabul qiluvchi takror
yuborilmaydi va xato hisobiga qo‘shiladi. Barcha xabarlar albatta yetkaziladi
degan kafolat yo‘q. Render Free uxlaganda navbat ham to‘xtab turadi.
Bir servis / bir worker talabi saqlanadi.

## Majburiy kanallar

1. Botni kerakli kanalga admin qiling.
2. Admin panel → Majburiy kanallar → Kanal qo‘shish.
3. Ochiq kanal: @kanal_nomi.
4. Yopiq kanal: -1001234567890 | https://t.me/+taklif_havolasi.
5. Kanal ro‘yxatidagi ❌ tugmasi talabni olib tashlaydi.

Ko‘pi bilan 10 kanal. Bot obunani Telegram orqali tekshiradi. Foydalanuvchi
botda yoki Mini Appda kanallarni ko‘radi va “Obunani tekshirish”ni bosadi.
O‘yinga kirishda ham tekshiriladi. Kanal qo‘shilganda davom etayotgan
o‘yinning mavjud ulanishi uzilmaydi; yangi kirish/qayta ulanish tekshiriladi.
Adminlar obuna talabidan ozod. Kanalga kira olmay qolgan foydalanuvchi
admin bilan bog‘lanishi mumkin. Yopiq kanal taklif havolasi aynan o‘sha
kanalga tegishli va amaldagi bo‘lishi kerak.

Qo‘shimcha adminlar uchun huquqlar Admin WebApp → Adminlar orqali beriladi:
support.view/reply, users.manage, broadcast.view/send, settings.manage.
Bot egasi ADMIN_TELEGRAM_IDS orqali barcha huquqlarga ega.

## Tekshiruv va deploy

To‘liq avtomatik testlar: 370 ta o‘tdi; 3 ta test muhiti ogohlantirishi
(1 deprecation, 2 SQLite yopilishidagi thread ogohlantirishi).
JavaScript sintaksisi va oldingi navigatsiya tekshiruvi o‘tdi.
Telegram yuborishlari testlarda taqlid qilindi; haqiqiy kanal/reklama
yuborish va Render deployi bajarilmadi.

Yangi jadvallar server ishga tushganda avtomatik yaratiladi.
Avvalgi v8 tuzatishlari va RENDER_FREE_UZ.md yo‘riqnomasi saqlangan.
Deploydan keyin /start yuborib pastki klaviaturani yangilang, so‘ng bitta
sinov foydalanuvchisi bilan murojaat/javob va obunani tekshiring.

Telegram hujjatlari:
https://core.telegram.org/bots/api#getchatmember
https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
