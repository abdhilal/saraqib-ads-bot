"""
سراقب ديليفري - تقرير الإعلانات اليومي على تيليجرام

كل يوم الساعة 9 المسا بيسحب أرقام الحملة من Meta Marketing API (قراءة فقط)،
وبيخلي Claude يكتب تقرير قصير بالعامية،
وبيبعته على تيليجرام.

المفاتيح بتنقرا من متغيرات البيئة (GitHub Secrets):
  META_ACCESS_TOKEN    مفتاح مستخدم النظام بصلاحية ads_read
  TELEGRAM_BOT_TOKEN   توكن البوت من BotFather
  TELEGRAM_CHAT_ID     رقم محادثتك
  ANTHROPIC_API_KEY    مفتاح Claude API (اختياري: بدونه بيوصلك تقرير أرقام بسيط)
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------- الإعدادات ----------
CAMPAIGN_ID = os.environ.get("CAMPAIGN_ID", "120247256749840138")
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v22.0")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

BUDGET_TOTAL = 48.0        # دولار
CAMPAIGN_DAYS = 14
END_DATE = "2026-11-21"

BENCHMARKS = """
- CTR على الرابط فوق 1.5% منيح، تحت 0.8% ضعيف.
- تكلفة مشاهدة صفحة الموقع: الحملات السابقة كانت حوالي 0.01 دولار، وفوق 0.05 دولار غالي.
- الميزانية 48 دولار على 14 يوم، يعني حوالي 3.4 دولار باليوم. نبّه إذا الصرف أسرع أو أبطأ بكتير.
- التكرار فوق 3 يعني الجمهور بدأ يملّ والتصميم بدو تغيير.
- لا يُنصح بتعديل الإعلان قبل 48 ساعة من آخر تعديل.
"""

INSIGHT_FIELDS = ",".join([
    "spend", "reach", "impressions", "frequency",
    "inline_link_clicks", "inline_link_click_ctr", "cost_per_inline_link_click",
    "actions", "cost_per_action_type",
])


def env(name, required=True):
    value = os.environ.get(name, "").strip()
    if required and not value:
        sys.exit(f"ناقص متغير البيئة: {name}")
    return value


def http_get_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=30) as r:
        return json.load(r)


def http_post_json(url, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# ---------- ميتا ----------
def meta(path, token, **params):
    params["access_token"] = token
    return http_get_json(f"https://graph.facebook.com/{GRAPH_VERSION}/{path}", params)


def summarize_insights(rows):
    if not rows:
        return None
    row = rows[0]

    def action(kind, key="actions"):
        for a in row.get(key, []) or []:
            if a.get("action_type") == kind:
                return float(a.get("value", 0))
        return None

    return {
        "spend_usd": float(row.get("spend", 0)),
        "reach": int(row.get("reach", 0)),
        "impressions": int(row.get("impressions", 0)),
        "frequency": round(float(row.get("frequency", 0)), 2),
        "link_clicks": int(row.get("inline_link_clicks", 0) or 0),
        "link_ctr_pct": round(float(row.get("inline_link_click_ctr", 0) or 0), 2),
        "cost_per_link_click_usd": round(float(row.get("cost_per_inline_link_click", 0) or 0), 4),
        "landing_page_views": action("landing_page_view"),
        "cost_per_landing_page_view_usd": action("landing_page_view", "cost_per_action_type"),
    }


def fetch_campaign(token):
    info = meta(
        CAMPAIGN_ID, token,
        fields="name,effective_status,status,lifetime_budget,start_time,stop_time,issues_info",
    )
    today_rows = meta(f"{CAMPAIGN_ID}/insights", token,
                     fields=INSIGHT_FIELDS, date_preset="today").get("data", [])
    total = meta(f"{CAMPAIGN_ID}/insights", token,
                 fields=INSIGHT_FIELDS, date_preset="maximum").get("data", [])
    return {
        "campaign": {
            "name": info.get("name"),
            "effective_status": info.get("effective_status"),
            "lifetime_budget_usd": (float(info["lifetime_budget"]) / 100) if info.get("lifetime_budget") else None,
            "start_time": info.get("start_time"),
            "stop_time": info.get("stop_time"),
            "issues": info.get("issues_info"),
        },
        "today": summarize_insights(today_rows),
        "since_start": summarize_insights(total),
    }


# ---------- Claude ----------
def write_report_with_claude(data, api_key):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""إنت مساعد إعلانات لصاحب تطبيق "سراقب ديليفري" بمدينة سراقب.
اكتب تقرير مسائي قصير (الساعة 9 المسا) باللهجة السورية، نص عادي بدون Markdown (لأنه رح ينبعت على تيليجرام).

الشكل:
1. سطر أول: الحكم العام (✅ ماشي منيح / ⚠️ بدو انتباه / 🔴 في مشكلة).
2. الأرقام المهمة: اليوم لحد هلق ومن البداية (الصرف، الوصول، النقرات، CTR، مشاهدات الصفحة وكلفتها، التكرار).
3. نقطة أو نقطتين: شو لازم يعمل بكرا، أو "ما في شي، خلي الحملة تشتغل".
4. سطر أخير: تذكير إنه التحميلات الفعلية بتنعرف من عداد الموقع واستخدام كود الخصم.

إذا الحملة مو شغالة (مسودة، متوقفة، فيها خطأ دفع أو رفض)، قول هالشي أول شي بوضوح.
إذا تاريخ اليوم بعد {END_DATE}، اكتب تقرير ختامي للحملة كلها بدل اليومي.
لا تخترع أرقام. إذا رقم ناقص قول "ما في بيانات".

المعايير:
{BENCHMARKS}

تاريخ اليوم: {today}
الميزانية الكلية: {BUDGET_TOTAL} دولار على {CAMPAIGN_DAYS} يوم، بتخلص {END_DATE}.

البيانات من ميتا:
{json.dumps(data, ensure_ascii=False, indent=2)}
"""
    resp = http_post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": CLAUDE_MODEL,
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()


def plain_report(data):
    c = data["campaign"]
    lines = [f"📊 تقرير سراقب ديليفري - {datetime.now(timezone.utc):%Y-%m-%d}",
             f"الحالة: {c.get('effective_status')}"]
    for label, key in (("اليوم", "today"), ("من البداية", "since_start")):
        s = data.get(key)
        if not s:
            lines.append(f"{label}: ما في بيانات")
            continue
        lines.append(
            f"{label}: صرف {s['spend_usd']}$ · وصول {s['reach']} · نقرات {s['link_clicks']} · "
            f"CTR {s['link_ctr_pct']}% · مشاهدات صفحة {s['landing_page_views']} · تكرار {s['frequency']}"
        )
    return "\n".join(lines)


# ---------- تيليجرام ----------
def send_telegram(text, bot_token, chat_id):
    for i in range(0, len(text), 4000):  # حد تيليجرام 4096 حرف
        http_post_json(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            {"chat_id": chat_id, "text": text[i:i + 4000], "disable_web_page_preview": True},
        )


def main():
    meta_token = env("META_ACCESS_TOKEN")
    bot_token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    claude_key = env("ANTHROPIC_API_KEY", required=False)

    try:
        data = fetch_campaign(meta_token)
    except Exception as e:  # noqa: BLE001
        send_telegram(f"🔴 ما قدرت اسحب أرقام الحملة من ميتا اليوم.\nالسبب: {e}\n"
                      "غالباً مفتاح ميتا انتهى أو ما إله صلاحية ads_read على الحساب.",
                      bot_token, chat_id)
        raise

    report = None
    if claude_key:
        try:
            report = write_report_with_claude(data, claude_key)
        except Exception as e:  # noqa: BLE001
            print(f"Claude فشل، ببعت تقرير الأرقام بس: {e}", file=sys.stderr)
    send_telegram(report or plain_report(data), bot_token, chat_id)
    print("تم إرسال التقرير.")


if __name__ == "__main__":
    main()
