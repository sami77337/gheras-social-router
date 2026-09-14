# مواصفات مشروع غراس — Social Comment Router V1

## الهدف

تحويل المستودع الحالي من Facebook auto-reply بسيط إلى نظام موحّد يدير تعليقات ورسائل غراس على Facebook وInstagram وTelegram وYouTube، مع تصنيف ذكي ومسارات بشرية وآلية واضحة ومعالجة موثوقة تمنع التكرار وفقدان الأحداث.

## النطاق

### داخل V1

- Facebook comments.
- Instagram comments.
- Telegram comments/messages ذات الصلة بالنظام.
- YouTube comments/replies ذات الصلة بالنظام.
- توحيد أحداث المنصات الأربع داخل نموذج Domain واحد.
- Persist-first durable processing قبل أي معالجة دلالية أو رد.
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
Facebook  ─┐
Instagram ─┤
Telegram  ─┼──> Social Collector
YouTube   ─┘        │
                    ▼
             Persist-First Core
                    │
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
              FAQ      SUPERVISOR     FATWA
               │           │           │
        جواب معتمد      المشرفون    بوت الفتاوى
               │           │           │
               └───────────┴───────────┘
                           │
                           ▼
                  Publishing Dispatcher
                           │
               ┌───────────┼───────────┬───────────┐
               ▼           ▼           ▼           ▼
           Facebook    Instagram    Telegram     YouTube
```

## نموذج المنصات

القيم المسموحة في V1:

- `facebook`
- `instagram`
- `telegram`
- `youtube`

كل Platform Adapter مسؤول عن تحويل الحدث الأصلي إلى نموذج موحد قبل دخوله إلى قلب النظام. لا يجوز ربط Domain logic مباشرة بتفاصيل SDK أو payload خاصة بمنصة بعينها.

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

- حفظ الحدث قبل معالجته: Persist First, Process Later.
- Unique key لكل platform event لمنع التكرار.
- تخزين processing state في قاعدة البيانات.
- outbound actions تسجل قبل/بعد التنفيذ لضمان عدم تكرار الرد.
- retries محدودة مع backoff.
- إعادة تشغيل الخدمة لا تفقد الأحداث المقبولة أو حالتها.
- نفس الحدث الوارد أو نفس outbound action لا ينشئ أثرًا مكررًا.

## الأمن والخصوصية

- الأسرار من Environment/Secrets فقط.
- عدم تسجيل Tokens أو Webhook secrets أو authorization headers.
- أقل صلاحيات ممكنة لحسابات Meta وTelegram وYouTube/Google.
- عدم نشر بيانات حقيقية للمستخدمين أو production logs داخل الاختبارات أو المستودع.
- تخزين الحقول المطبّعة اللازمة فقط؛ لا تُحفظ payloads الخام بلا ضرورة.

## مراحل التنفيذ

1. Bootstrap.
2. Core durable processing: SQLite + event model + state machine + idempotency.
3. Moderation.
4. Luna classifier.
5. FAQ engine.
6. Telegram supervisor workflow.
7. Platform adapters: Facebook + Instagram + Telegram + YouTube.
8. Fatwa integration bridge.
9. Reply publishing dispatcher للمنصات الأربع.
10. Evaluation + Shadow Mode + security review + final regression audit.

## بوابة التشغيل

لا يتم تفعيل auto-reply على الإنتاج قبل:

- نجاح الاختبارات الكاملة.
- اختبار idempotency وإعادة الإرسال لكل منصة.
- اختبار restart recovery.
- إثبات عدم توليد AI لفتوى.
- تقييم dataset حقيقي من تعليقات غراس في Shadow Mode.
- مراجعة security وsecrets.
- إثبات أن Facebook وInstagram وTelegram وYouTube تستخدم حدود Adapter واضحة وتعيد الرد للهدف الصحيح.
