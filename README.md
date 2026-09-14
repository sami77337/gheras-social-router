# Gheras Social Router

المشروع الرئيسي لإدارة تعليقات ورسائل **غراس العلم للعلم الشرعي** على Facebook وInstagram وTelegram وYouTube، مع توجيه آمن للمحتوى وربط محكوم بمسار الفتاوى والمراجعة البشرية.

## التدفق المعتمد

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
                    │
                    ▼
             Classification
                    │
               ┌────┼────┐
               ▼    ▼    ▼
              FAQ  SUPERVISOR  FATWA
               │      │        │
               └──────┴────────┘
                      │
                      ▼
             Publishing Dispatcher
                      │
          ┌───────────┼───────────┬───────────┐
          ▼           ▼           ▼           ▼
      Facebook    Instagram    Telegram     YouTube
```

## قواعد V1 غير القابلة للتجاوز

- الذكاء الاصطناعي لا يصدر فتوى ولا يكتب أو يعيد صياغة جواب شرعي آليًا.
- أي محتوى ديني محتمل يُوجَّه إلى `FATWA`.
- الإجابات الآلية من FAQ تتطلب سجلًا معتمدًا ودائمًا ومطابقة مفتاح دقيقة؛ لا يوجد fuzzy lookup.
- المحتوى غير الواضح أو منخفض الثقة يذهب للمراجعة البشرية.
- `Moderation` يسبق `Classification`.
- يتم حفظ الحدث قبل المعالجة (`persist first`).
- الإدخال والنشر idempotent لمنع التكرار.
- حالات النشر غير المؤكدة لا يعاد إرسالها بشكل أعمى؛ تُجمّد للتسوية (`reconciliation`).
- لا تُحفظ Tokens أو Secrets داخل GitHub.
- Facebook وInstagram وTelegram وYouTube تُطبّع إلى نموذج أحداث موحد خلف Adapters منفصلة.
- X/Twitter خارج نطاق V1.

## التقنية

- Python 3.12
- FastAPI
- SQLite في V1
- httpx async للتكاملات الخارجية المحقونة
- OpenAI Responses API client اختياري للـstructured moderation/classification خلف sandbox permit؛ لا يوجد production model افتراضي مفروض في الكود
- pytest + Ruff + Mypy
- pip-audit + exact dependency locks + reproducibility CI gates

## حالة البناء

**V1 engineering through Phase 19 موجود الآن على `main`.**

تم دمج الـintegrated stack عبر PR #44 في 2026-09-14، ثم اجتاز `main` post-merge CI run `34836900921` كامل البوابات التالية:

- production lock verification;
- dependency consistency;
- production/build/development SCA;
- production-environment reproduction;
- Ruff;
- Mypy;
- Pytest.

الدمج إلى `main` **ليس تفعيلًا Production**. ما تزال بوابات التشغيل الخارجي موثقة في `docs/HUMAN_GATES.md`، ومنها credentials/scopes الحقيقية، provider sandbox validation، supervised FATWA integration، representative Shadow evaluation، production-equivalent restore rehearsal، قرارات TLS/ingress/monitoring، والتفعيل الصريح للنشر الحي.

## حدود التشغيل الحالية

- `app.main:create_app()` يركّب health endpoint فقط افتراضيًا؛ provider ingress غير مفعّل تلقائيًا.
- clients الخارجية موجودة خلف `app/integrations/live/` وتحتاج `SandboxExecutionPermit` محقونًا صراحةً.
- configuration أو environment variables لا تنشئ permit للتنفيذ الخارجي.
- لا يوجد production execution permit في V1 الحالي.
- FATWA publication policy الافتراضية تمنع الرد على المنصة الأصلية حتى يُتخذ قرار تشغيل صريح مختلف بعد اكتمال التحقق الخارجي.

## تشغيل محلي

```bash
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload
```

ثم:

```text
GET http://127.0.0.1:8000/health
```

## الاختبارات

```bash
ruff check app tests scripts
mypy app
pytest
```

## Legacy

مسار Facebook القديم لم يعد مسارًا تشغيليًا معتمدًا على `main`:

- workflow المجدول القديم `.github/workflows/bot.yml` أزيل؛
- root `main.py` أصبح fail-closed retired stub؛
- ملفات runtime القديمة المتتبعة أزيلت من active code line؛
- التاريخ السابق بقي محفوظًا في Git ولم تتم إعادة كتابة history.

إفادة أن البوت القديم كان متوقفًا قبل هذا cutover هي إفادة مالك المستودع، وليست تحققًا مستقلًا من runtime الإنتاجي.