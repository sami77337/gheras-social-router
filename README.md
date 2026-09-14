# Gheras Social Router

المشروع الرئيسي لإدارة تعليقات ورسائل **غراس العلم للعلم الشرعي** على Facebook وInstagram وTelegram وYouTube، مع توجيه ذكي للتعليقات وربط آمن ببوت الفتاوى الحالي.

## التدفق المعتمد

```text
Facebook  ─┐
Instagram ─┤
Telegram  ─┼──> Social Collector
YouTube   ─┘        │
                    ▼
             Persist-First Core
            حفظ الحدث قبل معالجته
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

## قواعد أساسية

- الذكاء الاصطناعي لا يصدر فتوى ولا يكتب جوابًا شرعيًا آليًا.
- الأسئلة المعروفة تستخدم أجوبة معتمدة، ولا يتم اختراع معلومات تشغيلية.
- التعليق غير الواضح أو منخفض الثقة يذهب للمراجعة البشرية.
- أي سؤال ديني محتمل يذهب لمسار الفتاوى بدل الرد الآلي.
- Moderation يسبق التصنيف الدلالي.
- يتم حفظ الحدث قبل المعالجة Persist First.
- جميع الأحداث والردود يجب أن تكون idempotent لمنع التكرار.
- لا تُحفظ Tokens أو Secrets أو بيانات تشغيل حساسة داخل GitHub.
- Facebook وInstagram وTelegram وYouTube تدخل من خلال Adapters منفصلة وتُطبّع إلى نموذج أحداث موحد.
- X/Twitter خارج نطاق V1.

## التقنية

- Python 3.12
- FastAPI
- SQLite في V1
- OpenAI API في المراحل اللاحقة
- aiogram في مرحلة Telegram
- httpx للاتصالات الخارجية
- pytest + Ruff + Mypy

## حالة البناء

### Phase 0 — Bootstrap

مكتملة وموجودة على `main`.

تشمل:

- تطبيق FastAPI جديد تحت `app/`.
- `/health` لا يعتمد على أي خدمة خارجية.
- Configuration من Environment Variables فقط.
- `.env.example` بلا أسرار حقيقية.
- Adapter contracts للتكاملات القادمة.
- اختبارات أولية.
- GitHub Actions CI.
- وثيقة حدود المعمارية `docs/ARCHITECTURE.md`.

### Phase 1 — Durable Events, SQLite & Idempotency

هي المرحلة النشطة التالية على الفرع:

`codex/v1-full-build`

ولا تشمل أي اتصال حي مع Meta أو Telegram أو YouTube أو OpenAI أو بوت الفتاوى.

### تشغيل محلي

```bash
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload
```

ثم:

```text
GET http://127.0.0.1:8000/health
```

### الاختبارات

```bash
ruff check .
mypy app
pytest
```

## Legacy

الكود القديم الخاص بـFacebook ما زال موجودًا مؤقتًا في جذر المستودع للاستفادة من الأجزاء المفيدة منه لاحقًا. لا تعتمد البنية الجديدة عليه كمصدر معماري نهائي، ولا تستخدم حالته المحلية كأساس لمنع التكرار في النظام الجديد.
