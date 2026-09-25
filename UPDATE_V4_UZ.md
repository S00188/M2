# Mafia v4 — davomiy tekshiruv

Bu hisobot v3 dagi vizual tekshiruv bajarilmaganligi haqidagi eslatmani yangilaydi.

## Yangi tuzatishlar
- Birinchi kirishda o‘yin paneli ko‘rinmas holatda o‘lchanayotgani sababli chat ochilib qolardi. Endi panel ko‘rsatilgach joylashadi.
- Mavzu va til tanlashda tanlangan tugma ajratib ko‘rsatiladi. Mavzu tugmasiga aria-pressed qo‘shildi.
- Ovoz berish yoki tun paytida chat yopiq bo‘lsa, foydalanuvchiga noto‘g‘ri “sukut qilingansiz” deyilmaydi.
- Yangi bosh sahifa matnlari o‘zbek, rus va ingliz tillariga moslashtirildi.
- Harakatni kamaytirish rejimida panellar darhol almashadi.
- Uzilgan transport aniqlansa, o‘yinchining connected holati ham o‘chiriladi. Eski ulanish nusxalariga yuborish cheklanadi.

## Bajarilgan sinovlar
- Python to‘plami: 334 test o‘tdi; yakuniy ulanish o‘zgarishidan keyin tegishli 10 test qayta o‘tdi.
- JavaScript sintaksisi va qayta ulanish regressiya tekshiruvi o‘tdi.
- Haqiqiy lokal HTTP/WebSocket serverga sakkizta test o‘yinchisi ulandi. Host vakolati, noto‘g‘ri JSON, yangi ulanish eskisini almashtirishi tekshirildi.
- Lobbi → rollar → tun → tong → kunduzgi muhokama → ovoz berish o‘tishlari tekshirildi. Tez sinov uchun hostning bosqichni o‘tkazish buyrug‘i ishlatildi; bu to‘liq tabiiy partiya emas.
- Chromium brauzerida amaldagi JavaScript lokal backendga ulandi. Bosh menyu, sozlamalar, profil, reyting va ovoz berish oynalari ochildi. Sahifa JavaScript xatosi qayd etilmadi.
- Bosh menyu 320, 390 va 430 piksel kenglikda, yorug‘ va qorong‘i mavzularda gorizontal chiqib ketishsiz tekshirildi.
- preview-v4 papkasida haqiqiy brauzer rasmlari bor. Player 901 — sun’iy sinov foydalanuvchisi.

## Qolgan cheklovlar
- Telegram SDK sinov obyekti bilan almashtirildi; Telegramga hech qanday xabar yuborilmadi. Bu jonli Telegram integratsiya testi emas.
- iPhone/Safari, haqiqiy Telegram guruh a’zoligi va katta yuklama tekshiruvi hali bajarilmagan.
- To‘liq Python sinovida kutubxona deprecation va test yakunidagi SQLite thread yopilishiga oid 2 ogohlantirish saqlanadi.
- v3 dagi ishga tushirish ko‘rsatmalari amal qiladi. Mavjud server bazasini arxivdagi baza bilan almashtirmang. Hozircha bitta worker ishlating.

Jonli tekshiruvning keyingi bosqichi uchun mavjud bot havolasi va hosting ma’lumoti kerak. Maxfiy bot tokenini ochiq chatga joylamang; uni hostingning maxfiy muhit o‘zgaruvchisida saqlang.
