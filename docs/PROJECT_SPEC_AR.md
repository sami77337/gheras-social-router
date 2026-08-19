# مواصفات مشروع غراس — Social Comment Router V1

## الهدف

تحويل المستودع الحالي من Facebook auto-reply بسيط إلى نظام موحّد يدير تعليقات غراس على Facebook وInstagram وTelegram، مع تصنيف ذكي ومسارات بشرية وآلية واضحة.

## النطاق

### داخل V1

- Facebook comments.
- Instagram comments.
- Telegram comments/messages ذات الصلة بالنظام.
- Moderation للنصوص والصور قبل التصنيف.
- GPT-5.6 Luna لتصنيف التعليق فقط ضمن المسارات المعتمدة.
- Approved FAQ replies.
- Supervisor escalation للحالات غير المعروفة أو منخفضة الثقة.
- Fatwa routing إلى البوت الحالي بدون توليد فتوى من الذكاء الاصطناعي.
- إرجاع الرد إلى المنصة الأصلية عند اختيار ذلك.
- Shadow Mode قبل التشغيل الآلي الكامل.

### خارج V1

- X/Twitter.
- Fine-tuning.
- Microservices معقدة.
- Redis/Celery/Kafka ما لم يظهر احتياج حقيقي لاحقًا.
- توليد فتاوى بواسطة AI.

## التدفق

```text
Instagram ─┐
Facebook  ─┼──> Social Collector
Telegram  ─┘        │
                    ▼
             Moderation Filter
          فحص إساءة / صور / محتوى ضار
                    │
             ┌──────┴──────┐
             ▼             ▼
           مخالف          سليم
             │             │
      إخفاء / مراجعة       ▼
                       GPT-5.6 Luna
                    تصنيف نوع التعليق
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
          سؤال معروف    غير معروف     فتوى
               │           │           │
           رد تلقائي    المشرفون    بوت الفتاوى
                           │           │
                           ▼           ▼
                          الرد      جواب الشيخ
                                        │
                                        ▼
                             اختيار مكان النشر
                                        │
                           ┌────────────┼────────────┐
                           ▼            ▼            ▼
                      Telegram فقط   التعليق       الاثنين
                       [الافتراضي]
```

## التصنيف

المخرجات المنطقية المسموحة بعد Moderation:

- `FAQ`
- `SUPERVISOR`
- `FATWA`

يجب أن يكون إخراج النموذج Structured Output مع درجة ثقة، وألا يعتمد النظام على نص حر لاتخاذ قرار تنفيذي.

## سياسة الخطأ الآمن

- شك بين FAQ وSUPERVISOR → SUPERVISOR.
- شك أن التعليق قد يكون سؤالًا شرعيًا → FATWA.
- فشل النموذج أو API → لا رد آلي؛ تحفظ الحالة وتُعاد المحاولة أو تُصعّد للبشر.
- لا يتم حذف/إخفاء محتوى مشكوك به دون سياسة Moderation واضحة.

## FAQ

- الردود التشغيلية تأتي من قاعدة أجوبة معتمدة.
- النموذج يحدد intent/key فقط.
- البيانات المتغيرة مثل المواعيد والروابط وحالة التسجيل لا تُخترع من النموذج.

## الاعتمادية

- حفظ الحدث قبل معالجته.
- Unique key لكل platform event لمنع التكرار.
- تخزين processing state في قاعدة البيانات.
- outbound actions تسجل قبل/بعد التنفيذ لضمان عدم تكرار الرد.
- retries محدودة مع backoff.

## الأمن والخصوصية

- الأسرار من Environment/Secrets فقط.
- عدم تسجيل Tokens أو Webhook secrets.
- أقل صلاحيات ممكنة لحسابات Meta وTelegram.
- عدم نشر بيانات حقيقية للمستخدمين داخل الاختبارات أو المستودع.

## مراحل التنفيذ

1. Bootstrap.
2. Core durable processing.
3. Moderation.
4. Luna classifier.
5. FAQ engine.
6. Telegram supervisor workflow.
7. Facebook + Instagram adapter.
8. Fatwa integration bridge.
9. Reply publishing.
10. Evaluation + Shadow Mode + final audit.

## بوابة التشغيل

لا يتم تفعيل auto-reply على الإنتاج قبل:

- نجاح الاختبارات الكاملة.
- اختبار idempotency وإعادة الإرسال.
- اختبار restart recovery.
- إثبات عدم توليد AI لفتوى.
- تقييم dataset حقيقي من تعليقات غراس في Shadow Mode.
- مراجعة security وsecrets.
