# Rollar — to'liq ma'lumotnoma (20 rol)

Manba: `backend/app/game_engine/roles.py` (`description`, `max_charges`,
`can_target_self`, `unique`), `managers.py` (`NightResolver`,
`INVESTIGATOR_GROUPS`, `WinConditionManager`), `engine.py`
(`submit_night_action`, `reveal_mayor`, `gunner_shoot`),
`compositions.py` (qaysi o'yinchi sonida qaysi rol chiqadi) va
`bot_players.py` (botlar mantig'i).

Frontenddagi (`app.js`) matnlar shu hujjatga moslab tuzatildi — kelajakda
ham **kod birlamchi manba**, frontend matni emas.

---

## Umumiy qoidalar

**Tungi harakat cheklovlari** (`engine.submit_night_action`):

- Bir kechada bitta harakat; qayta yuborib bo'lmaydi.
- Nishon **tirik** bo'lishi shart — yagona istisno: Medium (seans), unda
  nishon **o'lgan** bo'lishi shart.
- O'ziga nishon olish faqat `can_target_self=true` rollarda (amalda —
  faqat Doktor).
- Nishonsiz harakatlar: Veteran (`ALERT`) va Arsonist (`IGNITE`).

**Kechani hal qilish tartibi** (`NightResolver.resolve`) — bu tartib
muhim, chunki natijalar bir-biriga bog'liq:

1. Himoyalar (Doktor, Himoyachi)
2. Tayyorlov effektlari (Framer, Silencer, Arsonist benzini)
3. O'ldirishlar to'planadi (mafiya, Serial Killer, Veteran ehtiyoti, yong'in)
4. Himoyalar o'limlarga qarshi qo'llanadi, o'limlar yoziladi
5. Tekshiruv/kuzatuv natijalari (o'limlardan **keyin**, ya'ni natija yakuniy)

**G'alaba shartlari** (`WinConditionManager.check`):

| Shart | G'olib |
|---|---|
| Mafiya ham, o'ldiruvchi neytral ham qolmadi | Shahar |
| Mafiya soni ≥ (shahar + o'ldiruvchi neytral) | Mafiya |
| Faqat o'ldiruvchi neytral(lar) qoldi | Neytral |
| Yagona tirik o'yinchi — Survivor | Neytral |

**Tekshiruvchi (Investigator) guruhlari** — `INVESTIGATOR_GROUPS`, 8 ta:

1. Doctor, Bodyguard, Veteran
2. Commissioner, Consigliere
3. Investigator, Tracker, Watcher
4. Mafioso, Don
5. Framer, Silencer
6. Serial Killer, Arsonist
7. Survivor, Jester
8. Citizen, Mayor, Gunner, Medium

**Botlar haqida umumiy** (`bot_players.py`): botlar 2–7 soniya "o'ylab"
harakat qiladi; mafiya botlari hech qachon o'z hamkasbini nishonga
olmaydi; nishonsiz va halokatli harakatlar (Veteran ehtiyoti, yong'in)
faqat **25% ehtimol** bilan ishlatiladi; ovoz berishda tasodifiy tirik
o'yinchini tanlaydi; **kunduzgi chatga yozmaydi** (ongli qaror).

---

# MAFIYA

## 1. Don

| | |
|---|---|
| Fraksiya | Mafiya |
| Tungi harakat | `KILL` (mafiya ovozi) |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta (unique) |
| Qachondan | 6+ (barcha o'yinlarda) |
| Tekshiruvchi guruhi | Mafioso, Don |

**Mexanika.** Har kecha mafiya a'zolari bilan birga o'ldirish nishoniga
ovoz beradi. Eng ko'p ovoz olgan nishon o'ldiriladi. Ovozlar teng
bo'lsa — **Donning ovozi hal qiladi** (agar u tirik bo'lsa va teng
nishonlardan biriga ovoz bergan bo'lsa). Don yo'q bo'lsa (yoki teng
nishonlarning birortasiga ovoz bermagan bo'lsa), teng holatda tizimning
urug'langan (seeded) tasodifiy generatori orasidan birini tanlaydi —
**hech qachon** birinchi yuborilgan ovoz yoki so'rov yetib kelish tartibi
bo'yicha emas.

**Maxsus.** Komissar tekshiruvida Don **doim** `not_mafia` bo'lib
ko'rinadi. Lekin bu himoya faqat Komissarga tegishli: Konsilyeri aniq
rolni ko'radi, Tergovchi esa uni "Mafioso/Don" guruhida ko'rsatadi.

**Botlar.** Mafiya bo'lmagan tirik o'yinchilardan tasodifiy birini
tanlaydi.

## 2. Mafioso

| | |
|---|---|
| Fraksiya | Mafiya |
| Tungi harakat | `KILL` (mafiya ovozi) |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | **Bir nechta bo'lishi mumkin** (unique=False) |
| Qachondan | 6+ (1 ta), 16+ (2 ta), 22+ (3 ta), 25 (4 ta) |
| Tekshiruvchi guruhi | Mafioso, Don |

**Mexanika.** Don bilan bir xil ovoz beradi. `roles.py` tavsifida "Don
o'lsa, eng yuqori ustuvorlikdagi Mafioso hal qiluvchi ovozga aylanadi"
deyilgan — **kodda esa** Don yo'q bo'lganda teng ovozlar oddiygina
**eng erta yuborilgan ovoz** foydasiga hal qilinadi, alohida
"ustuvorlik" ro'yxati yo'q. (Quyidagi "Nomuvofiqliklar" bo'limiga
qarang.)

**Botlar.** Don bilan bir xil.

## 3. Consigliere (Konsilyeri)

| | |
|---|---|
| Fraksiya | Mafiya |
| Tungi harakat | `INVESTIGATE` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 10+ |
| Tekshiruvchi guruhi | Commissioner, Consigliere |

**Mexanika.** Har kecha bitta o'yinchining **aniq rolini** biladi
(`exact_role`). Framer uni chalg'ita olmaydi, Donning "toza" himoyasi
ham unga ta'sir qilmaydi.

**Botlar.** Mafiya bo'lmagan tirik o'yinchidan tasodifiy biri.

## 4. Framer

| | |
|---|---|
| Fraksiya | Mafiya |
| Tungi harakat | `FRAME` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 13+ |
| Tekshiruvchi guruhi | Framer, Silencer |

**Mexanika.** Nishonga olingan o'yinchi **shu kechada** Komissar
tekshirsa `mafia` bo'lib chiqadi. Effekt bir kecha davom etadi —
`PhaseManager.to_night()` har kecha `framed` bayrog'ini tozalaydi.
Konsilyeri va Tergovchiga ta'sir **qilmaydi**.

**Botlar.** Mafiya bo'lmagan tasodifiy tirik o'yinchi.

## 5. Silencer

| | |
|---|---|
| Fraksiya | Mafiya |
| Tungi harakat | `SILENCE` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 18+ |
| Tekshiruvchi guruhi | Framer, Silencer |

**Mexanika.** Nishon ertasi kuni ikki narsani qila olmaydi: chatga yozish
(`send_chat_message` rad etadi) va **ovoz berish** (`VoteManager` rad
etadi). Effekt keyingi kechada tozalanadi.

**Botlar.** Sukutga olingan bot ovoz bermay o'tkazib yuboradi.

---

# SHAHAR

## 6. Commissioner (Komissar)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `INVESTIGATE` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 6+ |
| Tekshiruvchi guruhi | Commissioner, Consigliere |

**Mexanika.** Natija faqat ikki xil: `mafia` yoki `not_mafia`. Tartib:

1. Nishon **Don** → doim `not_mafia`
2. Nishon **framed** → `mafia`
3. Aks holda → fraksiyasi bo'yicha

Ya'ni Serial Killer va Arsonist ham Komissar uchun `not_mafia` bo'lib
ko'rinadi — ular Mafiya fraksiyasida emas.

**Botlar.** O'zidan boshqa tasodifiy tirik o'yinchi.

## 7. Doctor (Doktor)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `PROTECT` |
| Zaryadlar | Cheksiz |
| O'ziga | **Ha** (yagona rol) |
| Nusxa | 1 ta |
| Qachondan | 6+ |
| Tekshiruvchi guruhi | Doctor, Bodyguard, Veteran |

**Mexanika.** Nishonni shu kechadagi har qanday o'limdan saqlaydi —
mafiya, Serial Killer, Veteran ehtiyoti va yong'in, hammasidan.
O'zini davolashi mumkin, lekin **ketma-ket ikki kecha emas**: agar
oldingi kecha o'zini davolagan bo'lsa, bu safar harakat **jimgina
bekor bo'ladi** (xato ham chiqmaydi, himoya ham bo'lmaydi).

**Botlar.** `can_target_self=True` bo'lgani uchun o'zi ham tanlov
ro'yxatiga qo'shiladi.

## 8. Investigator (Tergovchi)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `INVESTIGATE` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 6+ |
| Tekshiruvchi guruhi | Investigator, Tracker, Watcher |

**Mexanika.** **Aniq rolni bermaydi.** Nishonning haqiqiy roli qaysi
`INVESTIGATOR_GROUPS` guruhida bo'lsa, **o'sha guruhning butun ro'yxati**
qaytariladi. Masalan Doktor tekshirilsa → "Bodyguard, Doctor, Veteran".
Framer unga ta'sir qilmaydi.

> ⚠️ Frontendda avval "rol kategoriyasini (Mafiya/Shahar/Neytral)
> biladi" deb yozilgan edi — bu **noto'g'ri** edi, tuzatildi.

**Botlar.** Tasodifiy tirik o'yinchi.

## 9. Tracker (Izquvar)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `TRACK` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 10+ |
| Tekshiruvchi guruhi | Investigator, Tracker, Watcher |

**Mexanika.** Nishon **kimning oldiga borgani**ni ko'rsatadi
(`visited`). Nishon o'sha kecha hech narsa qilmagan yoki nishonsiz
harakat (Veteran ehtiyoti, yong'in) qilgan bo'lsa — natija `null`.

**Botlar.** Tasodifiy tirik o'yinchi.

## 10. Watcher (Kuzatuvchi)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `WATCH` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 12+ |
| Tekshiruvchi guruhi | Investigator, Tracker, Watcher |

**Mexanika.** Izquvarning teskarisi: nishonning oldiga **kimlar
kelgani**ni ro'yxat qilib beradi (`visitors`). Kuzatuvchining o'zi
ro'yxatdan chiqarib tashlanadi. Nishonsiz harakat qilganlar hech
kimga "tashrif buyurmagan" hisoblanadi.

**Botlar.** Tasodifiy tirik o'yinchi.

## 11. Bodyguard (Himoyachi)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `GUARD` |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 14+ |
| Tekshiruvchi guruhi | Doctor, Bodyguard, Veteran |

**Mexanika.** Qo'riqlanayotgan o'yinchiga hujum bo'lsa:

- himoyalangan o'yinchi **omon qoladi**;
- Himoyachining o'zi **o'ladi** (hujumni to'sib);
- hujumchi (mafiya) ham **omon qoladi** — hech qanday almashinuv
  (trade) yo'q.

Muhim: Doktor himoyasi **birinchi** tekshiriladi — ikkalasi bir
o'yinchida bo'lsa, Doktor saqlaydi va Himoyachi omon qoladi.

**Botlar.** `can_target_self=False`, shuning uchun o'zidan boshqa
tasodifiy tirik o'yinchi.

## 12. Mayor (Mer)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | Yo'q |
| Kunduzgi harakat | `REVEAL` |
| Zaryadlar | 1 marta (qaytarib bo'lmaydi) |
| Nusxa | 1 ta |
| Qachondan | 13+ |
| Tekshiruvchi guruhi | Citizen, Mayor, Gunner, Medium |

**Mexanika.** Yashirin holda ovoz og'irligi = 1. Faqat **muhokama
bosqichida** (`DAY_DISCUSSION`) o'zini oshkor qila oladi; shundan keyin
`vote_weight = 3` (**x3**). Qayta yashirinib bo'lmaydi. Ikkinchi marta
oshkor qilishga urinish rad etiladi.

> ⚠️ Frontendda "2 baravar" deb yozilgan edi — kodda **3 baravar**,
> tuzatilgan.

**Botlar.** Bot-Mer hech qachon o'zini oshkor qilmaydi (kunduzgi
harakatlar bot mantig'ida umuman yo'q).

## 13. Veteran

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `ALERT` (nishonsiz) |
| Zaryadlar | **2 marta** |
| O'ziga | Yo'q (nishon yo'q) |
| Nusxa | 1 ta |
| Qachondan | 15+ |
| Tekshiruvchi guruhi | Doctor, Bodyguard, Veteran |

**Mexanika.** Ehtiyot rejimi yoqilgan kechada uning oldiga kelgan
**hamma** o'ladi — do'stmi, dushmanmi, farqi yo'q (Doktor himoyalagan
mehmon omon qoladi). Ehtiyot Veteranning o'zini o'limdan
**saqlamaydi**: rejim o'chiq kechalarda ham, yoqilgan kechalarda ham u
mafiya hujumiga oddiy o'yinchi kabi ochiq.

> ⚠️ Frontendda "birinchi hujumdan o'lmaydi" deb yozilgan edi — bu
> **noto'g'ri** edi, tuzatilgan.

Cheklov ikki joyda tekshiriladi: `submit_night_action` (2 ta zaryad
tugagan bo'lsa xato) va `NightResolver` (hisoblagichni oshiradi).

**Botlar.** Nishonsiz halokatli harakat — har kechada faqat **25%**
ehtimol bilan yoqadi.

## 14. Medium

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | `SEANCE` |
| Zaryadlar | Cheksiz |
| Nishon | **Faqat o'lgan o'yinchi** |
| Nusxa | 1 ta |
| Qachondan | 17+ |
| Tekshiruvchi guruhi | Citizen, Mayor, Gunner, Medium |

**Mexanika.** O'yindagi yagona rol, u **tirik emas, o'lgan** o'yinchini
nishonga oladi. Bir tomonlama seans kanali ochiladi (v1 da bu faqat
bayroq — `seance_open_with`; chatni ulash frontend ishi).

**Muhim:** birinchi kechada hech kim o'lmagan bo'ladi, shuning uchun
Medium umuman harakat qila olmaydi. Bu **kutilgan xatti-harakat**, xato
emas. (Lekin quyidagi "Nomuvofiqliklar" 4-bandiga qarang.)

> ⚠️ Avval bu rol **umuman ishlamas edi** — `submit_night_action` hamma
> harakat uchun tirik nishon talab qilardi. Tuzatilgan va test bilan
> tasdiqlangan.

**Botlar.** Tasodifiy **o'lgan** o'yinchini tanlaydi; o'lgan hech kim
bo'lmasa, kechani o'tkazib yuboradi.

## 15. Gunner (Otuvchi)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | Yo'q |
| Kunduzgi harakat | `SHOOT` |
| Zaryadlar | **2 ta o'q** |
| Nusxa | 1 ta |
| Qachondan | 18+ |
| Tekshiruvchi guruhi | Citizen, Mayor, Gunner, Medium |

**Mexanika.** Faqat `DAY_DISCUSSION` bosqichida otadi. O'q **darhol**
o'ldiradi — hech qanday himoya (Doktor, Himoyachi) kunduzgi o'qqa
qarshi ishlamaydi. Har otishdan keyin g'alaba sharti tekshiriladi.
O'qlar tugasa xato qaytadi.

**Botlar.** Bot-Otuvchi hech qachon otmaydi (kunduzgi harakatlar bot
mantig'ida yo'q).

## 16. Citizen (Fuqaro)

| | |
|---|---|
| Fraksiya | Shahar |
| Tungi harakat | Yo'q |
| Nusxa | **Bir nechta** (unique=False) |
| Qachondan | 6+ (o'yinchi soniga qarab 2–5 ta) |
| Tekshiruvchi guruhi | Citizen, Mayor, Gunner, Medium |

**Mexanika.** Hech qanday qobiliyati yo'q. Muhokama va ovoz. Kechasi
harakat yuborishga urinsa `"Your role has no night action"` xatosi
qaytadi, va u kechani hal qilishda "kutilayotganlar" ro'yxatiga ham
kirmaydi.

---

# NEYTRAL

## 17. Survivor

| | |
|---|---|
| Fraksiya | Neytral |
| Tungi harakat | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 20+ |
| Tekshiruvchi guruhi | Survivor, Jester |

**Mexanika (kodda).** `WinConditionManager` uni g'olib deb faqat bitta
holatda belgilaydi: **yagona tirik o'yinchi bo'lib qolsa**.

> ⚠️ `roles.py` tavsifi ("kim yutishidan qat'i nazar, o'yin oxirida
> tirik bo'lsa yutadi") kodga **mos emas** — pastdagi "Nomuvofiqliklar"
> 1-bandiga qarang.

**Botlar.** Tungi harakati yo'q, faqat ovoz beradi.

## 18. Jester

| | |
|---|---|
| Fraksiya | Neytral |
| Tungi harakat | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 22, 23, 25 (24 da yo'q) |
| Tekshiruvchi guruhi | Survivor, Jester |

**Mexanika.** Agar kunduzgi **ovoz berish** natijasida osilsa
(`reason == "day_vote"`), `jester_won = True` belgilanadi va o'yin
qolgan fraksiyalar uchun davom etadi. Boshqa yo'l bilan o'lsa (mafiya,
o'q, Veteran, yong'in) — yutmaydi.

> ⚠️ `jester_won` bayrog'i qo'yiladi, lekin g'olib ro'yxatiga
> qo'shilmaydi — "Nomuvofiqliklar" 2-bandiga qarang.

**Botlar.** Maxsus mantiq yo'q; bot-Jester osilishga harakat qilmaydi.

## 19. Serial Killer

| | |
|---|---|
| Fraksiya | Neytral |
| Tungi harakat | `KILL` (yolg'iz) |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | 24, 25 |
| Tekshiruvchi guruhi | Serial Killer, Arsonist |

**Mexanika.** Har kecha bitta o'yinchini o'ldiradi, mafiya ovozidan
mustaqil. Doktor va Himoyachi to'sib qola oladi. G'alaba hisobida u
"o'ldiruvchi neytral" sifatida mafiyaga teng xavf deb qaraladi: mafiya
g'alabasi shartida u ham hisobga olinadi, va shahar u tirik ekan
yutolmaydi.

**Botlar.** Tasodifiy tirik o'yinchi (mafiya filtri unga tegishli emas —
u mafiya emas, hammani nishonga oladi).

## 20. Arsonist (O't qo'yuvchi)

| | |
|---|---|
| Fraksiya | Neytral |
| Tungi harakat | `DOUSE` (+ `IGNITE`) |
| Zaryadlar | Cheksiz |
| O'ziga | Yo'q |
| Nusxa | 1 ta |
| Qachondan | **Hech qachon** — hech bir kompozitsiyada yo'q |
| Tekshiruvchi guruhi | Serial Killer, Arsonist |

**Mexanika.** Ikki bosqichli: kecha-kecha o'yinchilarni benzin bilan
belgilaydi (`doused_players` to'plamiga qo'shiladi), keyin `IGNITE`
(nishonsiz) **barcha belgilanganlarni bir vaqtda** o'ldiradi va
ro'yxatni tozalaydi. Doktor/Himoyachi yong'inga qarshi ham ishlaydi.

**Muhim:** rol to'liq yozilgan, lekin `compositions.py` da 6–25
o'yinchining **birortasida ham** ishlatilmagan
(`validate_all_compositions` uni hatto taqiqlaydi:
`assert R.ARSONIST not in roles`). Ya'ni bu rol amalda **o'yinda
chiqmaydi** — kelajakdagi rejim uchun tayyor turibdi.

**Botlar.** `DOUSE` — tasodifiy tirik o'yinchi; `IGNITE` — nishonsiz,
25% ehtimol bilan.

---

# Kodda topilgan nomuvofiqliklar (tuzatilmagan)

Bular frontend matni emas, **backend mantig'i** bilan bog'liq. Hech
biri o'yinni buzmaydi, shuning uchun so'ralmagan holda tegilmadi.

### 1. Survivor g'alabasi tavsifga mos emas
`roles.py`: "kim yutishidan qat'i nazar, o'yin oxirida tirik bo'lsa
yutadi". `WinConditionManager.check`: uni g'olib deb faqat **yagona
tirik** qolganda belgilaydi. Shahar yoki mafiya yutganda tirik Survivor
g'olib ro'yxatiga tushmaydi.

### 2. Jester g'alabasi hech qayerda ko'rinmaydi
`DeathManager.eliminate` `jester_won = True` qo'yadi, lekin bu bayroq
`WinConditionManager` ham, `get_player_view`ning `stats.won` maydoni ham
o'qimaydi — o'yinchi yutganini bilmaydi.

### 3. Arsonist statistikasi hisoblanmaydi
`engine._credit_night_kills` `reason == "arsonist"` ni qidiradi, lekin
`NightResolver` `"arsonist_ignite"` deb yozadi — mos kelmaydi.
Bir vaqtda ikki hujumchi bo'lsa ham (`"mafia/serial_killer"`) hech kimga
o'ldirish yozilmaydi. Faqat statistika, o'yin natijasiga ta'siri yo'q.

### 4. Birinchi kecha har doim taymer oxirigacha kutadi
`resolve_night_if_ready` "kutilayotganlar" ro'yxatiga tungi harakati bor
barcha tiriklarni qo'shadi, shu jumladan Mediumni. Birinchi kechada
Medium harakat qila **olmaydi** (o'lgan nishon yo'q), shuning uchun
sanoq hech qachon to'lmaydi va kecha faqat taymer tugagach hal bo'ladi.
17+ o'yinchili o'yinlarda seziladi.

### 5. Veteran o'ldirishlari statistikaga yozilmaydi
`_credit_night_kills` faqat `mafia`, `serial_killer`, `arsonist`
sabablarini biladi; `veteran_alert` yo'q.
