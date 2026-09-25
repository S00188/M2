# v7 — bot oqimi va Renderga tayyorlash

- Profil va eski profile havolalari yangilangan bosh menyuni ochadi.
- Guruhga admin sifatida qo‘shish tugmasi qo‘shildi; Telegram tasdig‘i zarur.
- Guruh uchun bitta faol o‘yin cheklovi markaziy registrda ham tekshiriladi.
- Boshlanish xabari faqat rollar sonini ko‘rsatadi, ismlarni oshkor qilmaydi.
- Yakunda jamoa, qatnashchilar, rollar va g‘oliblar ko‘rsatiladi.
- Ismlar Telegram HTMLiga xavfsiz o‘giriladi.
- Parallel xabar yuborishdan himoya va yuborish xatosidan keyin qayta urinish.
- PostgreSQL URL formatlari qabul qilinadi; productionda standart maxfiy
  kalitlar va SQLite bilan ishga tushish bloklanadi.
- Render bitta worker bilan sozlandi. RENDER_FREE_UZ.md ni o‘qing.
- Oldingi v5 o‘yin tuzatishlari va v6 dizayni saqlangan.

Tekshiruv: 352 avtomatik test o‘tdi, JavaScript sintaksisi tekshirildi.
Test muhitida 2 ogohlantirish: kutubxona deprecation xabari va SQLite test
oqimining yopilishidagi thread ogohlantirishi. Haqiqiy Telegram,
PostgreSQL va Render deployi ushbu muhitda bajarilmagan.
ZIPda ishchi/test SQLite bazasi va maxfiy .env fayli yo‘q.
