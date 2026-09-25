# Mafia — v3 yaxshilanishlari

## Ko‘rinish
- Bosh sahifaga noir uslubidagi sarlavha va ikki ustunli menyu qo‘shildi.
- Tungi mavzuda sarlavhalar kontrasti tuzatildi.
- Tugmalar, kartalar, fokus holati va pastki navigatsiya bir xillashtirildi.
- Telefonning xavfsiz ekran chetlari va dinamik ekran balandligi hisobga olindi.
- Matn maydonlari 16px: iPhone’da yozishda avtomatik kattalashishni kamaytiradi.
- Harakatni kamaytirish sozlamasi barcha animatsiyalarga tatbiq etiladi.

## Tuzatilgan xatolar
- Eski WebSocket uzilishi yangi ulanishni o‘chirib yubormaydi.
- Almashtirilgan ulanishdan o‘yin buyruqlari qabul qilinmaydi.
- Qayta ulanishda eski hodisa ishlovchilari yangi ulanishni yopmaydi.
- Tugagan sessiya va yopilgan o‘yinlar uchun cheksiz qayta ulanish to‘xtatildi.
- Botdan o‘yinni to‘xtatish xabari klientda qayta ishlanadi.
- Ovoz berish natijalari taymerini oddiy klient buyrug‘i bilan chetlab o‘tish yopildi.
- Noto‘g‘ri JSON va noto‘g‘ri turdagi xabar maydonlari rad etiladi.
- Bir ulanishga 10 soniyada 40 xabar va 8192 belgilik xabar chegarasi qo‘yildi.
- Xabar yuborish uchun 5 soniyalik kutish chegarasi qo‘yildi.
- Bitta o‘yindagi xato umumiy taymer siklini to‘xtatmaydi; xato jurnalga yoziladi.
- Server yopilganda taymer vazifasi bekor qilinishi kutiladi.
- Advokatning amaldagi SHIELD qobiliyatiga eskirgan test moslashtirildi.
- Offline tekshiruvdagi mavjud bo‘lmagan test moduliga havola olib tashlandi.

## Tekshiruv
- To‘liq Python to‘plami: 333 test o‘tdi.
- Shundan 9 ta yangi ulanish, xabar va taymer regressiya testi.
- Offline o‘yin mexanikasi: 219 test o‘tdi (yuqoridagi to‘plam bilan qisman bir xil).
- JavaScript sintaksisi va klient qayta ulanish regressiya tekshiruvi o‘tdi.
- Python sintaksisi tekshirildi.
- To‘liq to‘plamda 2 ogohlantirish bor: kutubxona eskirgan interfeysi va test yakunidagi SQLite thread/event-loop yopilishi. Testlar muvaffaqiyatli, lekin ogohlantirishlar yashirilmagan.

## Ishga tushirish
Mavjud README va .env.example ko‘rsatmalaridan foydalaning. Bot tokeni, uzun tasodifiy SESSION_SECRET va domenni o‘zingizning serveringizda kiriting. O‘yinlar xotirada boshqarilgani sababli hozircha bitta server jarayoni (worker) bilan ishlating. Ishlayotgan serverning bazasini arxivdagi baza bilan almashtirmang.

backend ichida tekshiruv buyruqlari:

```sh
python -m pytest -q
node tools/test_client_connection.cjs
python tools/run_pure_engine_tests_offline.py
```

## Tekshirilmagan qismlar
Telegram bilan jonli guruh sinovi, haqiqiy iPhone/Safari sinovi va katta yuklama sinovi bajarilmadi. Brauzer dvigatelini yuklash muvaffaqiyatsiz bo‘lgani uchun vizual render tekshiruvi ham bajarilmadi. Bu versiya butunlay xatosiz deb kafolatlanmaydi. Eski screens-preview.html va cards-preview.html tarixiy namunalardir; amaldagi interfeys backend/app/static/index.html ichida.
