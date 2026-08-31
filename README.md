# Abu Jana Radar Trader (OKX)

تطبيق ويب للتداول اليدوي + خروج أوتوماتيك على عكس الإشارة، مبني على منطق مؤشر **Abu Jana Ultimate Radar Pro V13**.

## المميزات

- ربط سهل بـ OKX (Demo + Live)
- دخول يدوي بزر CALL / PUT مع تحديد الحجم
- خروج أوتوماتيك أول ما تظهر إشارة عكسية وتتقفل الشمعة
- Stop Loss حماية محسوب بـ ATR × 1.2
- واجهة ويب عربية بسيطة

## التثبيت والتشغيل

```bash
cd okx_radar_trader
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

ثم افتح المتصفح على: `http://localhost:8000`

## إعداد Demo على OKX

1. ادخل على okx.com → Trade → **Demo Trading**
2. من داخل الـ Demo اعمل API Key جديد (Read + Trade)
3. انسخ الـ Key + Secret + Passphrase
4. في التطبيق اختار **Demo** والصق المفاتيح

## إعداد Live

- اعمل API Key من الحساب الحقيقي
- صلاحيات: Read + Trade فقط (بدون Withdraw)
- حط IP Whitelist لو أمكن
- ابدأ بمبالغ صغيرة جدًا

## طريقة الاستخدام

1. اربط المفاتيح
2. تابع الشارت على TradingView (أو انتظر إشارة من التطبيق)
3. لما تحب تدخل → اكتب الحجم واضغط CALL أو PUT
4. التطبيق هيقفل الصفقة أوتوماتيك لما الإشارة تعكس

## تحذير مهم

التداول ينطوي على مخاطر عالية. استخدم الـ Demo أولًا لفترة كافية.
لا تشارك مفاتيح الـ API مع أحد.
"""
