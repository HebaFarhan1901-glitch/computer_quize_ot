import os
import json
import logging
import threading
import time
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

# إعداد التسجيل (Logging)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# جلب البيانات الحساسة من متغيرات البيئة لمنع التسريب
PROPERTIES = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN", "8961543175:AAFyLgnCSpgbORd65ftUJm6oyq2yitKzncc"),
    "WEB_APP_URL": os.getenv("WEB_APP_URL", ""),
    "ADMIN_ID": os.getenv("ADMIN_ID", "602498802")
}

SCRIPT_CACHE = {}  # { key: (value, expire_timestamp) }
SCRIPT_LOCK = threading.Lock()

# دالة التعامل مع Cache مع حماية خيوط التنفيذ (Thread Safety)
def cache_get(key: str):
    with SCRIPT_LOCK:
        if key in SCRIPT_CACHE:
            val, expire_at = SCRIPT_CACHE[key]
            if time.time() < expire_at:
                return val
            else:
                del SCRIPT_CACHE[key]
        return None

def cache_put(key: str, value: str, ttl_seconds: int = 21600):
    with SCRIPT_LOCK:
        SCRIPT_CACHE[key] = (value, time.time() + ttl_seconds)

# الصفحة الرئيسية
@app.get("/", response_class=PlainTextResponse)
def do_get():
    return "Yasser Quiz Bot is running"

# استقبال رسائل Telegram (تم تحويلها لـ synchronous لتجنب مشاكل requests مع Async)
@app.post("/webhook", response_class=PlainTextResponse)
def do_post(request: Request):
    try:
        # قراءة محتوى الطلب بشكل متزامن
        try:
            import asyncio
            e_contents = asyncio.run(request.json())
        except Exception:
            return "OK"

        if not e_contents:
            return "OK"

        update = e_contents

        # تجاهل التحديثات التي لا تحتوي رسالة أو ضغطة زر
        if "message" not in update and "callback_query" not in update:
            return "OK"

        update_id = update.get("update_id")
        key = f"update_{update_id}"

        # منع معالجة التحديث نفسه أكثر من مرة باسناد الـ Lock داخل Cache مباشرة
        if cache_get(key):
            logger.info(f"Duplicate update ignored: {update_id}")
            return "OK"

        # تسجيل التحديث فوراً
        cache_put(key, "1", 21600)

        # معالجة الرسائل وضغطات الأزرار
        if "callback_query" in update:
            handle_callback_query(update["callback_query"])
        elif "message" in update:
            handle_message(update["message"])

        logger.info(f"Update processed: {update_id}")

    except Exception as err:
        logger.error(f"doPost ERROR: {err}", exc_info=True)

    return "OK"

# ربط البوت بعنوان Web App المحفوظ
def set_webhook():
    token = PROPERTIES.get("BOT_TOKEN")
    url = PROPERTIES.get("WEB_APP_URL")

    if not token or not url:
        raise Exception("تأكد من BOT_TOKEN و WEB_APP_URL في Script Properties")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data={"url": url}
    )

    result_text = response.text
    logger.info(f"setWebhook result: {result_text}")

    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Telegram setWebhook failed: {result_text}")

# إرسال رسالة وفحص نتيجة Telegram
def send(chat_id, text, reply_markup=None):
    token = PROPERTIES.get("BOT_TOKEN")

    payload = {
        "chat_id": chat_id,
        "text": str(text)
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload)
    )

    result = response.json()

    if not result.get("ok"):
        logger.error(f"sendMessage error: {response.text}")
        raise Exception("Telegram sendMessage failed")

    return result

# التحقق من المشرف
def is_admin(user_id):
    admin_ids = [
        x.strip() for x in str(PROPERTIES.get("ADMIN_ID", "")).split(",") if x.strip()
    ]
    return str(user_id).strip() in admin_ids

# إدارة حالة المستخدم
def get_state(user_id):
    raw_state = cache_get(f"STATE_{user_id}")
    return json.loads(raw_state) if raw_state else {}

def save_state(user_id, state):
    cache_put(f"STATE_{user_id}", json.dumps(state), ttl_seconds=86400)

def clear_state(user_id):
    with SCRIPT_LOCK:
        SCRIPT_CACHE.pop(f"STATE_{user_id}", None)

question_explanations = {
    "From which tab can WordArt be inserted in Microsoft Word?":
        "يُدرج WordArt من تبويب Insert، لأنه أداة لإضافة نصوص بتنسيقات وتأثيرات فنية.",

    "What is the protocol responsible for transferring files over the network?":
        "FTP اختصار File Transfer Protocol، وهو بروتوكول مخصص لنقل الملفات بين الأجهزة عبر الشبكة.",

    "How can passwords be better protected?":
        "المصادقة الثنائية 2FA تضيف خطوة تحقق ثانية إلى كلمة المرور، فتقلل احتمال الدخول غير المصرح به.",

    "From which tab can a page picture background be inserted in Microsoft Word?":
        "تبويب Design يضم أدوات تنسيق مظهر المستند، ومنها لون الصفحة وحدودها والعلامة المائية.",

    "Which tab allows you to run spelling and grammar check in Microsoft Word?":
        "تبويب Review يضم أدوات التدقيق الإملائي والنحوي ومراجعة المستند.",

    "What is meant by DDL in databases?":
        "DDL تعني Data Definition Language، وتُستخدم لتعريف بنية قاعدة البيانات، مثل إنشاء الجداول وتعديلها.",

    "What is meant by DCL in databases?":
        "DCL تعني Data Control Language، وتُستخدم لإدارة الصلاحيات والتحكم في الوصول إلى بيانات قاعدة البيانات.",

    "Where are the control buttons located in Microsoft Excel?":
        "أزرار تصغير النافذة وتكبيرها وإغلاقها توجد في شريط العنوان Title Bar.",

    "When forwarding all incoming emails to another person, which option should be used?":
        "خيار Forward يعيد توجيه الرسالة إلى مستلم آخر، بدلاً من الرد على مرسلها." ,
    "What is URL?":
      "URL هو عنوان المورد على الويب وقد يتضمن البروتوكول واسم المضيف والمسار إلى المورد" ,

    "What is a responsive website?":
    "الموقع المتجاوب يكيّف تصميمه وترتيب عناصره مع أحجام الشاشات المختلفة، مثل الهاتف والحاسوب.",

  "Internet is:":
    "الإنترنت شبكة عالمية تربط شبكات وأجهزة كثيرة لتبادل البيانات والخدمات.",

  "In case of accidentally deleting a file, where can it be restored in the operating system?":
    "سلة المحذوفات Recycle Bin تحتفظ عادةً بالملفات المحذوفة مؤقتاً، ومنها يمكن استعادتها إذا لم تُحذف نهائياً.",

  "How do I rotate text 45 degrees in Excel?":
    "توجد خيارات اتجاه النص في مجموعة Alignment ضمن تبويب Home، ومنها يمكن ضبط زاوية دوران النص.",

  "From which tab can you add a background in Microsoft Excel?":
    "في إصدارات Excel التقليدية، يوجد خيار خلفية ورقة العمل ضمن تبويب Page Layout.",

  "What does the ($) indicate in Microsoft Excel?":
    "رمز $ قد يُستخدم للدلالة على العملة في تنسيق الأرقام، كما يُستخدم في المراجع المطلقة مثل $A$1؛ ويعتمد المعنى على سياق السؤال.",

  "If a value in the table changes, does it affect the chart value in Microsoft Excel?":
    "إذا كان المخطط مرتبطاً ببيانات الجدول، فإن تغيير البيانات ينعكس عليه عادةً تلقائياً.",

  "The connection is made with _____ to build internet networks.":
    "يمكن استخدام الأقمار الصناعية وADSL وISDN لتوفير اتصالات بالشبكات، لذلك يشير مفتاح السؤال إلى All of above.",

  "What shortcut Ctrl + B?":
    "الاختصار Ctrl + B يفعّل التنسيق الغامق Bold للنص المحدد في Word.",

  "From which tab can a symbol be inserted in Word?":
    "تبويب Insert يضم أمر Symbol لإدراج الرموز الخاصة التي لا تتوفر مباشرةً على لوحة المفاتيح.",
    
  "First Cell in Excel?":
    "أول خلية في ورقة Excel هي A1؛ لأن الأعمدة تُسمّى بالحروف والصفوف بالأرقام.",

  "How can an important message be marked in email?":
    "يمكن تمييز الرسالة المهمة بإضافة نجمة Star، لتسهيل العثور عليها والرجوع إليها لاحقاً.",

  "What is meant by HTTPS?":
    "HTTPS هو الإصدار الآمن من HTTP، ويستخدم التشفير لحماية البيانات المتبادلة بين المتصفح والموقع.",

  "It is acceptable to let long text overflow into adjacent cells in a worksheet when ...":
    "يمكن أن يمتد النص الطويل إلى الخلايا المجاورة إذا كانت تلك الخلايا فارغة؛ أما إذا احتوت على بيانات فقد لا يظهر النص كاملاً.",

  "How do you auto-fit column width in Excel?":
    "يمكن ضبط عرض العمود تلقائياً بالنقر المزدوج على الحد الأيمن لعنوان العمود، فيتسع بحسب محتوياته.",

  "If you want to fill cells with months in sequence (January, February, ...), use:":
    "تُستخدم ميزة Series Fill لإنشاء تسلسل من الأشهر في الخلايا بدلاً من إدخال كل شهر يدوياً.",

  "From where can you insert a picture in Excel?":
    "يُدرج الصور في Excel من تبويب Insert، الذي يحتوي على أدوات إدراج الصور والعناصر الأخرى.",

  "You can change sheet orientation from portrait to landscape in Excel using:":
    "يمكن تغيير اتجاه ورقة العمل للطباعة من Portrait إلى Landscape عبر تبويب Page Layout.",

  "What shortcut saves in Excel?":
    "الاختصار Ctrl + S يُستخدم لحفظ المصنف الحالي في Excel.",

  "How do you fill cells with color in Excel?":
    "تُستخدم أداة Fill Color لتغيير لون خلفية الخلية، ويمكن الوصول إليها من أدوات التنسيق في Excel.",

  "Where is the file name written in Excel?":
    "يظهر اسم المصنف الحالي في شريط العنوان Title Bar أعلى نافذة Excel.",

  "What default name file Excel?":
    "الاسم الافتراضي للمصنف الجديد في Excel هو Book1، ما لم يُغيَّر الاسم أو يوجد مصنف آخر مفتوح.",

  "Which menu option can be used to split windows into two panes in Excel?":
    "يوجد أمر Split ضمن تبويب View في Excel، ويُستخدم لتقسيم نافذة ورقة العمل إلى أجزاء لتسهيل عرض مناطق مختلفة.",

  "MS-Word is:":
    "Microsoft Word هو برنامج تطبيقي Application يُستخدم لإنشاء المستندات النصية وتحريرها وتنسيقها.",

  "Which of the following is not related to editing a cell in Excel?":
    "وفقاً لمفتاح الإجابة المعتمد في السؤال، الاختيار هو Alt. لكن صياغة السؤال غير دقيقة؛ فـAlt وCtrl وShift مفاتيح مساعدة يمكن استخدامها ضمن اختصارات Excel، بينما F2 يُستخدم مباشرةً لتحرير الخلية.",

  "What happens when you press F12 in Excel?":
    "الضغط على F12 في Excel يفتح نافذة Save As، التي تتيح حفظ المصنف باسم أو في موقع أو بتنسيق مختلف.",

  "Where is the taskbar located on the Windows screen?":
    "يوجد شريط المهام Taskbar عادةً أسفل شاشة Windows في الإعداد الافتراضي، ويمكن تغيير موضعه بحسب إصدار النظام وإعداداته.",

  "Headers and footers can include text, graphics, and ...":
    "يمكن أن تحتوي الرؤوس والتذييلات على نصوص وصور وتاريخ ووقت وأرقام الصفحات، لذلك الإجابة هي All of above.",

  "In Excel, a pie chart is used to ...":
    "يُستخدم المخطط الدائري Pie Chart لتوضيح مساهمة كل قيمة في المجموع الكلي، وتُعرض القيم عادةً على شكل قطاعات من الدائرة.",

  "Can PowerPoint display data from any of the following Microsoft add-in programs?":
    "وفقاً لمفتاح الإجابة في السؤال، الإجابة All of these؛ أي جميع الخيارات المذكورة. تختلف طريقة إدراج هذه العناصر بحسب إصدار PowerPoint والأدوات المتاحة.",
    "Which of these options allows users to store and access files via the internet?":
    "Google Drive خدمة تخزين سحابي تتيح للمستخدم حفظ الملفات والوصول إليها عبر الإنترنت.",

  "The extension of a file saved in Excel is of type ...":
    "امتداد ملفات Excel الحديثة هو .xlsx، ويُستخدم لحفظ المصنفات التي تحتوي على أوراق العمل والبيانات.",

  "What does Document outline view represent?":
    "يعرض Document Outline بنية المستند وعناوينه بمستويات مختلفة، مما يسهل التنقل بين أقسامه.",

  "The small black square in the bottom-right corner of an active cell or range represents ...":
    "المربع الصغير في الزاوية السفلية اليمنى من الخلية المحددة يُسمّى Fill Handle، ويُستخدم لنسخ البيانات أو إكمال التسلسلات.",

  "What is a typical advantage of online learning?":
    "من مزايا التعلم عبر الإنترنت إمكانية الوصول إلى المحتوى التعليمي بسهولة وفي أوقات مختلفة، دون الحاجة إلى الحضور الدائم إلى الصف.",

  "A hyperlink is inserted from the tab:":
    "لإدراج رابط تشعبي Hyperlink في برامج Office، نستخدم تبويب Insert ثم خيار Hyperlink.",

  "Keyboard shortcut to open the Font dialog box in Word?":
    "الاختصار Ctrl + D يفتح مربع حوار Font في Microsoft Word، ويتيح تغيير إعدادات الخط.",

  "To insert a new column between column A and column B, click the button:":
    "لإضافة عمود بين A وB في Excel، نحدد العمود B ثم نختار Insert من مجموعة Cells؛ فيُضاف العمود الجديد قبل العمود المحدد.",

  "What menu provides options such as animation, custom animation, slide transition?":
    "وفقاً لمفتاح الإجابة المعتمد في السؤال، الاختيار هو Slide Show. قد تختلف مواقع خيارات الحركات والانتقالات باختلاف إصدار PowerPoint.",

  "How to remove cell borders?":
    "يمكن إزالة حدود الخلايا من نافذة Format Cells باختيار None، أو باستخدام قائمة Borders واختيار No Border؛ لذلك الإجابة Both.",

  "what do the letters C,D,E represent in operating system":
    "في Windows، تُستخدم الحروف مثل C وD وE عادةً لتمييز محركات الأقراص أو أقسامها، لذلك الإجابة Drives.",

  "Microsoft Word is ____ software":
    "Microsoft Word برنامج تطبيقي Application Software يُستخدم لإنشاء المستندات النصية وتحريرها وتنسيقها.",

  "Which of the following best describes Serifs?":
    "Serifs هي الزوائد أو الخطوط الصغيرة التي تظهر عند أطراف الحروف في بعض أنواع الخطوط.",

  "What is HTML?":
    "HTML اختصار HyperText Markup Language، وهي لغة ترميز تُستخدم لبناء هيكل صفحات الويب.",

  "In PowerPoint presentation...":
    "يمكن إدراج المقاطع الصوتية والمرئية معاً في عروض PowerPoint؛ لذلك الإجابة Both can be inserted.",

  "When a range is selected, how can you activate the previous cell?":
    "بحسب مفتاح الإجابة المعتمد في السؤال، الاختيار هو None of above. لكن صياغة السؤال غير واضحة؛ ففي Excel يمكن الانتقال إلى الخلية السابقة ضمن النطاق باستخدام Shift + Tab.",

  "Which of the following is considered secondary storage?":
    "القرص الصلب HDD يُعد من وحدات التخزين الثانوية، لأنه يحتفظ بالبيانات حتى بعد إيقاف تشغيل الحاسوب.",

  "To add a comment in Word 2016, you should":
    "يمكن إضافة تعليق في Word 2016 من تبويب Review ثم New Comment، أو بتحديد النص والنقر بزر الفأرة الأيمن واختيار New Comment؛ لذلك الإجابة Both B and C.",

  "To insert an image click the button":
    "وفقاً لمفتاح الإجابة، الاختيار هو Image from a list of illustrations. يعتمد تحديد الزر المقصود بدقة على صورة السؤال أو واجهة البرنامج المعروضة.",

  "In Microsoft Excel, pie chart is used for":
    "يُستخدم المخطط الدائري Pie Chart لإظهار مساهمة كل قيمة كنسبة من المجموع الكلي.",
    "To insert a new column between Column A and Column B, press the button:":
    "لإدراج عمود جديد بين A وB في Excel، نحدد العمود B ثم نستخدم Insert من مجموعة Cells لإضافة عمود قبله.",

  "Which of the following statement is false?":
    "وفقاً لمفتاح الإجابة، العبارة غير الصحيحة هي أن عناصر التخطيطات الجاهزة لا يمكن حذفها؛ إذ يمكن عادةً تعديل العناصر أو حذفها بحسب نوع التخطيط.",

  "To start Microsoft PowerPoint application":
    "وفقاً لمفتاح الإجابة، الخيار A يوضح فتح PowerPoint من قائمة Start ثم Programs أو All Programs، بحسب إصدار Windows.",

  "To close the current workbook in use, click on the option....... in the....... menu.":
    "وفقاً لمفتاح الإجابة، الاختيار هو Close من قائمة Office، وهي واجهة الإصدارات القديمة من برامج Microsoft Office.",

  "What is an Internet search engine?":
    "محرك البحث هو برنامج أو خدمة تبحث في الإنترنت عن صفحات ومعلومات محددة، مثل الكلمات والصور ومقاطع الفيديو.",

  "Which of the following technologies provides the greatest benefit to a blind computer user?":
    "مفتاح الإجابة يحدد الخيار B، لكن صياغة هذا الخيار غير واضحة ولا تصف تقنية معروفة بدقة. من التقنيات المفيدة للمكفوفين قارئات الشاشة التي تحول النص إلى صوت.",

  "Ctrl + D shortcut key in Excel will:":
    "في Excel، الاختصار Ctrl + D ينفذ Fill Down، أي ينسخ محتوى الخلية العلوية إلى الخلايا المحددة أسفلها.",

  "Any website can be accessed easily via:":
    "يساعد محرك البحث Search Engine على العثور على المواقع وصفحات الويب من خلال كتابة الكلمات المفتاحية المناسبة.",

  "If the setting locks the taskbar is on, then _______":
    "عند تفعيل Lock the taskbar في Windows، يُمنع تغيير موضع شريط المهام أو تغيير حجمه بالطريقة المعتادة.",

  "What happens when you press Ctrl + X after selecting some cells in Excel?":
    "الاختصار Ctrl + X يحدد الخلايا للقص Cut، ثم يمكن نقل محتوياتها إلى موقع آخر باستخدام Paste.",

  "File extensions are used in order to":
    "امتداد الملف يساعد على تحديد نوع الملف، مثل .docx لمستند Word و.xlsx لمصنف Excel و.pdf لملف PDF.",

  "What is the short form of CPU?":
    "CPU اختصار Central Processing Unit، أي وحدة المعالجة المركزية التي تنفذ التعليمات وتعالج البيانات.",

  "What's the best way to design the layout for your slides?":
    "وفقاً لمفتاح الإجابة، الخيار A يشير إلى استخدام Slide Master لتصميم تخطيطات الشرائح والنشرات والملاحظات بصورة موحدة.",

  "To insert the logo graphic, click the button":
    "وفقاً لمفتاح الإجابة، الاختيار هو All answers given are incorrect؛ لأن الخيارات المذكورة لا تحدد الزر المقصود لإدراج الشعار بدقة.",

  "Which of the following are physical devices of a computer?":
    "Hardware تعني المكونات المادية للحاسوب التي يمكن لمسها، مثل الشاشة ولوحة المفاتيح والطابعة.",

  "All mathematical operations in Excel 2019 must begin with?":
    "تبدأ الصيغة الحسابية في Excel بعلامة المساواة =، مثل =A1+B1، حتى يتعامل البرنامج معها بوصفها صيغة.",

  "Which of the following is an input device?":
    "لوحة المفاتيح Keyboard جهاز إدخال لأنها تسمح للمستخدم بإدخال النصوص والأرقام والأوامر إلى الحاسوب.",

  "Using the Internet to download the latest version of a program is an example of":
    "يُسمى تنزيل أحدث إصدار من البرنامج Software Updating، أي تحديث البرنامج لتحسينه أو إصلاح مشكلاته.",

  "Which of the following is considered an operating system?":
    "Windows 10 نظام تشغيل يدير موارد الحاسوب ويتيح تشغيل البرامج والتعامل مع الملفات والأجهزة.",

  "To insert a new sheet, click the button":
    "في Excel، يمكن إضافة ورقة عمل جديدة من Home ثم Insert ثم Insert Sheet، أو باستخدام علامة + بجانب ألسنة الأوراق.",
    "Which storage device uses magnetic technology?":
    "يستخدم القرص الصلب HDD تقنية التخزين المغناطيسي لحفظ البيانات، بخلاف SSD الذي يعتمد على ذاكرة الفلاش.",

  "Which of the following is not a computer virus?":
    "وفقاً لمفتاح الإجابة، الاختيار هو Linux؛ لكنه نظام تشغيل وليس فيروساً. أما Trojans وWorms وRansomware فهي أنواع مختلفة من البرمجيات الخبيثة.",

  "Which protocol is commonly used to secure data transmission over the internet?":
    "وفقاً لمفتاح الإجابة المعتمد، الخيار A هو HTTP، لكن الإجابة التقنية الصحيحة هي HTTPS لأنه يستخدم التشفير لحماية البيانات أثناء انتقالها.",

  "In Excel 2019, which function is used to calculate the average of a range of cells?":
    "تُستخدم الدالة AVERAGE لحساب المعدل الحسابي للقيم الموجودة في نطاق من الخلايا، مثل =AVERAGE(A1:A10).",

  "Auto clipart is a feature that":
    "وفقاً لمفتاح الإجابة، الخيار C هو أن الميزة تضع Clip Art تلقائياً في العرض التقديمي. قد تختلف هذه الميزة أو تسميتها بحسب إصدار Office.",

  "How can you change page orientation?":
    "يمكن تغيير اتجاه الصفحة إلى عمودي Portrait أو أفقي Landscape من تبويب Layout ثم Orientation في إصدارات Word الحديثة.",

  "In order to edit a chart, you can _______":
    "يُستخدم النقر المزدوج على المخطط عادةً للدخول إلى وضع تحريره أو التعامل مع عناصره، لذلك الإجابة Double click the chart object.",

  "Header and footer option allows us to insert __________":
    "يمكن للرأس والتذييل أن يتضمنا رقم الصفحة والتاريخ والوقت، لذلك الإجابة All of the above.",

  "The ...... works with the standard Copy and Paste commands.":
    "تعمل حافظة Office Clipboard مع أوامر Copy وPaste، وتساعد على الاحتفاظ بالعناصر المنسوخة أو المقصوصة لاستخدامها لاحقاً.",

  "In the following paragraph, the table...":
    "وفقاً لمفتاح الإجابة، الخيار A يعني أن أطوال الفئات تتغير تلقائياً لاستيعاب القيمة الجديدة. يعتمد التفسير الدقيق على الجدول أو الشكل المشار إليه في السؤال.",

  "If you receive a message from a friend sent to a number of people and you want to respond to everyone, do you use the command...":
    "إذا أردت الرد على المرسل وجميع المستلمين، تستخدم Reply to All، وليس Reply الذي يرسل الرد إلى المرسل فقط.",

  "In MS Excel, formulas must always begin with a:":
    "تبدأ الصيغ في Excel بعلامة المساواة =، مثل =A1+B1، حتى يتعرف البرنامج عليها بوصفها صيغة.",

  "To insert specific text on each page, click the... button.":
    "لإضافة نص يتكرر في صفحات المستند، مثل عنوان ثابت أو اسم المؤسسة، نستخدم Header أو Footer من تبويب Insert.",

  "What is Email short for?":
    "Email اختصار Electronic Mail، أي البريد الإلكتروني الذي يُستخدم لإرسال الرسائل واستقبالها عبر الشبكات.",

  "How to convert the number listed in a divided cell into a group of ranks in Microsoft Excel?":
    "وفقاً لمفتاح الإجابة، الخيار B يشير إلى رمز الفاصلة Comma Style في Excel، الذي يُستخدم لتنسيق الأرقام. صياغة السؤال غير واضحة بشأن المقصود بـ ranks.",

  "In Microsoft PowerPoint, which view is best used to reorder and organize slides?":
    "يُستخدم Slide Sorter View لعرض الشرائح على شكل صور مصغرة، مما يسهل إعادة ترتيبها وتنظيمها.",

  "How to change the width of column (B) to width (30) in a Microsoft Excel 2019 workbook?":
    "نحدد العمود B، ثم نختار Home > Format > Column Width، وندخل القيمة 30 لتحديد عرض العمود.",

  "How can I insert a new column between column A and B in a worksheet in Microsoft Excel 2019?":
    "لإضافة عمود بين A وB، نحدد العمود B ثم نختار Home > Insert > Insert Sheet Columns، فيُدرج العمود الجديد قبله.",

  "While Finding and Replacing some data in Excel, which of the following statement is valid?":
    "يمكن استخدام Find and Replace للبحث والاستبدال ضمن ورقة العمل أو المصنف، لذلك الإجابة You can Find and Replace within the sheet or workbook.",

  "Which tab is used to insert a table in Word 2016?":
    "لإدراج جدول في Word 2016، نذهب إلى تبويب Insert ثم نختار Table ونحدد عدد الصفوف والأعمدة.",
    "Animation schemes can be applied to .......... in the presentation":
    "وفقاً لمفتاح الإجابة، يمكن تطبيق مخططات الحركة على جميع الشرائح أو الشرائح المحددة أو الشريحة الحالية، لذلك الإجابة All of the above.",

  "What is the definition of browser?":
    "المتصفح Browser هو برنامج يُستخدم لعرض صفحات الويب والتنقل بينها على الإنترنت، مثل Google Chrome وMicrosoft Edge.",

  "Which of the following is an example of an application software?":
    "Microsoft Word برنامج تطبيقي Application Software يُستخدم لإنشاء المستندات وتحرير النصوص، بخلاف Windows وLinux اللذين يُعدّان نظامَي تشغيل.",

  "A presentation program developed by Microsoft is...":
    "PowerPoint هو برنامج من Microsoft مخصص لإنشاء العروض التقديمية وتنظيم الشرائح وإضافة النصوص والصور والحركات.",

  "Which of the following devices can transfer data from one person to another via a telephone line without using a computer?":
    "وفقاً لمفتاح الإجابة، الخيار C هو Fax؛ إذ يمكن لجهاز الفاكس إرسال المستندات عبر خط الهاتف إلى جهاز فاكس آخر.",

  "Which of the following tools enable you to add text to a slide without using the standard placeholders?":
    "تتيح أداة Text Box إضافة نص إلى الشريحة في أي موضع مناسب، دون الحاجة إلى استخدام العناصر النائبة الجاهزة Placeholders.",

  "primary purpose of protecting data online is...":
    "الهدف الأساسي من حماية البيانات على الإنترنت هو الحفاظ على خصوصية البيانات الشخصية ومنع الوصول إليها أو استخدامها دون إذن.",

  "Which network device is used to connect different networks together?":
    "جهاز Router أو الموجّه يربط بين شبكات مختلفة ويوجّه حزم البيانات إلى الشبكة أو الوجهة المناسبة.",

  "The default name for files created in Excel 2019 is...":
    "وفقاً لمفتاح الإجابة، الخيار A هو Book. في Excel يكون الاسم الافتراضي للمصنف الجديد عادةً Book1، ثم يزداد الرقم عند إنشاء مصنفات إضافية.",

  "What is RAM?":
    "RAM اختصار Random Access Memory، أي ذاكرة الوصول العشوائي، وهي ذاكرة مؤقتة تحتفظ بالبيانات التي يحتاج إليها الحاسوب أثناء التشغيل.",

  "If a website is not loading correctly, which action might help resolve the issue?":
    "يمكن تحديث الصفحة Refresh أو مسح ذاكرة التخزين المؤقت للمتصفح Browser Cache لمعالجة بعض مشكلات تحميل المواقع.",

  "The Show group of the View tab is used to show ............":
    "تضم مجموعة Show في تبويب View خيارات مثل Ruler وGridlines وNavigation Pane، لذلك الإجابة All of the above.",

  "To delete a new row between column A and column B, press the button":
    "وفقاً لمفتاح الإجابة، الخيار D هو All the answers given are incorrect. صياغة السؤال غير دقيقة؛ لأن حذف عمود يختلف عن حذف صف، ويجب تحديد المطلوب بدقة.",

  "Which of the following items you must have to send an email?":
    "لإرسال بريد إلكتروني إلى شخص آخر، تحتاج إلى عنوان البريد الإلكتروني للمستلم حتى تصل الرسالة إلى الوجهة الصحيحة.",

  "Which component coordinates all computer activities?":
    "تُعد وحدة المعالجة المركزية CPU المكوّن الذي ينفذ التعليمات وينسق كثيراً من عمليات معالجة البيانات داخل الحاسوب.",

  "To insert a new row between row 10 and row 11, click the button ..........":
    "وفقاً لمفتاح الإجابة، الخيار D هو All answers given are incorrect. في Excel يمكن إدراج صف بين الصفين 10 و11 بتحديد الصف 11 ثم اختيار Insert.",

  "A file which contains readymade styles that can be used for presentations is called":
    "Template هو قالب جاهز يحتوي على تصميمات وتنسيقات يمكن استخدامها لإنشاء عرض تقديمي بسرعة وبمظهر موحّد.",

  "It is a device that controls the transmission of data to its destination on a computer network.":
    "Router هو جهاز يوجّه البيانات بين الشبكات ويختار المسار المناسب لوصولها إلى وجهتها.",

  "What is the default file extension for Microsoft Word 2016 documents?":
    "الامتداد الافتراضي لمستندات Word 2016 هو .docx، وهو تنسيق مستندات Word الحديثة.",

  "Which key on the keyboard is used to cancel an action or close a dialog box?":
    "يُستخدم مفتاح Esc عادةً لإلغاء إجراء جارٍ أو إغلاق بعض مربعات الحوار دون تأكيد التغييرات.",

  "What is the purpose of the firewall in a computer network?":
    "يعمل Firewall على مراقبة حركة مرور الشبكة والتحكم بها وفق قواعد أمنية، بهدف حظر الاتصالات أو محاولات الوصول غير المصرح بها.",

  "Which of the following is firmware?":
    "BIOS مثال على Firmware، وهو برنامج منخفض المستوى يساعد على تهيئة مكونات الحاسوب وبدء عملية الإقلاع.",

  "_______ writes the name of the current cell in use in Excel":
    "يعرض Name Box عنوان الخلية المحددة حالياً، مثل A1، ويمكن استخدامه أيضاً للانتقال مباشرةً إلى خلية أو نطاق معين.",

  "What is the purpose of the archive feature in email?":
    "تُستخدم ميزة Archive لنقل الرسائل القديمة من صندوق الوارد إلى الأرشيف مع الاحتفاظ بها دون حذفها.",

  "What does WAN stand for?":
    "WAN اختصار Wide Area Network، أي شبكة واسعة النطاق تربط أجهزة أو شبكات عبر مسافات جغرافية كبيرة.",

  "The intersection of a row and column is called a:":
    "تُسمّى نقطة تقاطع الصف والعمود في Excel خلية Cell، ويُحدد موقعها بحرف العمود ورقم الصف، مثل B3.",

  "If you have a PowerPoint show you created and want to send using email to another teacher you can add the show to your email message as a (an) __________":
    "يُرسل ملف العرض التقديمي عبر البريد الإلكتروني عادةً بوصفه Attachment، أي مرفقاً مع الرسالة.",

  "What is an online account?":
    "الحساب الإلكتروني Online Account هو حساب شخصي يتيح للمستخدم الوصول إلى خدمة عبر الإنترنت باستخدام بيانات تسجيل الدخول.",

  "The taskbar is located __________":
    "يوجد شريط المهام Taskbar عادةً في أسفل شاشة Windows وفق الإعداد الافتراضي، مع إمكانية تغيير موضعه في بعض الإصدارات.",

  "In Microsoft Excel, to fill a cell with a specific color or pattern, do the following":
    "وفقاً لمفتاح الإجابة، نفتح Format Cells ثم تبويب Fill لاختيار لون تعبئة الخلية أو نمطها.",

  "What is the meaning of cell A15?":
    "العنوان A15 يعني أن الخلية تقع عند تقاطع العمود A مع الصف 15؛ فالحروف تحدد الأعمدة والأرقام تحدد الصفوف.",

  "Which of the following is the default page setup orientation for slides in PowerPoint?":
    "الاتجاه الافتراضي الشائع لشرائح PowerPoint هو Landscape، أي الاتجاه الأفقي، الذي يجعل عرض الشريحة أكبر من ارتفاعها.",

  "What does LAN stand for?":
    "LAN اختصار Local Area Network، أي شبكة محلية تربط الأجهزة ضمن مساحة محدودة مثل منزل أو مكتب أو مختبر.",

  "In Excel 2019, to make text appear on multiple lines within a single cell, you should use...":
    "تُستخدم أداة Wrap Text لجعل النص يظهر على عدة أسطر داخل الخلية نفسها، مع تعديل ارتفاع الصف عند الحاجة.",

  "What does 'exe' file extension stand for":
    "الامتداد .exe اختصار Executable، ويشير في Windows عادةً إلى ملف قابل للتنفيذ يمكنه تشغيل برنامج.",

  "To change the page orientation in Microsoft Word":
    "لتغيير اتجاه الصفحة في Word، نذهب إلى تبويب Layout ثم Orientation ونختار Portrait أو Landscape.",

  "Which of the following is an example of an Operating System?":
    "Windows 10 نظام تشغيل يدير موارد الحاسوب ويتيح تشغيل البرامج والتعامل مع الملفات والأجهزة.",

  "What does WWW stand for?":
    "WWW اختصار World Wide Web، أي الويب العالمي الذي يتكون من صفحات وموارد مترابطة يمكن الوصول إليها عبر الإنترنت.",

  "the unit that is a responsible for receiving data and messages from other devices within networks or another networks connected in the same network is":
    "وفقاً لمفتاح الإجابة، الخيار B هو Receiving Unit، أي وحدة الاستقبال التي تتلقى البيانات أو الرسائل من الأجهزة الأخرى.",

  "Left click in a suitable place in the desktop can be used to delete a file, folder or shortcut.":
    "الإجابة المعتمدة هي False؛ فالنقر الأيسر على مساحة فارغة من سطح المكتب لا يحذف الملفات أو المجلدات. يتطلب الحذف تحديد العنصر ثم تنفيذ أمر Delete أو استخدام قائمة النقر بالزر الأيمن.",

  "File type at bmp":
    "BMP اختصار Bitmap، وهو تنسيق لملفات الصور يخزن الصورة على هيئة بيانات نقطية.",

  "Before you can perform any action on a file or folder, what must you do?":
    "قبل تنفيذ إجراء على ملف أو مجلد، يجب تحديده أولاً حتى يعرف نظام التشغيل العنصر المطلوب التعامل معه.",

  "To clear the cell contents, follow these steps":
    "وفقاً لمفتاح الإجابة، يتم الوصول إلى أمر Clear من تبويب Home في Excel، ثم اختيار نوع المحتوى المراد مسحه.",

  "To insert a page break in Microsoft Word, you can press:":
    "الاختصار Ctrl + Enter يُدرج فاصل صفحة Page Break في Word، فيبدأ النص التالي من صفحة جديدة.",
 "To insert a text box click the button...":
    "وفقاً لمفتاح الإجابة، نستخدم أمر Text Box الموجود ضمن مجموعة Text لإدراج مربع نص في المستند أو الشريحة بحسب البرنامج.",

  "Which command will you choose to convert a column of data into row?":
    "يحوّل الأمر Paste Special > Transpose البيانات من ترتيب عمودي إلى أفقي أو بالعكس، مع تبديل الصفوف بالأعمدة.",

  "What was the first type of computer that allowed many users to access information... match a large geographic area?":
    "وفقاً لمفتاح الإجابة، الخيار C يشير إلى الحاسوب المركزي Mainframe، الذي يدعم معالجة كميات كبيرة من البيانات وخدمة عدد كبير من المستخدمين.",

  "In Microsoft Excel, what is the formula to calculate the total sum of a range of cells?":
    "تُستخدم الدالة SUM لجمع القيم في نطاق من الخلايا، مثل =SUM(A1:A10)، التي تجمع محتويات الخلايا من A1 إلى A10.",

  "What is the main purpose of using the Excel 2016 application?":
    "وفقاً لمفتاح الإجابة، الغرض الأساسي هو إجراء الحسابات والتحليلات الإحصائية؛ إذ يوفر Excel صيغاً ودوالاً وأدوات لتنظيم البيانات وتحليلها.",

  "Which of the following is a non-volatile memory?":
    "ROM ذاكرة غير متطايرة Non-volatile Memory؛ فهي تحتفظ بمحتوياتها حتى بعد إيقاف تشغيل الحاسوب، بخلاف RAM التي تفقد بياناتها المؤقتة عند انقطاع الطاقة.",
    "To format the number listed in a cell to be shown with two decimal places in Microsoft Excel 2019?":
    "لتنسيق رقم ليظهر بمنزلتين عشريتين في Excel، نستخدم أدوات Number ضمن تبويب Home ونختار زيادة المنازل العشرية Increase Decimal حتى يظهر الرقم بمنزلتين.",

  "What is used to verify people's identity and accounts on the network?":
    "وفقاً لمفتاح الإجابة، الخيار A هو User name؛ إذ يُستخدم اسم المستخدم للتعريف بالحساب، لكنه وحده لا يكفي للتحقق الآمن من الهوية.",

  "Which folder contains installed applications by default?":
    "يُستخدم مجلد Program Files في Windows عادةً لتثبيت ملفات البرامج والتطبيقات.",

  "In Microsoft Word, which view displays the document as it would appear on a printed page?":
    "يعرض Print Layout المستند بطريقة قريبة من شكله عند الطباعة، بما في ذلك الصفحات والهوامش وتوزيع المحتوى.",

  "What is the shortcut key to undo the last action in Windows?":
    "الاختصار Ctrl + Z يُستخدم للتراجع عن آخر إجراء في كثير من برامج Windows، ومنها Word وExcel.",

  "What does spam refer to in email?":
    "Spam هو البريد الإلكتروني غير المرغوب فيه، وقد يتضمن إعلانات مزعجة أو رسائل احتيالية أو روابط ضارة.",

  "how can you print only selected pages of a document?":
    "من File ثم Print، نحدد أرقام الصفحات أو نطاق الصفحات المطلوب طباعته بدلاً من طباعة المستند كاملاً.",

  "How do you apply a text highlight color in Word 2016?":
    "نحدد النص، ثم نذهب إلى Home ونختار Text Highlight Color من مجموعة Font لتظليل النص باللون المطلوب.",

  "What is the encryption?":
    "التشفير Encryption هو تحويل البيانات إلى صيغة غير مفهومة لغير المصرح لهم، ثم يمكن فك تشفيرها باستخدام الطريقة أو المفتاح المناسب.",

  "Which of the following is considered the \"brain\" of the computer?":
    "تُسمّى وحدة المعالجة المركزية CPU دماغ الحاسوب لأنها تنفذ التعليمات وتعالج البيانات وتنسق عمليات الحاسوب.",

  "How to hide 4th row from being visible?":
    "في Excel، لإخفاء الصف الرابع نحدد الصف 4، ثم نختار Home > Format > Hide & Unhide > Hide Rows.",

  "What is the difference between the Inbox and the Spam folder?":
    "يحتوي Inbox على الرسائل الواردة بصورة اعتيادية، بينما يجمع Spam الرسائل غير المرغوب فيها أو التي يُشتبه بأنها مزعجة أو ضارة.",

  "The Show group of the View tab is used to show...":
    "تحتوي مجموعة Show في تبويب View على خيارات عرض مثل Ruler وGridlines وNavigation Pane، بحسب البرنامج وإصدار Office.",

  "Which shortcut is used to copy selected text?":
    "الاختصار Ctrl + C ينسخ النص أو العنصر المحدد إلى الحافظة Clipboard، ليتم لصقه لاحقاً باستخدام Ctrl + V.",

  "To delete a table in MS Word, we select the entire table and then press the key _________":
    "وفقاً لمفتاح الإجابة، الخيار D هو Backspace. لكن حذف الجدول كاملاً في إصدارات Word الحديثة يتم بصورة أوضح من Table Layout > Delete > Delete Table.",

  "How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?":
    "نحدد الخلايا الثلاث، ثم نختار Home > Merge & Center لدمجها في خلية واحدة. انتبه إلى أن Excel يحتفظ عادةً بمحتوى الخلية العلوية اليسرى فقط.",

  "Which of the following is a type of cyber security threat?":
    "Phishing هو هجوم إلكتروني يحاول خداع المستخدم للحصول على كلمات المرور أو المعلومات الحساسة من خلال رسائل أو مواقع مزيفة.",

  "Which of the following can be used for quick access to common commands and tools?":
    "وفقاً لمفتاح الإجابة، الخيار B هو Toolbar؛ وهو شريط أدوات يتيح الوصول السريع إلى مجموعة من الأوامر الشائعة.",

  "GB means:":
    "GB اختصار Gigabyte، وهي وحدة لقياس سعة البيانات والتخزين. أما Gb بحرف b صغير فتعني Gigabit.",

  "When working on a cloud-based document, such as Google Docs, which feature allows multiple users to edit the document in real time?":
    "Real-time collaboration تعني تعاون عدة مستخدمين على المستند نفسه في الوقت الفعلي، بحيث تظهر تعديلاتهم أثناء العمل.",

  "How can you change the line spacing in Word 2016?":
    "يمكن تغيير تباعد الأسطر من تبويب Home، ضمن مجموعة Paragraph، باختيار Line and Paragraph Spacing.",

  "To make the text in the cell fit the cell border, we click the button:":
    "وفقاً لمفتاح الإجابة، الخيار A هو Format > AutoFit Column Width. هذه الأداة تضبط عرض العمود ليتناسب مع محتوياته؛ أما Wrap Text فيجعل النص يظهر على عدة أسطر داخل الخلية.",

  "The speed of a computer processor (CPU) is typically measured in...":
    "تُقاس سرعة تردد المعالج عادةً بوحدة Gigahertz (GHz)، وهي تعادل مليار دورة في الثانية.",

  "Where can a virus enter the computer from?":
    "يمكن أن تصل البرمجيات الخبيثة إلى الحاسوب عبر تنزيل ملفات من الإنترنت أو فتح مرفقات وروابط غير موثوقة.",

  "Files are temporarily stored without repetition in:":
    "وفقاً لمفتاح الإجابة، الخيار C هو Cache؛ وهي ذاكرة أو مساحة تخزين مؤقتة تساعد على تسريع الوصول إلى البيانات المتكررة الاستخدام.",

  "What is the PNG format?":
    "PNG اختصار Portable Network Graphics، وهو تنسيق صور يدعم الشفافية ويستخدم ضغطاً لا يفقد بيانات الصورة.",

  "How many columns are in Microsoft Excel?":
    "يحتوي Excel الحديث على 16,384 عموداً في ورقة العمل، تبدأ من A وتنتهي عند XFD.",

  "(2, 4, 7, 8) min":
    "الدالة MIN تُرجع أصغر قيمة ضمن مجموعة الأرقام. في المجموعة 2 و4 و7 و8 تكون النتيجة 2.",

  "Which function is used to calculate the middle value (median) for a set of numbers in Excel?":
    "تُستخدم الدالة MEDIAN لحساب الوسيط، أي القيمة التي تقع في المنتصف بعد ترتيب الأرقام، أو متوسط القيمتين الوسطيتين إذا كان عددها زوجياً.",

  "Where does the name of the selected cell appear in Excel?":
    "يظهر عنوان الخلية المحددة في Name Box، الموجود عادةً إلى يسار شريط الصيغة Formula Bar.",

  "The intersection of a column and a row represents ......":
    "تُسمّى نقطة تقاطع العمود والصف Cell، ويُكتب عنوانها باستخدام حرف العمود ورقم الصف، مثل C5.",

  "You can set page borders in Excel from:":
    "وفقاً لمفتاح الإجابة الموجود في الملف، الخيار D هو You cannot set page borders in Excel. المقصود غالباً حدود صفحة الطباعة؛ إذ لا يوفر Excel ميزة حدود الصفحة نفسها بالطريقة الموجودة في Word، لكن يمكن إضافة حدود للخلايا.",

  "When you need to display all numbers between 0 and 100 in a red font range, what should you do?":
    "تتيح ميزة Conditional Formatting تطبيق تنسيق تلقائي على الخلايا التي تحقق شرطاً معيناً، مثل جعل الأرقام الواقعة بين 0 و100 باللون الأحمر.",

  "The keyboard shortcut Ctrl + D in Excel will:":
    "الاختصار Ctrl + D ينفذ Fill Down، أي ينسخ محتوى الخلية العلوية إلى الخلايا المحددة أسفلها.",

  "The Delete key on the keyboard is assigned to which command in Excel?":
    "يُستخدم مفتاح Delete لمسح محتويات الخلايا المحددة عادةً، دون حذف الصف أو العمود نفسه.",

  "If the numbers are 18, 6, and 3 in Excel, what is the value of MAX?":
    "تُرجع الدالة MAX أكبر قيمة من مجموعة الأرقام. في المجموعة 18 و6 و3 تكون النتيجة 18.",

  "How are months repeated in Excel?":
    "يمكن استخدام AutoFill لسحب مقبض التعبئة وإكمال تسلسل الأشهر تلقائياً، مثل January ثم February ثم March.",

  "From which tab can you change the sheet orientation from portrait to landscape in Excel?":
    "يمكن تغيير اتجاه ورقة العمل للطباعة من تبويب Page Layout ثم Orientation واختيار Landscape.",

  "In Excel, the column header consists of:":
    "تُعرّف أعمدة Excel بالحروف الإنجليزية، مثل A وB وC، بينما تُعرّف الصفوف بالأرقام.",

  "Which value is not valid by the Fill Series box in Excel?":
    "وفقاً لمفتاح الإجابة، الخيار C هو Time. لكن نافذة Fill Series في Excel تتضمن أنواعاً مثل Linear وGrowth وDate وAutoFill؛ لذا قد تكون صياغة السؤال أو خياراته غير دقيقة.",

  "Delete the 10 row in Excel:":
    "يمكن حذف الصف العاشر بتحديد رقم الصف 10 ثم النقر بزر الفأرة الأيمن واختيار Delete، أو من Home > Delete > Delete Sheet Rows.",

  "Which menu option can be used to split windows into two parts?":
    "يحتوي تبويب View في Excel على أمر Split لتقسيم نافذة ورقة العمل إلى أجزاء تساعد على عرض مناطق مختلفة في الوقت نفسه.",

  "Which of the following options allows showing or hiding elements in Excel?":
    "وفقاً لمفتاح الإجابة الموجود في الملف، الخيار C هو Format. في Excel يمكن إظهار الصفوف أو الأعمدة وإخفاؤها من Home > Format، ضمن خيارات Visibility.",

  "To activate the previous cell in a prespecified range, press:":
    "وفقاً لمفتاح الإجابة، الاختيار هو None of above. عند التنقل بين خلايا النطاق باستخدام Tab، يمكن الرجوع إلى الخلية السابقة باستخدام Shift + Tab.",

  "What is the default font type in Word?":
    "وفقاً لمفتاح الإجابة في الملف، الخيار C هو Calibri. لكن الخط الافتراضي يختلف بحسب إصدار Word والقالب المستخدم؛ ففي الإصدارات الحديثة قد يكون Aptos.",

  "What is the best option for creating a resume?":
    "Microsoft Word هو الخيار الأنسب عادةً لإنشاء السيرة الذاتية وتنسيق النصوص والعناوين والخبرات والمؤهلات.",

  "The ruler in Word is located in the tab:":
    "يمكن إظهار المسطرة Ruler من تبويب View في Word، عبر تفعيل خيار Ruler.",

  "How can you delete text before the insertion point and to the left in Word?":
    "يمسح مفتاح Backspace الحروف الموجودة إلى يسار موضع المؤشر، بينما يمسح Delete الحروف الموجودة إلى يمينه.",

  "How can you quickly zoom in on the Word screen?":
    "يمكن تكبير عرض المستند من شريط التكبير Zoom Slider أسفل نافذة Word، أو من خيارات Zoom ضمن تبويب View.",
  "What is the number of automatic backup copies PowerPoint saves when presentations are disabled/closed?": "حسب الإجابة المحددة في الأسئلة، العدد هو نسخة واحدة.",
  "How can you make the slide show automatic in PowerPoint?": "يمكن جعل عرض الشرائح تلقائياً باستخدام المؤقت (Timer) لتحديد توقيت الانتقال بين الشرائح.",
  "Which of the following is NOT a method to create a presentation?": "الخيار Slide scan ليس طريقة معتمدة لإنشاء عرض تقديمي ضمن الخيارات المذكورة.",
  "What is the extension for government websites?": "الامتداد .gov يُستخدم عادةً للمواقع الحكومية.",
  "What is the document that people see when browsing?": "صفحة الويب (Web Page) هي المستند الذي يظهر للمستخدم عند تصفح الإنترنت.",
  "What are the features of e-commerce?": "من مميزات التجارة الإلكترونية إمكانية عرض السلع وأسعارها والشراء عن بُعد، وتوفر الخدمات على مدار الساعة.",
  "What is the site/service that saves documents and files online?": "Google Drive خدمة تخزين سحابي تتيح حفظ الملفات والمستندات عبر الإنترنت.",
"What does .com domain represent?": "الامتداد .com يشير عادةً إلى المواقع التجارية (Commercial).",
"Which of the following options is used to save documents and files over the internet?": "يمكن استخدام Google Drive لحفظ المستندات والملفات على الإنترنت.",
"How can you properly shut down the computer?": "لإيقاف تشغيل الحاسوب بصورة صحيحة، نفتح قائمة Start ثم نختار Shut down.",
"What shortcut can you use to quickly select all page content and then copy it?": "نستخدم Ctrl + A لتحديد المحتوى كله، ثم Ctrl + C لنسخه.",
"Closing the current file in Office:": "يمكن إغلاق الملف الحالي من قائمة Office أو File باختيار Close.",
"Where is \"Save\" located?": "يوجد أمر Save ضمن تبويب File لحفظ الملف.",
"Which of the following options is not a type of database?": "وفق الخيارات المحددة في السؤال، الإجابة هي Text Databases.",
"DML stand for ......": "DML اختصار لـ Data Manipulation Language، وهي لغة معالجة البيانات داخل قواعد البيانات.",
"What allows you to access and save database?": "الإجابة المحددة في السؤال هي DCL، وهي اختصار لـ Data Control Language وتُستخدم للتحكم بالصلاحيات في قواعد البيانات.",
"What is E-mail?": "E-mail اختصار Electronic Mail، أي البريد الإلكتروني.",
"Copying text from internet pages onto paper without referencing the original author's name is the process of...": "يُسمّى نسخ عمل الآخرين ونسبه إلى النفس من دون الإشارة إلى المصدر Plagiarism، أي الانتحال.",
"What is latency?": "Latency تعني التأخير الذي يحدث أثناء انتقال البيانات عبر الشبكة.",
"What is digital footprint?": "البصمة الرقمية هي الأثر الذي تتركه أنشطة المستخدم أثناء استخدام الإنترنت.",
"What is Wi-Fi?": "Wi-Fi تقنية اتصال لاسلكي تتيح ربط الأجهزة بالشبكة دون الحاجة إلى كابل شبكة مباشر.",
"What is a username?": "اسم المستخدم (Username) هو المعرّف الذي يُستخدم لتمييز حساب المستخدم.",
"What is the primary purpose of Encryption?": "التشفير يحمي البيانات بتحويلها إلى صيغة غير مقروءة للأشخاص غير المصرح لهم.",
"What are the most common methods for data security breaches by unauthorized hackers?": "ضعف حماية كلمات المرور لدى الموظفين قد يسمح للمهاجمين غير المصرح لهم بالوصول إلى البيانات.",
"Using the internet to download the latest version of a program is an example of": "تنزيل أحدث إصدار من برنامج عبر الإنترنت يُعد مثالاً على تحديث البرامج (Software Update).",
"What does WWW mean?": "WWW اختصار لـ World Wide Web، أي الشبكة العالمية التي تتيح الوصول إلى صفحات الويب المترابطة.",
"A type of computer that allows multiple users to access information across a somewhat large geographical area": "وفق الإجابة المحددة في السؤال، المقصود هو Mainframe Computer، وهو حاسوب مركزي يمكن أن يخدم عدداً كبيراً من المستخدمين.",
"The Name Box appears to the left of the formula bar, what does it display?": "يعرض Name Box اسم الخلية المحددة أو نطاق الخلايا المحدد في Excel.",
"Which of the cell pointers indicates that you can move content to another cell?": "وفق الخيارات في السؤال، يشير مؤشر الماوس ذو العلامة الموجودة عند طرفه إلى إمكانية نقل محتوى الخلية إلى خلية أخرى.",
"Which of the cell pointers indicates that you can fill a series?": "مؤشر التعبئة الصغير على شكل علامة زائد يُستخدم لسحب مقبض التعبئة وإكمال سلسلة من القيم.",
"MS Excel provides the default step value in the \"Fill Series\" dialog box": "القيمة الافتراضية للخطوة (Step value) في مربع Fill Series هي 1.",
"Where do we find control buttons in Excel 2019?": "توجد أزرار التحكم بالنافذة، مثل التصغير والتكبير والإغلاق، في شريط العنوان (Title Bar).",
"How can you fill a cell with a pattern color in Excel?": "نفتح Format Cells ثم تبويب Fill لاختيار لون تعبئة الخلية.",
"What is the maximum column width?": "الحد الأقصى لعرض العمود في Excel هو 255 حرفاً تقريباً وفق مقياس عرض الأعمدة في البرنامج.",
"When you want to add a color to a font cell in Excel, which of the following options should you choose from the Home tab?": "الإجابة المحددة في السؤال هي Fill Color، لكن هذا الخيار يغيّر لون خلفية الخلية؛ أما لون الحروف فيُغيَّر باستخدام Font Color.",
"How can you change column width to 2 cm?": "الإجابة المحددة في السؤال هي None of above؛ إذ لا يتضمن السؤال خياراً مباشراً صحيحاً لتعيين العرض بالسنتيمتر.",
"How can you merge three cells into one cell in Excel?": "نحدد الخلايا الثلاث ثم نختار Merge & Center من تبويب Home لدمجها في خلية واحدة.",
"From where can you delete a worksheet in Excel?": "الإجابة المحددة في السؤال هي None of above. عملياً، يمكن حذف ورقة العمل من Home > Delete > Delete Sheet أو بالنقر بزر الفأرة الأيمن على تبويب الورقة واختيار Delete.",
"Where can you hide a row in Excel?": "يمكن إخفاء الصف من Home > Format > Hide & Unhide > Hide Rows.",
"Where can you insert a symbol in Microsoft Excel?": "لإدراج رمز في Excel، نذهب إلى تبويب Insert ثم نختار Symbol.",
"From where can you know the word count in a Word page?": "يمكن معرفة عدد الكلمات من شريط الحالة (Status Bar) أسفل نافذة Word.",
"How can you add the time and date in programs like Microsoft Word, PowerPoint?": "لإدراج التاريخ والوقت، نفتح تبويب Insert ثم نختار أمر Date & Time.",
"What does a table object's size depend on?": "وفق الإجابة المحددة في السؤال، يعتمد حجم الجدول على النص المُدرج أو على طريقة عرضه وإمكانية تعديله؛ لذلك يشير الخيار D إلى A or C.",
"Where do the styles appear in the tabs in Word 2016?": "تظهر مجموعة Styles ضمن تبويب Home في Word 2016.",
"Which of the following is not part of a slide design?": "الإجابة المحددة في السؤال هي Slide layout، مع ملاحظة أن تخطيط الشريحة يُعد فعلياً جزءاً من تصميم العرض في PowerPoint.",
"How many views in PowerPoint?": "وفق الإجابة المحددة في السؤال، عدد طرق العرض هو 5.",
"Two-factor authentication provides:": "المصادقة الثنائية تضيف طبقة حماية إضافية للحساب أو البريد الإلكتروني من خلال التحقق بخطوتين.",
"If you want to forward all incoming messages to someone else, what do you choose?": "لإعادة توجيه الرسائل الواردة تلقائياً إلى شخص آخر، نختار Forwarding automatically.",
    "If you want to send search/research in email what choose?": "لإرسال بحث أو ملف مع البريد الإلكتروني كمرفق، نختار Send as attachment.",
"Where is an email saved before sending and for editing?": "تُحفظ الرسالة التي لم تُرسل بعد في مجلد Drafts، ويمكن فتحها وتعديلها لاحقاً.",
"What is the number of automatic backup copies PowerPoint saves when presentations are disabled/closed?": "حسب الإجابة المعتمدة في السؤال، العدد هو نسخة واحدة.",
"How can you make the slide show automatic in PowerPoint?": "يمكن ضبط عرض الشرائح ليعمل تلقائياً باستخدام المؤقت (Timer).",
"Which of the following is NOT a method to create a presentation?": "الإجابة هي Slide scan؛ لأنها ليست من الطرق المذكورة لإنشاء عرض تقديمي.",
"What is the extension for government websites?": "الامتداد .gov يُستخدم عادةً للمواقع الحكومية.",
"What is the document that people see when browsing?": "صفحة الويب (Web Page) هي الصفحة التي يشاهدها المستخدم عند تصفح الإنترنت.",
"What are the features of e-commerce?": "وفق الإجابة المحددة في السؤال، من مميزات التجارة الإلكترونية توفر الخدمات على مدار 24 ساعة.",
"What is the site/service that saves documents and files online?": "Google Drive خدمة تخزين سحابي لحفظ الملفات والمستندات عبر الإنترنت.",
"What does .com domain represent?": "الامتداد .com اختصار لكلمة Commercial، ويُستخدم عادةً للمواقع التجارية.",
"Which of the following options is used to save documents and files over the internet?": "يمكن استخدام Google Drive لحفظ الملفات والمستندات على الإنترنت.",
"How can you properly shut down the computer?": "نفتح قائمة Start ثم نختار Shut down لإيقاف تشغيل الحاسوب بصورة صحيحة.",
"What shortcut can you use to quickly select all page content and then copy it?": "نستخدم Ctrl + A لتحديد المحتوى كله، ثم Ctrl + C لنسخه.",
"Closing the current file in Office:": "وفق الإجابة المحددة، نختار Close من قائمة Office لإغلاق الملف الحالي.",
"Where is \\\"Save\\\" located?": "يوجد أمر Save ضمن تبويب File لحفظ الملف.",
"Which of the following options is not a type of database?": "الإجابة المحددة هي Text Databases.",
"DML stand for ......": "DML اختصار لـ Data Manipulation Language، وهي لغة معالجة البيانات في قواعد البيانات.",
"What allows you to access and save database?": "الإجابة المحددة في السؤال هي DCL، وهي اختصار لـ Data Control Language.",
"What is E-mail?": "E-mail اختصار لـ Electronic Mail، أي البريد الإلكتروني.",
"Copying text from internet pages onto paper without referencing the original author's name is the process of...": "يُسمّى ذلك Plagiarism، أي الانتحال أو نقل عمل الآخرين دون الإشارة إلى المصدر.",
"What is latency?": "Latency تعني التأخير الذي يحدث أثناء انتقال البيانات.",
"What is digital footprint?": "البصمة الرقمية هي الأثر الذي تتركه أنشطة المستخدم أثناء استخدام الإنترنت.",
"What is Wi-Fi?": "Wi-Fi تقنية اتصال لاسلكي تتيح ربط الأجهزة بالشبكة دون الحاجة إلى كابل شبكة مباشر.",
"What is a username?": "Username هو اسم المستخدم الذي يميّز حسابه عن الحسابات الأخرى.",
"What is the primary purpose of Encryption?": "التشفير يحمي البيانات بتحويلها إلى صيغة غير مقروءة لغير المصرح لهم.",
"What are the most common methods for data security breaches by unauthorized hackers?": "وفق الإجابة المحددة، ضعف حماية كلمات المرور لدى الموظفين قد يسمح بالوصول غير المصرح به إلى البيانات.",
"Using the internet to download the latest version of a program is an example of": "يُسمّى تنزيل أحدث إصدار من برنامج Software Update، أي تحديث البرامج.",
"What does WWW mean?": "WWW اختصار لـ World Wide Web، أي الشبكة العالمية للويب. ملاحظة: خيارات السؤال لا تتضمن التوسعة الصحيحة حرفياً.",
"A type of computer that allows multiple users to access information across a somewhat large geographical area": "الإجابة المحددة هي Mainframe Computer، وهو حاسوب مركزي يمكن أن يخدم عدداً كبيراً من المستخدمين.",
"The Name Box appears to the left of the formula bar, what does it display?": "يعرض Name Box عنوان الخلية المحددة أو اسم نطاق الخلايا المحدد في Excel.",
"Which of the cell pointers indicates that you can move content to another cell?": "وفق السؤال، المؤشر الذي يشير إلى إمكانية نقل محتوى الخلية هو مؤشر الماوس ذي العلامة عند طرفه.",
"Which of the cell pointers indicates that you can fill a series?": "مؤشر التعبئة الصغير الذي يظهر على شكل علامة زائد يُستخدم لسحب مقبض التعبئة وإكمال سلسلة.",
"MS Excel provides the default step value in the \\\"Fill Series\\\" dialog box": "القيمة الافتراضية لـ Step value في مربع Fill Series هي 1.",
"Where do we find control buttons in Excel 2019?": "توجد أزرار التصغير والتكبير والإغلاق في شريط العنوان (Title Bar).",
"How can you fill a cell with a pattern color in Excel?": "نفتح Format Cells ثم تبويب Fill لاختيار لون تعبئة الخلية أو نمطها.",
"What is the maximum column width?": "الحد الأقصى لعرض العمود في Excel هو 255 وفق مقياس عرض الأعمدة في البرنامج.",
"When you want to add a color to a font cell in Excel, which of the following options should you choose from the Home tab?": "الإجابة المحددة في السؤال هي Fill Color، لكن هذا يغيّر خلفية الخلية؛ أما لون الخط فيُغيّر بواسطة Font Color.",
"How can you change column width to 2 cm?": "الإجابة المحددة في السؤال هي None of above؛ لأن الخيارات لا توفر طريقة مباشرة صحيحة لتعيين العرض بالسنتيمتر.",
"How can you merge three cells into one cell in Excel?": "نحدد الخلايا الثلاث ثم نختار Merge & Center من تبويب Home لدمجها.",
"From where can you delete a worksheet in Excel?": "الإجابة المحددة هي None of above. عملياً يمكن حذف الورقة من Home > Delete > Delete Sheet.",
"Where can you hide a row in Excel?": "الإجابة المحددة هي من تبويب Home ثم Format ثم Hide & Unhide ثم Hide Rows.",
"Where can you insert a symbol in Microsoft Excel?": "نفتح تبويب Insert ثم نختار Symbol لإدراج رمز.",
"From where can you know the word count in a Word page?": "يمكن معرفة عدد الكلمات من شريط الحالة (Status Bar) أسفل نافذة Word.",
"How can you add the time and date in programs like Microsoft Word, PowerPoint?": "نفتح Insert ثم نختار أمر Date & Time لإدراج التاريخ والوقت.",
"What does a table object's size depend on?": "وفق الإجابة المحددة، يعتمد حجم الجدول على النص المُدرج وطريقة عرضه؛ والإجابة هي A or C.",
"Where do the styles appear in the tabs in Word 2016?": "توجد مجموعة Styles ضمن تبويب Home في Word 2016.",
"Which of the following is not part of a slide design?": "الإجابة المحددة هي Slide layout.",
"How many views in PowerPoint?": "وفق الإجابة المعتمدة في السؤال، عدد طرق العرض هو 5.",
"Two-factor authentication provides:": "المصادقة الثنائية تضيف طبقة حماية إضافية للحساب من خلال التحقق من هوية المستخدم بخطوتين.",
"If you want to forward all incoming messages to someone else, what do you choose?": "نختار Forwarding automatically لإعادة توجيه الرسائل الواردة تلقائياً.",
"If you want to send search/research in email what choose?": "لإرسال البحث أو الملف مع البريد الإلكتروني، نختار Send as attachment.",
"Where is an email saved before sending and for editing?": "تُحفظ الرسالة التي لم تُرسل بعد في مجلد Drafts، ويمكن تعديلها قبل الإرسال.",
"To exchange texts between two or more people": "الإجابة المحددة هي IM (Instant Messaging)، أي المراسلة الفورية لتبادل الرسائل النصية.",
"Desktop background is called:": "تُسمّى خلفية سطح المكتب Wallpaper.",
"Where can you find file information such as name and size?": "وفق الإجابة المحددة في السؤال، نختار File لعرض معلومات الملف.",
"The byte is a unit of measurement for": "البايت (Byte) وحدة قياس تُستخدم للتعبير عن سعة الذاكرة أو حجم البيانات.",
"Data security breaches by unauthorized intruders": "وفق الإجابة المحددة، من أسباب اختراق البيانات عدم استخدام الموظفين كلمات مرور قوية.",
"What is a username?": "Username هو اسم المستخدم أو المعرّف الخاص بالحساب.",
"What are the small text files stored on a user's computer by a web browser to save information and track active user?": "تُسمّى Cookies، وهي ملفات نصية صغيرة يحفظها المتصفح لتخزين معلومات عن المستخدم أو الجلسة.",
"What is online shopping?": "التسوق الإلكتروني هو شراء المنتجات عبر الإنترنت.",
"What does WWW stand for?": "WWW اختصار لـ World Wide Web، أي الشبكة العالمية للويب.",
"The primary purpose of protecting data online is:": "الهدف الأساسي وفق السؤال هو حماية خصوصية البيانات الشخصية.",
"Which of the following is a strong password example?": "الإجابة هي B9hSYt8x؛ لأنها تجمع بين الأحرف والأرقام بدلاً من استخدام كلمة سهلة التخمين.",
"What is the result of the function =MIN(2, 5, 25, 10)?": "الدالة MIN تُرجع أصغر قيمة من الأرقام المعطاة؛ والنتيجة هي 2.",
"The Show group of the View tab is used to show:": "تُستخدم مجموعة Show في تبويب View لإظهار عناصر مثل Ruler وGridlines وNavigation Pane وفق خيارات السؤال.",
"To insert a new sheet, click the button:": "وفق الإجابة المحددة، نختار Home ثم Insert ثم Insert Sheet.",
"What is the main purpose of using the Excel 2016 application?": "يُستخدم Excel بصورة أساسية لإجراء الحسابات والتحليلات الإحصائية وتنظيم البيانات.",
"It is acceptable to let long text flow into adjacent cells in a worksheet when": "يمكن أن يمتد النص إلى الخلايا المجاورة عندما تكون الخلايا المجاورة فارغة.",
"What happens when you press Ctrl + X after selecting some cells in Excel?": "يُجهّز Ctrl + X الخلايا المحددة للقص، لتتمكن من نقل محتواها إلى مكان آخر.",
"In Microsoft Excel, to fill a cell with a specific color or pattern, do the following:": "وفق الإجابة المحددة، نفتح Format Cells ثم Fill ونختار اللون أو النمط المطلوب.",
"What is the default value for step in Fill series dialog box?": "القيمة الافتراضية لـ Step في مربع Fill Series هي 1.",
"The default name for files created in Excel 2019 is:": "اسم المصنف الافتراضي في Excel هو Book، مثل Book1.",
"How can you change an existing chart to a Line Chart in Excel 2016?": "نحدد المخطط ثم نفتح Design ونختار Change Chart Type، وبعدها نختار Line Chart.",
"To insert a new column between Column A and Column B, press the button": "وفق الإجابة المحددة، نستخدم Insert Columns من مجموعة Cells.",
"Which command will you choose to convert a column of data into a row?": "نستخدم Paste Special ثم Transpose لتحويل البيانات من عمود إلى صف.",
"When you gather data from a database to include it in a project within Excel, this process is called:": "وفق الإجابة المحددة في السؤال، تُسمّى العملية Data collection، أي جمع البيانات.",
"To insert a new row between row 10 and row 11, click the button:": "الإجابة المحددة هي All answers given are incorrect؛ لأن الخيارات المعروضة لا تحدد الأمر الصحيح وفق صياغة السؤال.",
"From where can you know the word count in a Word page?": "يمكن الاطلاع على عدد الكلمات من شريط الحالة (Status Bar) في أسفل Word.",
"How can you change the line spacing in Word 2016?": "نستخدم تبويب Home، ثم مجموعة Paragraph، ونختار Line and Paragraph Spacing.",
"How can you change the orientation of a page in Word 2016 from portrait to landscape?": "نفتح تبويب Layout ثم Orientation ونختار Landscape.",
"How do you apply a text highlight color in Word 2016?": "نحدد النص ثم نفتح تبويب Home ونختار Text Highlight Color من مجموعة Font.",
"Which view in PowerPoint can be used to enter speaker comments?": "وفق الإجابة المحددة، نستخدم Notes Page View لإضافة ملاحظات المتحدث.",
"In a PowerPoint presentation....": "يمكن إدراج مقاطع الصوت والفيديو معاً في عرض PowerPoint.",
"Which of the following section does not exist in a slide layout?": "الإجابة المحددة هي Animations؛ إذ لا تُعد جزءاً من أقسام تخطيط الشريحة.",
"Animation schemes can be applied to .......... in the presentation": "وفق الإجابة المحددة، يمكن تطبيق مخططات الحركة على جميع الشرائح أو شرائح محددة أو الشريحة الحالية.",
"Headers and footers can include text and graphics, as well as their": "وفق الإجابة المحددة، يمكن أن تتضمن الرؤوس والتذييلات التاريخ ورقم الصفحة والوقت.",
"Which of the following is the default page setup orientation for slides in PowerPoint?": "الاتجاه الافتراضي للشرائح في PowerPoint هو Landscape، أي أفقي.",
"Which of the following tools enable you to add text to a slide without using the standard placeholders?": "نستخدم أداة Text Box لإضافة نص إلى الشريحة من دون استخدام العناصر النائبة الجاهزة.",
"You access the recycle bin through an icon located:": "يمكن الوصول إلى سلة المحذوفات من الأيقونة الموجودة على سطح المكتب.",
"Which of the following is an operating system?": "Windows هو نظام تشغيل، بينما البرامج الأخرى المذكورة ليست أنظمة تشغيل.",
"Which folder usually contains user documents?": "عادةً ما تُحفظ مستندات المستخدم داخل مجلد Documents.",
"The unit that is responsible for receiving data and messages from other devices within networks or another networks connected in the same network is": "وفق الإجابة المحددة في السؤال، الوحدة هي Receiving unit، أي وحدة الاستقبال.",
"Which component coordinates all computer activities?": "وحدة المعالجة المركزية CPU تنفذ التعليمات وتنسق كثيراً من عمليات الحاسوب.",
"GB means:": "GB اختصار لـ Gigabyte، وهي وحدة لقياس سعة تخزين البيانات.",
"Which device converts digital signals to printed output?": "الطابعة (Printer) تحوّل البيانات الرقمية إلى مخرجات مطبوعة على الورق.",
"What does the Reply All function do?": "Reply All يرسل الرد إلى المرسل وإلى جميع المستلمين الآخرين في سلسلة البريد.",
"Insert a header and footer from the tab": "نفتح تبويب Insert ثم نختار Header أو Footer لإضافتهما إلى المستند.",
"Find and replace in Ms word from": "وفق الإجابة المحددة، الاختصار Ctrl + H يفتح نافذة Find and Replace في Word.",
"What functions are included in the Home tab in Microsoft Office programs?": "يتضمن Home أدوات تنسيق النصوص وتغيير نوع الخط وحجمه ومحاذاة النص.",
"What happens when you press the Home key on the keyboard in Word?": "ينقل مفتاح Home مؤشر الكتابة إلى بداية السطر الحالي.",
"What is the shortcut used to insert a page break in a Microsoft Word document?": "الاختصار Ctrl + Enter يُدرج فاصل صفحة (Page Break) في Word.",
"The number of steps between the start and the end in the AutoContent Wizard is usually:": "وفق الإجابة المحددة في السؤال، العدد المعتاد هو 3 خطوات.",
"Which presentation view works best when presenting inside Auditorium?": "نستخدم Slide Show لعرض الشرائح بملء الشاشة أمام الجمهور.",
"To add a new slide, you click on:": "الاختصار Ctrl + M يُستخدم لإضافة شريحة جديدة في PowerPoint.",
"Which of the following section does not exist in a slide layout?": "حسب مفتاح الإجابة، الخيار هو Animations.",
"How can you navigate between slides while giving a PowerPoint presentation in front of an audience?": "يمكن عرض الشرائح بالتتابع باستخدام وضع Slide Show والتنقل بينها أثناء العرض.",
"Accessing previously viewed Internet browser content without an internet connection is done via:": "تُخزَّن بعض محتويات صفحات الويب مؤقتاً في Cache، وقد تسمح بعرضها دون اتصال بالإنترنت.",
"The tool that enables a researcher to obtain references from the internet is:": "حسب الإجابة المحددة في السؤال، الخيار هو Yahoo.",
"Which of the following is considered an internet browser?": "Google Chrome متصفح إنترنت يُستخدم لفتح صفحات الويب.",
"What can a hyperlink link to?": "يمكن للرابط التشعبي Hyperlink أن يربط بصفحات ويب أو مستندات.",
"The element that contains rows and columns inside Excel is:": "تحتوي ورقة العمل Worksheet على صفوف وأعمدة تتكون عند تقاطعها الخلايا.",
"What is the function used to calculate the standard deviation in Excel?": "تُستخدم الدالة STDEV في صياغة السؤال لحساب الانحراف المعياري.",
"What is the shortcut used to go to the first cell in a worksheet?": "الاختصار Ctrl + Home ينقل المستخدم إلى بداية ورقة العمل، أي الخلية A1 عادةً.",
"To add the currency symbol Iraqi dinar after the number 1000 in Excel:": "حسب الخيارات، الرمز المحدد للدينار العراقي هو IQD.",
"In which tab can you change the font type in Excel or PowerPoint?": "نغيّر نوع الخط من تبويب Home ضمن مجموعة Font.",
"What is the function of the shortcut Ctrl + D in Microsoft Excel?": "يُستخدم Ctrl + D لتعبئة الخلايا المحددة بمحتوى الخلية العلوية.",
"Which of the following is an operating system?": "Windows نظام تشغيل يدير موارد الحاسوب ويتيح تشغيل البرامج.",
"To create a new document:": "نختار New لإنشاء مستند جديد.",
"Which of the following categories is used to transfer data in databases?": "DML اختصار Data Manipulation Language، وتُستخدم للتعامل مع البيانات داخل قواعد البيانات.",
"What is the primary role of a firewall in network security?": "يعمل Firewall على منع الوصول غير المصرح به إلى الشبكة.",
"Where is the Recycle Bin located?": "توجد أيقونة Recycle Bin عادةً على سطح المكتب Desktop.",
"When saving files, where are they stored by default?": "حسب مفتاح الإجابة، الخيار هو Document.",
"What is the function shortcut Ctrl + O?": "الاختصار Ctrl + O يُستخدم لفتح ملف موجود.",
"What is the shortcut used to open the help or assistance window?": "المفتاح F1 يُستخدم عادةً لفتح المساعدة Help.",
"How can you remove a column between two columns in Excel?": "نضغط بزر الفأرة الأيمن على عنوان العمود المطلوب ثم نختار Delete.",
"How can you move a sheet from one workbook to a new workbook using:": "حسب مفتاح الإجابة في السؤال، الخيار المحدد هو None of above.",
"How can you open the Microsoft Excel application?": "يمكن فتح Excel من قائمة Start ثم All Programs واختيار Microsoft Excel.",
"Which key is used to move between cells vertically in Excel?": "يُستخدم Enter للتنقل عمودياً بين الخلايا وفق اتجاه الحركة وإعدادات Excel.",
"If the values (18, 5, 6) are present in a cell, and the function used is MAX, what is the result?": "الدالة MAX تُرجع أكبر قيمة؛ والنتيجة هي 18.",
"What is the benefit of adding patterns (pattern fill) to cells in Excel?": "تساعد أنماط التعبئة على تمييز الخلايا بصرياً عن بعضها.",
"What function is used to calculate the number of failing students?": "تُستخدم COUNTIF لعدّ الخلايا التي تحقق شرطاً معيناً، مثل عدد الطلبة الراسبين.",
"What is the function of the small square located in the corner of an Excel cell?": "يُسمّى المربع الصغير Fill Handle، ويُستخدم للتعبئة التلقائية ونسخ الصيغ أو إكمال السلاسل.",
"How can you delete the third sheet from an Excel workbook?": "نحدد الورقة الثالثة، ثم نضغط بزر الفأرة الأيمن ونختار Delete.",
"Which of the following options can convert a column of data into a row?": "نستخدم Paste Special ثم Transpose لتحويل البيانات من عمود إلى صف.",
"How can a column be inserted between A and B in Excel?": "نحدد العمود B ثم نختار Insert؛ فيُدرج عمود جديد قبله بين A وB.",
"What is the extension of saved files in Excel?": "امتداد ملفات Excel الحديثة هو .xlsx.",
"Which menu insert column in Excel?": "حسب مفتاح الإجابة، نستخدم تبويب Home لإدراج عمود من مجموعة Cells.",
    "What is the result of the function MAX when the values 18, 5, and 6 are present in a cell?": "الدالة MAX تُرجع أكبر رقم بين القيم 18 و5 و6، وهو 18.",
"What is the function of the shortcut Ctrl + B?": "الاختصار Ctrl + B يجعل النص عريضاً Bold أو يلغي التنسيق عند استخدامه مرة أخرى.",
"When repeated word in Ms Word what color appear under?": "حسب مفتاح الإجابة، يظهر الخط الأحمر المتموج تحت الكلمة التي يعتقد Word أنها مكتوبة بصورة خاطئة.",
"Where can you find the Watermark in Microsoft Word?": "في إصدارات Word الحديثة، يوجد Watermark ضمن تبويب Design.",
"What is the benefit of text WordArt in Microsoft Word?": "يُستخدم WordArt لتحسين مظهر النص وجعله أكثر جاذبية.",
"Can video and audio clips be inserted into PowerPoint?": "نعم، يمكن إدراج مقاطع الفيديو والصوت في PowerPoint.",
"How can you add a logo in PowerPoint?": "يمكن إضافة الشعار كصورة من خلال Insert ثم Pictures.",
"When sending a PowerPoint file via email, what option is used?": "يمكن إرسال ملف PowerPoint عبر البريد الإلكتروني كمرفق Attachment.",
"What is the best way to view slides in PowerPoint?": "يُستخدم Slide Show لعرض الشرائح أمام الجمهور بملء الشاشة.",
"What does HTTP stand for?": "HTTP اختصار لـ Hypertext Transfer Protocol، وهو بروتوكول نقل النص التشعبي.",
"What is the icon for bookmarking a web page or saving it for later access?": "حسب الخيارات، تُستخدم أيقونة النجمة Star لحفظ الصفحة في المفضلة.",
"What is a Web Browser?": "متصفح الويب برنامج يتيح فتح صفحات الويب وعرض محتواها.",
"How can multiple users use a large mainframe computer at the same time?": "يمكن لعدة مستخدمين الوصول إلى الحاسوب المركزي عبر أجهزة طرفية أو اتصالات متعددة.",
"When merging e-mail with data, what is the term used?": "حسب مفتاح الإجابة، الخيار المحدد هو None of above.",
"What is the difference between the inbox and spam messages?": "Inbox يستقبل الرسائل الواردة، أما Spam فيحتوي عادةً على الرسائل غير المرغوب فيها أو المشبوهة.",
"What is the best password you can use to protect your account?": "كلمة المرور الأقوى بين الخيارات هي ali@17&ah0؛ لأنها تجمع الأحرف والأرقام والرموز.",
"What is the primary role of a firewall in network security?": "وظيفة Firewall الأساسية منع الاتصالات أو عمليات الوصول غير المصرح بها إلى الشبكة.",
"Which of the following options makes the command 'Edit > fill across worksheet' active in Excel?": "حسب مفتاح الإجابة، يصبح الأمر متاحاً عند تحديد عدة أوراق عمل.",
"Where can you set the shading color for a range of cells in Excel?": "يمكن تغيير لون تعبئة الخلايا من Format Cells > Pattern في الإصدارات القديمة، أو Fill Color في الإصدارات الحديثة.",
"Where can you set page borders in Excel?": "حسب مفتاح الإجابة، لا يوفر Excel أمراً مباشراً مماثلاً لحدود الصفحات في Word.",
"While using Find and Replace in Excel, which of the following statements is correct?": "يمكن البحث والاستبدال ضمن ورقة العمل أو ضمن مصنف Excel وفق نطاق البحث المحدد.",
"Which menu option can be used to split windows into two parts?": "نختار View ثم Split لتقسيم نافذة ورقة العمل إلى أجزاء.",
"What does A15 represent in Excel?": "A15 تعني العمود A والصف 15.",
"To insert a new column between Column A and Column B, click the button": "حسب مفتاح الإجابة، نستخدم Insert Columns من مجموعة Cells.",
"What does 'Sort' mean?": "Sort تعني ترتيب البيانات، مثل الأرقام تصاعدياً أو تنازلياً والنصوص أبجدياً؛ لذلك الإجابة All of above.",
"If the data values linked to a pie chart in Excel change, does this affect the chart?": "يتحدّث المخطط تلقائياً عند تغيير البيانات المرتبطة به، ما لم تكن هناك مشكلة في مصدر البيانات.",
"When deleting a row between Column A and Column B, what happens to the data?": "ملاحظة: صياغة السؤال تخلط بين الصف والعمود؛ حذف صف يؤدي عادةً إلى انتقال الصفوف التي تحته إلى الأعلى.",
"In Excel, every file is a workbook containing different sheets. Which of the following cannot be a sheet in the workbook?": "حسب مفتاح الإجابة، الخيار هو Data sheet.",
"When opening page setup settings, what is usually the default orientation?": "الاتجاه الافتراضي المعتاد لإعداد الصفحة هو Portrait، أي عمودي.",
"How can you change the column width to 30 in Excel?": "نحدد العمود ثم نستخدم Format > Column Width ونكتب القيمة 30.",
"What is the function of the shortcut Ctrl + D in Microsoft Excel?": "يُستخدم Ctrl + D لتعبئة الخلايا المحددة بمحتوى الخلية العلوية.",
"How can you find the minimum value in Excel?": "تُستخدم الدالة MIN لإيجاد أصغر قيمة ضمن مجموعة أرقام.",
"A comment can be inserted from": "حسب مفتاح الإجابة، يمكن إدراج تعليق من تبويب Review.",
"Which key do you press to check spelling?": "المفتاح F7 يُستخدم لتشغيل التدقيق الإملائي والنحوي في Word.",
"How can you select all text?": "الاختصار Ctrl + A يُستخدم لتحديد كل النص أو كل المحتوى في المستند.",
"How can you navigate from one page to another in Word without using the mouse or arrows?": "يمكن التنقل بين الصفحات باستخدام Ctrl + Page Up أو Ctrl + Page Down.",
"When repeated word in Ms Word what color appear under?": "حسب مفتاح الإجابة، يظهر خط أحمر متموج تحت الكلمة التي يشير Word إلى احتمال وجود خطأ إملائي فيها.",
"Where can you find the Watermark in Microsoft Word?": "يوجد Watermark في تبويب Design في إصدارات Word الحديثة.",
"What is the benefit of text WordArt in Microsoft Word?": "يساعد WordArt على تنسيق النص بطريقة زخرفية وجذابة.",
"What is the benefit of an IP address?": "يساعد عنوان IP على تحديد الجهاز أو واجهته ضمن الشبكة.",
"How can you mark an important page while browsing to save it and return to it later?": "نضغط على أيقونة النجمة لإضافة الصفحة إلى المفضلة والعودة إليها لاحقاً.",
"If you exit the page you are browsing, where will you go?": "حسب مفتاح الإجابة، يؤدي ذلك إلى الرجوع إلى الصفحة السابقة.",
"Which of the following options is considered an internet browser?": "MS Explorer، والمقصود غالباً Internet Explorer، هو متصفح ويب.",
"When the internet disconnects, how can a web page be opened without a connection?": "قد تسمح ذاكرة Cache بعرض نسخة محفوظة سابقاً من صفحة ويب دون اتصال.",
"What is the technology that allows communication between all people around the world?": "الإنترنت شبكة عالمية تتيح التواصل وتبادل المعلومات بين المستخدمين في مختلف أنحاء العالم.",
"Where is the Recycle Bin located?": "توجد أيقونة Recycle Bin عادةً على سطح المكتب.",
"The purpose of a file extension": "امتداد الملف يساعد على معرفة نوع الملف والبرنامج المناسب لفتحه.",
"What is the function of the shortcut Ctrl + X?": "الاختصار Ctrl + X يقص النص أو العناصر المحددة ويضعها في الحافظة Clipboard.",
"How can multiple users use a large mainframe computer at the same time?": "يستطيع عدة مستخدمين استخدام الحاسوب المركزي من مواقع متعددة عبر اتصالات أو أجهزة طرفية.",
"Which of the following is not a type of database?": "حسب مفتاح الإجابة، الخيار هو Text Data Bases.",
"When replying to an email, what can happen to the message?": "يمكن الرد على المرسل وحده باستخدام Reply أو على المرسل وجميع المستلمين باستخدام Reply All.",
"Which view displays the slides in a presentation as thumbnails?": "يعرض Slide Sorter الشرائح على شكل صور مصغرة لتسهيل ترتيبها.",
"What is the shortcut used to show the help menu?": "المفتاح F1 يفتح نافذة المساعدة Help في كثير من برامج Windows.",
"Where is the Recycle Bin located in the Windows system?": "حسب مفتاح الإجابة، توجد سلة المحذوفات على سطح المكتب.",
"What is the best way to shut down a computer?": "نختار Shut down من قائمة Start لإيقاف تشغيل الحاسوب بطريقة صحيحة.",
"Which of the following dialog boxes tells you about readiness to create a new document?": "حسب مفتاح الإجابة، الخيار هو Start screen.",
"How do you open a new window in the browser?": "الاختصار Ctrl + N يفتح نافذة جديدة في كثير من المتصفحات.",
"How can you change the desktop background in Windows?": "يمكن تغيير خلفية سطح المكتب من Settings ثم Personalization ثم Background.",
"Which of the following statements is incorrect regarding Find and Replace?": "حسب مفتاح الإجابة، العبارة غير الصحيحة هي البحث عن تنسيق مائل واستبداله بنص مميز بالطريقة المذكورة.",
"When saving a file in Excel 2019, what name is given to the file?": "اسم المصنف الافتراضي في Excel هو Book، مثل Book1.",
"What symbol must precede a function in Excel?": "تبدأ الصيغة في Excel بعلامة يساوي =.",
"In Ms Excel, what is the default number that appears in the Fill dialog box?": "حسب مفتاح الإجابة، القيمة الافتراضية هي 1.",
"Excel displays the current cell address in:": "يظهر عنوان الخلية الحالية في Name Box، الموجود بجانب شريط الصيغة.",
"How can numbers from 0 to 100 be changed to red in Excel?": "نستخدم Conditional Formatting لتطبيق لون الخط الأحمر على الأرقام التي تقع ضمن النطاق المطلوب.",
"What is the function used to find the highest value in Excel?": "تُستخدم الدالة MAX لإيجاد أكبر قيمة ضمن مجموعة أرقام.",
"How can you insert a new worksheet in Excel?": "يمكن إضافة ورقة جديدة من Home ثم Insert، أو بالنقر بزر الفأرة الأيمن على تبويب الورقة واختيار Insert Worksheet.",
"What is the function used to find the number of failing students?": "تُستخدم COUNTIF لعدّ الخلايا التي تحقق شرطاً محدداً، مثل عدد الطلبة الذين تقل درجاتهم عن درجة النجاح.",
"How can you change the worksheet direction from right to left or vice versa in Excel?": "حسب الإجابة المحددة في السؤال، يتم تغيير اتجاه ورقة العمل من Page Layout.",
"If you open a workbook and have three sheets, how can you delete the third sheet in Excel?": "نضغط بزر الفأرة الأيمن على تبويب الورقة الثالثة ثم نختار Delete.",
"What is the function of the shortcut Ctrl + X?": "الاختصار Ctrl + X يقص المحتوى المحدد ويحفظه مؤقتاً في Clipboard لنقله إلى مكان آخر.",
"What is the function used to find the minimum value in Excel?": "تُستخدم الدالة MIN لإيجاد أصغر قيمة ضمن مجموعة من الأرقام.",
"Which of the following options makes the command 'Edit > fill across worksheet' active in Excel?": "وفق الإجابة المحددة، يصبح الأمر متاحاً عند تحديد عدة أوراق عمل معاً.",
"Where can you set the shading color for a range of cells in Excel?": "يمكن تغيير لون تعبئة الخلايا من Format Cells > Pattern أو باستخدام Fill Color؛ والإجابة المحددة في السؤال هي All of above.",
"Where can you set page borders in Excel?": "وفق الإجابة المحددة في السؤال، لا يوجد أمر مخصص لإضافة حدود للصفحة بالطريقة نفسها الموجودة في Word.",
"What does A15 represent in Excel?": "A15 تمثل الخلية الواقعة عند تقاطع العمود A مع الصف 15.",
"To insert a new column between Column A and Column B, click the button": "نستخدم Insert Columns من مجموعة Cells لإدراج عمود جديد بين A وB.",
"What does Sort mean?": "Sort تعني ترتيب البيانات تصاعدياً أو تنازلياً أو أبجدياً؛ لذلك الإجابة المحددة هي All of above.",
"If the data values linked to a pie chart in Excel change, does this affect the chart?": "يتحدّث المخطط تلقائياً عند تغيير البيانات المرتبطة به، وقد تتغير القيم المعروضة فيه.",
"When deleting a row between Column A and Column B, what happens to the data?": "صياغة السؤال تخلط بين الصف والعمود؛ حذف صف يؤدي عادةً إلى انتقال الصفوف التي تحته إلى الأعلى، أما حذف عمود فيؤدي إلى انتقال الأعمدة التي على يمينه إلى اليسار.",
"In Excel, every file is a workbook containing different sheets. Which of the following cannot be a sheet in the workbook?": "وفق الإجابة المحددة، الخيار هو Data sheet.",
"When opening page setup settings, what is usually the default orientation?": "الاتجاه الافتراضي المعتاد لإعداد الصفحة هو Portrait، أي عمودي.",
"How can you change the column width to 30 in Excel?": "نحدد العمود ثم نذهب إلى Format ونختار Column Width ونُدخل القيمة المطلوبة.",
"What is the extension of saved files in Excel?": "الامتداد الافتراضي لملفات Excel الحديثة هو .xlsx.",
"Which menu insert column in Excel?": "وفق الإجابة المحددة في السؤال، نستخدم Home لإدراج عمود من مجموعة Cells.",
"Which of the following options can convert a column of data into a row?": "نستخدم Paste Special ثم Transpose لتحويل البيانات من عمود إلى صف.",
"What is the most appropriate way to help the blind use a computer?": "يمكن مساعدة المكفوفين باستخدام برامج قراءة الشاشة أو لوحة مفاتيح برايل.",
"What is the command used to bold text in Microsoft Office programs?": "الاختصار Ctrl + B يجعل النص عريضاً Bold.",
"How can a chart be inserted in Microsoft Word?": "نفتح Insert ثم نختار Chart لإدراج مخطط داخل المستند.",
"How can you adjust margins in Word?": "نفتح Layout ثم Margins ونختار الهوامش المناسبة.",
"How can you print a specific number of pages in Word?": "نفتح File ثم Print، ونكتب أرقام الصفحات المطلوبة في خانة Pages.",
"What is the shortcut Ctrl + S?": "الاختصار Ctrl + S يُستخدم لحفظ الملف.",
"Can video and audio clips be inserted into PowerPoint?": "نعم، يمكن إدراج مقاطع الفيديو والصوت في PowerPoint؛ والإجابة هي Both.",
"If you want to display a fixed element on all slides in PowerPoint, where should you place it?": "نضع العنصر الثابت في Slide Master ليظهر على الشرائح المرتبطة به.",
"Which view displays the slides in a presentation as thumbnails?": "يعرض Slide Sorter الشرائح على شكل صور مصغرة، ويسمح بترتيبها بسهولة.",
"In which place can you search for images, texts, and other contents?": "نستخدم Search Engine، أي محرك البحث، للبحث عن الصور والنصوص والمحتوى على الإنترنت.",
"Which of the following options is a characteristic of cloud computing?": "تتيح الحوسبة السحابية الوصول إلى البيانات من أماكن وأجهزة مختلفة عبر الإنترنت.",
"What is Phishing?": "التصيد الاحتيالي Phishing محاولة خداع المستخدم للحصول على معلوماته أو بيانات تسجيل الدخول؛ والإجابة المحددة في السؤال هي Data breach.",
"Which of the following options is considered an internet browser?": "الإجابة المحددة هي MS Explorer، والمقصود غالباً Internet Explorer، وهو متصفح ويب.",
"Which of the field has width 8 bytes?": "وفق مفتاح الإجابة في السؤال، النوع المحدد هو DateTime.",
"When saving a file in Excel 2019, what name is given to the file?": "يُسمّى ملف Excel مصنفاً Workbook، ويكون الاسم الافتراضي عادةً Book1.",
"What should you do if you receive an unwanted email?": "نضع علامة Spam على الرسالة غير المرغوب فيها، ولا نضغط على روابطها المشبوهة.",
"What is the best password you can use to protect your account?": "من الخيارات المعطاة، ali@17&ah0 هي الأقوى لأنها تجمع الأحرف والأرقام والرموز.",
"When replying to an email, what can happen to the message?": "يمكن الرد على المرسل وحده باستخدام Reply أو الرد على جميع المستلمين باستخدام Reply All.",
"What is the tool through which photos and documents can be sent via telephone lines without needing a computer?": "Fax جهاز يرسل المستندات والصور عبر خطوط الهاتف دون الحاجة إلى حاسوب.",
"What is the primary role of a firewall in network security?": "يعمل Firewall على منع الاتصالات والوصول غير المصرح به إلى الشبكة.",
"How can you change the desktop background in Windows?": "يمكن تغيير خلفية سطح المكتب من Settings ثم Personalization ثم Background.",
"What technology uses invisible computer devices to enable the purchase of credit or debit cards?": "وفق الإجابة المحددة في السؤال، الخيار هو Magnetic stripe reading، أي قراءة الشريط المغناطيسي للبطاقة.",
"If you select a range of cells and want to make the previous cell active, what do you press?": "الاختصار Shift + Tab ينقل التحديد إلى الخلية السابقة.",
"In Microsoft Excel, a pie chart is used for:": "يُستخدم المخطط الدائري Pie Chart لعرض مساهمة كل قيمة كنسبة من المجموع الكلي.",
"How do you navigate between cells in Microsoft Excel?": "وفق الإجابة المحددة، يُستخدم Tab للانتقال بين الخلايا.",
"When applying mathematical functions in programs like Excel, the function must start with which symbol?": "تبدأ الصيغ والدوال في Excel بعلامة يساوي =.",
"How can you change the column width to 30 cm in Microsoft Excel?": "نحدد العمود ثم نختار Format > Column Width ونحدد العرض؛ ملاحظة: Excel يستخدم وحدة عرض خاصة بالأعمدة، وليس السنتيمتر مباشرةً في هذا الأمر.",
"What does A15 represent in Microsoft Excel?": "A15 هي الخلية الواقعة في العمود A والصف 15.",
"What is the shape of the fill handle (fill pointer) that transfers cell contents in Microsoft Excel?": "مقبض التعبئة Fill Handle هو مربع صغير عند زاوية الخلية المحددة، ويتحول مؤشر الماوس عنده عادةً إلى علامة زائد سوداء رفيعة.",
"What is the shortcut that helps to copy the content or formula of a cell into the cell below it in Microsoft Excel?": "Ctrl + D ينسخ محتوى أو صيغة الخلية العلوية إلى الخلايا المحددة أسفلها.",
"What action is used to merge and center cells in Microsoft Excel?": "نحدد الخلايا ثم نضغط Merge & Center من تبويب Home لدمجها وتوسيط المحتوى.",
"How can a border be removed in Microsoft Excel?": "يمكن إزالة الحدود من Format Cells ثم Borders واختيار No Border.",
"How can a worksheet be inserted in Microsoft Excel?": "نفتح Home ثم Insert ونختار Insert Sheet لإضافة ورقة عمل جديدة.",
"Where can a hyperlink be inserted in Microsoft Word?": "نفتح تبويب Insert ثم نختار Hyperlink لإضافة رابط تشعبي.",
"Where can you insert WordArt in Microsoft Word?": "نفتح تبويب Insert ثم نختار WordArt لإدراج نص زخرفي.",
"What is the shortcut for opening the Font formatting dialog box in Microsoft Word?": "الاختصار Ctrl + D يفتح مربع حوار Font في Word.",
"What page size dimensions does document layout allow in Microsoft Word?": "يمكن تخصيص أبعاد الصفحة في Word حسب حاجة المستخدم من Layout ثم Size ثم More Paper Sizes.",
"What is the number of slides that cannot be printed on one page?": "وفق الإجابة المحددة في السؤال، الخيار هو 5 slides per page.",
"Animated images (animations) can be applied to:": "يمكن تطبيق الحركات على جميع الشرائح أو شريحة محددة أو الشريحة الحالية وفق نوع الحركة والإعدادات؛ والإجابة المحددة هي All of the above.",
"If you want to print only slide 12 and slide 5, what should you choose?": "نختار Slides ضمن إعدادات الطباعة، ثم نكتب أرقام الشرائح المطلوبة، مثل 12,5.",
"How many Slide Layouts are in Microsoft PowerPoint?": "وفق مفتاح الإجابة في هذا البنك، الخيار هو None of above؛ إذ يختلف عدد التخطيطات حسب إصدار PowerPoint والقالب.",
"What does Outline View mean in Microsoft PowerPoint?": "يعرض Outline View النصوص والعناوين الرئيسية للشرائح في شكل مخطط نصي.",
"What does View Handout mean in Microsoft PowerPoint?": "يعرض Handout طريقة ترتيب الشرائح على صفحات مخصصة للطباعة والتوزيع على الحضور.",
"The way computers recognize and communicate with each other on the Internet:": "عنوان IP يُستخدم للتعرّف على الأجهزة وتحديدها ضمن الشبكة؛ والإجابة المحددة هي IP.",
"What is the difference between the web and the Internet?": "الإنترنت هو الشبكة العالمية التي تربط الأجهزة، أما الويب فهو خدمة تعمل عبر الإنترنت وتعرض صفحات ومحتوى باستخدام بروتوكولات مثل HTTP.",
"What is the benefit of a digital certificate?": "تساعد الشهادة الرقمية على التحقق من هوية الموقع أو الجهة وتعزيز أمان الاتصال.",
"What is the Internet?": "الإنترنت شبكة عالمية تربط الحواسيب والأجهزة لتبادل البيانات والمعلومات.",
"What application is used to browse websites?": "يُستخدم متصفح الويب Browser لفتح المواقع وعرض صفحاتها.",
"When working on cloud documents such as Google Docs, which feature allows multiple users to work on the document in real time?": "تتيح ميزة Real-time collaboration لعدة مستخدمين تعديل المستند نفسه في الوقت الفعلي.",
"What is the shortcut used to show the help menu?": "المفتاح F1 يُستخدم عادةً لفتح قائمة المساعدة Help.",
"Where is it preferable to save your files and folders in the operating system?": "وفق مفتاح الإجابة في السؤال، الخيار هو My Folder.",
"Where do we find active windows in Windows?": "تظهر التطبيقات والنوافذ المفتوحة على شريط المهام Taskbar.",
"Where are files downloaded from the Internet stored on the computer?": "تُحفظ الملفات المنزّلة عادةً في مجلد Downloads.",
"What is the shortcut for Select All in most programs?": "الاختصار Ctrl + A يُستخدم لتحديد جميع العناصر أو النصوص في معظم البرامج.",
"How do we close a workbook in Microsoft Excel?": "وفق مفتاح الإجابة، نستخدم زر Close في شريط عنوان النافذة لإغلاق المصنف.",
"Which of the following options is NOT considered a database?": "وفق مفتاح الإجابة، الخيار هو Relationship؛ فهي علاقة تربط الجداول وليست قاعدة بيانات بحد ذاتها.",
"What should you do if you receive an unwanted email?": "نضع علامة Spam على الرسالة غير المرغوب فيها، ونتجنب فتح الروابط أو المرفقات المشبوهة.",
"What is the primary protocol used to secure data transmission over the internet?": "HTTPS يضيف طبقة حماية للاتصال بين المتصفح والموقع؛ والإجابة المحددة هي HTTPS.",
"What is the primary protocol used to transfer web data across the internet?": "HTTP هو بروتوكول نقل صفحات وبيانات الويب؛ والإجابة المحددة هي HTTP.",
"What is the method by which computers recognize each other on the Internet network?": "عنوان IP يساعد على تحديد الأجهزة وواجهاتها ضمن الشبكة.",
"Uploading pages and files from the computer to the Internet": "Upload تعني رفع الملفات من الحاسوب إلى الإنترنت أو إلى خادم بعيد.",
"Downloading data and files from the Internet to the computer": "Download تعني تنزيل البيانات والملفات من الإنترنت إلى الحاسوب.",
"What is the Internet?": "الإنترنت شبكة عالمية تربط الأجهزة وتتيح تبادل المعلومات؛ والإجابة المحددة هي الخيار D.",
"The difference between the Web and the Internet": "الإنترنت هو البنية الشبكية العالمية، أما الويب فهو إحدى الخدمات التي تعمل عبرها. ملاحظة: خيارات هذا السؤال لا تصوغ الفرق بدقة.",
"What is WWW?": "WWW اختصار لـ World Wide Web، أي الشبكة العالمية للويب.",
"What is the address of a web page on the internet?": "URL هو عنوان الصفحة أو المورد على الإنترنت.",
"Which of the following represents a social networking site?": "Facebook موقع للتواصل الاجتماعي؛ والإجابة المحددة هي Facebook.",
"Which command is used in a web browser for quick navigation / saving favorite pages?": "Bookmarks تُستخدم لحفظ الصفحات المفضلة والعودة إليها بسرعة.",
"What does HTML stand for?": "HTML اختصار لـ HyperText Markup Language، وهي لغة ترميز صفحات الويب.",
"What application is used to browse websites?": "Browser هو البرنامج المستخدم لفتح المواقع وتصفح صفحات الويب.",
"What is the benefit of cloud storage?": "يتيح التخزين السحابي الوصول إلى الملفات من أجهزة مختلفة ومن أماكن متعددة عبر الإنترنت.",
"For web browsing, the best option is:": "وفق مفتاح الإجابة في السؤال، الخيار هو Google Chrome.",
"Which of the following options is a characteristic of cloud computing?": "من خصائص الحوسبة السحابية إمكانية الوصول إلى البيانات من أماكن مختلفة عبر الإنترنت.",
"What does HTTPS represent?": "HTTPS هو إصدار آمن من HTTP يستخدم التشفير لحماية الاتصال بين المتصفح والموقع.",
"What is ISP stand for?": "ISP اختصار لـ Internet Service Provider، أي مزوّد خدمة الإنترنت.",
"Which of the pointers indicates that you can select cells in Excel?": "المؤشر الأبيض الكبير على شكل علامة زائد يُستخدم لتحديد الخلايا في Excel.",
"Cell pointer indicating that you can fill the series": "وفق مفتاح الإجابة، الخيار هو Thin plus icon، أي علامة زائد رفيعة تظهر عند مقبض التعبئة.",
"Cell pointer indicating that you can move content to another cell": "وفق مفتاح الإجابة، المؤشر المقصود هو المؤشر الذي يظهر عند حافة الخلية ويتيح سحب محتواها إلى مكان آخر.",
"In Excel every formula or function operation must be preceded by:": "تبدأ كل صيغة أو دالة في Excel بعلامة يساوي =.",
"The first cell in an Excel worksheet is called": "أول خلية في ورقة Excel هي A1، عند تقاطع العمود A مع الصف 1.",
"The first cell in an Excel worksheet is called": "أول خلية في ورقة Excel هي A1، وتقع عند تقاطع العمود A مع الصف 1.",
"What does A16 mean?": "A16 تعني الخلية الموجودة في العمود A والصف 16.",
    "In Excel which of the following can be used to navigate between cells?": "يمكن التنقل بين خلايا Excel باستخدام Enter وTab ومفاتيح الأسهم؛ لذلك الإجابة All of above.",
"Excel file extension": "امتداد ملفات Excel الحديثة هو .xlsx، أما .xls فيُستخدم مع الإصدارات الأقدم.",
"Where is the Formula Bar located in Excel?": "يوجد Formula Bar أعلى ورقة العمل، بجانب شريط الأدوات، ويعرض محتوى الخلية المحددة أو صيغتها.",
"How can you hide and show a row or a column in a worksheet?": "لإخفاء صف أو عمود، نحدده ثم نضغط بزر الفأرة الأيمن ونختار Hide. ولإظهاره مجدداً نختار Unhide.",
"How do we change the column width in Excel?": "نحدد العمود ثم نختار Home > Format > Column Width لتحديد عرضه، أو ننقر نقراً مزدوجاً على حد العمود لضبطه تلقائياً.",
"What is the function of the MIN function in Excel?": "الدالة MIN تُرجع أصغر قيمة ضمن مجموعة من الأرقام.",
"What is the average of (2, 5, 1, 4) in Excel?": "المعدل الحسابي هو مجموع الأرقام مقسوماً على عددها: (2 + 5 + 1 + 4) ÷ 4 = 3.",
"How can you merge and center cells in Excel?": "نحدد الخلايا المطلوبة ثم نختار Merge & Center من تبويب Home لدمجها وتوسيط المحتوى.",
"What happens when you change a cell's content in Excel?": "تتحدث الصيغ المرتبطة بالخلية تلقائياً عند تغيير محتواها، إذا كانت تعتمد على تلك الخلية.",
"Where is the ruler located in an Excel worksheet?": "وفق الإجابة المحددة في السؤال، يمكن الوصول إلى إعدادات إظهار المسطرة من تبويب View.",
"How do you add comments in Excel?": "نحدد الخلية ثم نفتح تبويب Review ونختار Add Comment أو New Comment حسب إصدار Excel.",
"To split a worksheet in Excel, what do we do?": "نفتح تبويب View ثم نختار Split لتقسيم نافذة ورقة العمل إلى أجزاء.",
"To delete the third worksheet in Excel:": "نحدد تبويب ورقة العمل الثالثة، ثم نضغط بزر الفأرة الأيمن ونختار Delete.",
"To freeze or lock the first row in Excel, we choose:": "نفتح View > Freeze Panes > Freeze Top Row لتثبيت الصف الأول أثناء التمرير.",
"To resume writing/editing inside an Excel cell, we press:": "المفتاح F2 يسمح بتحرير محتوى الخلية المحددة مباشرةً.",
"Which of the following options is used to clear data (cell content) without deleting the cell itself?": "يُستخدم Clear Contents لمسح محتوى الخلية مع إبقاء الخلية نفسها وموقعها.",
"How can you change the column width to 30 cm in Microsoft Excel?": "وفق مفتاح الإجابة، نختار Format ثم Column Width. ملاحظة: Excel يحدد عرض الأعمدة بوحدة خاصة، وليس بالسنتيمتر مباشرةً من هذا الأمر.",
"What is the function used to find the highest value in Excel?": "تُستخدم الدالة MAX لإيجاد أكبر قيمة ضمن مجموعة من الأرقام.",
"When applying mathematical functions in programs like Excel, the function must start with which symbol?": "تبدأ الصيغ والدوال في Excel بعلامة يساوي (=).",
"What is the shape of the fill handle (fill pointer) that transfers cell contents in Microsoft Excel?": "مقبض التعبئة Fill Handle هو مربع صغير عند زاوية الخلية المحددة، ويتحول المؤشر عنده عادةً إلى علامة زائد صغيرة.",
"What is the shortcut that helps to copy the content or formula of a cell into the cell below it in Microsoft Excel?": "الاختصار Ctrl + D ينسخ محتوى أو صيغة الخلية العلوية إلى الخلايا المحددة أسفلها.",
"Where can a hyperlink be inserted in Microsoft Word?": "نفتح تبويب Insert ثم نختار Hyperlink لإدراج رابط تشعبي.",
"What is the shortcut for opening the Font formatting dialog box in Microsoft Word?": "الاختصار Ctrl + D يفتح مربع حوار Font لتغيير نوع الخط وحجمه وتنسيقه.",
"In which tab is the Spell Check located?": "يوجد التدقيق الإملائي Spell Check ضمن تبويب Review في Word.",
"Where are your documents reviewed?": "حسب الإجابة المحددة في السؤال، الخيار هو Page Layout؛ لكن أدوات المراجعة والتدقيق توجد عادةً في Review.",
"What is the purpose of the ruler in Office?": "تُستخدم المسطرة Ruler لضبط الهوامش والمسافات والمسافات البادئة ومحاذاة العناصر.",
"How is the current page closed?": "وفق الإجابة المحددة، نختار File > Close لإغلاق الملف الحالي دون إغلاق البرنامج بالكامل.",
"How can you insert an image in Excel or PowerPoint?": "نفتح تبويب Insert ثم نختار Pictures لإدراج صورة.",
"What page size dimensions does document layout allow in Microsoft Word?": "يمكن تخصيص أبعاد الصفحة في Word حسب الحاجة من Layout > Size > More Paper Sizes.",
"What is the command used to bold text in Microsoft Office programs?": "الاختصار Ctrl + B يجعل النص عريضاً Bold.",
"What is the shortcut Ctrl + S?": "الاختصار Ctrl + S يُستخدم لحفظ الملف الحالي.",
"What is the PowerPoint template file extension?": "امتداد ملفات قوالب PowerPoint الحديثة هو .potx.",
"What is the shortcut for text replacement (Find and Replace) in presentations?": "الاختصار Ctrl + H يفتح نافذة Find and Replace لاستبدال النصوص.",
"What is the number of slides that cannot be printed on one page?": "وفق مفتاح الإجابة في السؤال، الخيار المحدد هو 5 slides per page.",
"Animated images (animations) can be applied to:": "وفق الإجابة المحددة، يمكن تطبيق الحركات على جميع الشرائح أو شريحة معينة أو الشريحة الحالية؛ لذلك الإجابة All of the above.",
"If you want to print only slide 12 and slide 5, what should you choose?": "نختار Slides ضمن إعدادات الطباعة ثم نكتب أرقام الشرائح المطلوبة، مثل 12,5.",
"How many Slide Layouts are in Microsoft PowerPoint?": "وفق مفتاح الإجابة في هذا البنك، الخيار هو None of above؛ إذ يختلف عدد التخطيطات بحسب إصدار PowerPoint والقالب.",
"What does Outline View mean in Microsoft PowerPoint?": "يعرض Outline View عناوين الشرائح والنصوص الرئيسية على شكل مخطط نصي.",
"What does View Handout mean in Microsoft PowerPoint?": "يتيح Handout عرض الشرائح مرتبة على صفحات مخصصة للطباعة والتوزيع على الحضور.",
"Where is a background inserted for a presentation?": "نفتح تبويب Design ثم نختار Format Background لتغيير خلفية العرض.",
"Where is it preferable to save your files and folders in the operating system?": "وفق مفتاح الإجابة، الخيار هو My Folder.",
"Where do we find active windows in the Windows operating system?": "تظهر البرامج والنوافذ المفتوحة عادةً على شريط المهام Taskbar.",
"Where are files saved?": "تُحفظ الملفات داخل مجلد يختاره المستخدم، مثل Documents أو مجلد آخر على القرص.",
"Where can you find the Recycle Bin in the Windows operating system?": "توجد أيقونة Recycle Bin عادةً على سطح المكتب Desktop.",
"Where is the taskbar located?": "يوجد شريط المهام Taskbar عادةً أسفل الشاشة في إعدادات Windows الافتراضية.",
"What is the shortcut used to show the help menu?": "المفتاح F1 يُستخدم عادةً لفتح نافذة المساعدة Help.",
"What is the shortcut for Select All?": "الاختصار Ctrl + A يُستخدم لتحديد جميع العناصر أو النصوص.",
"Shortcut to save a file": "الاختصار Ctrl + S يُستخدم لحفظ الملف.",
"What is the shortcut Ctrl + X?": "الاختصار Ctrl + X يقص النص أو الملف المحدد ويضعه مؤقتاً في Clipboard.",
"Which language is used to create or modify database structure, such as tables and keys?": "DDL اختصار Data Definition Language، وتُستخدم لإنشاء بنية قاعدة البيانات أو تعديلها، مثل الجداول والمفاتيح.",
"Which language is used to manage permissions and privileges in a database?": "DCL اختصار Data Control Language، وتُستخدم لإدارة صلاحيات الوصول إلى قاعدة البيانات.",
"Which language is used to interact with data inside tables, such as inserting, modifying, or deleting data?": "DML اختصار Data Manipulation Language، وتُستخدم لإضافة البيانات وتعديلها وحذفها داخل الجداول.",
"Which of the following options is NOT considered a database?": "وفق مفتاح الإجابة، الخيار هو Relationship؛ فهي علاقة تربط الجداول وليست قاعدة بيانات مستقلة.",
"Which device has a large internal storage capacity?": "وفق الإجابة المحددة في السؤال، الخيار هو Server، إذ يُستخدم الخادم لتقديم الخدمات وتخزين البيانات للمستخدمين والأجهزة.",
"What should you do if you receive an unwanted email?": "نضع علامة Spam على الرسالة غير المرغوب فيها، ونتجنب فتح الروابط أو المرفقات المشبوهة.",
"If we want to save an incoming email so we can easily return to it later, what is the correct option?": "وفق الإجابة المحددة، نستخدم Star لتمييز الرسالة والرجوع إليها بسهولة لاحقاً.",
"The difference between the Inbox and Spam mail": "Inbox يحتوي على الرسائل الواردة، بينما Spam يحتوي عادةً على الرسائل غير المرغوب فيها أو المشبوهة.",
"Sending messages to a single person is considered": "تُسمّى الرسالة المرسلة إلى شخص واحد Individual message، أي رسالة فردية.",
"What is a search engine?": "محرك البحث أداة تساعد على العثور على صفحات الويب والصور والفيديوهات والنصوص عبر الإنترنت.",
"What do you need when connecting to the internet?": "وفق مفتاح الإجابة، الخيار هو Router، وهو جهاز يربط الأجهزة بالشبكة ويوجه حركة البيانات.",
"What is a hyperlink?": "Hyperlink رابط ينقل المستخدم إلى صفحة أو موقع أو مورد آخر عند النقر عليه.",
"How can a user's identity be known when logging onto the network?": "يُستخدم Username للتعرّف على حساب المستخدم عند تسجيل الدخول إلى الشبكة.",
"Where do files that you download go on your device?": "تُحفظ الملفات التي تنزّلها عادةً في مجلد Downloads، ويمكن تغيير موقع الحفظ من إعدادات المتصفح.",
"What does the appearance of a lock next to the page address mean?": "يشير رمز القفل عادةً إلى أن الاتصال بالموقع يستخدم HTTPS لتشفير البيانات المتبادلة.",
"What is WAN in computer networks?": "WAN اختصار Wide Area Network، أي شبكة واسعة النطاق تربط أجهزة أو شبكات عبر مسافات جغرافية كبيرة.",
"What is the benefit of cloud storage?": "يتيح التخزين السحابي الوصول إلى الملفات من أجهزة مختلفة ومن أماكن متعددة عبر الإنترنت.",
"What is ISP stand for?": "ISP اختصار Internet Service Provider، أي مزوّد خدمة الإنترنت.",
"What does HTTPS represent?": "HTTPS هو إصدار آمن من HTTP يستخدم التشفير لحماية الاتصال بين المتصفح والموقع.",
"What is the Internet?": "الإنترنت شبكة عالمية تربط الحواسيب والأجهزة لتبادل المعلومات والبيانات.",
"What is the shape of the mouse pointer when using autofill for a cell in Excel?": "يتحول مؤشر الماوس عند مقبض التعبئة إلى علامة زائد صغيرة تُستخدم لسحب البيانات أو إكمال السلاسل.",
"How do you move vertically in Excel?": "وفق مفتاح الإجابة، يُستخدم Enter للانتقال إلى الخلية التالية عمودياً بحسب اتجاه الحركة وإعدادات Excel.",
"What does the Find and Replace box contain?": "تتضمن نافذة Find and Replace خيارات مثل Find وReplace وGo To؛ لذلك الإجابة All of above.",
"What does the command Edit >> Delete Comment mean?": "يعني الأمر Delete Comment حذف التعليق المرتبط بالخلية، وليس حذف محتوى الخلية نفسها.",
"What is located to the left of the formula bar in Excel?": "يوجد Name Box إلى يسار شريط الصيغة، ويعرض عنوان الخلية أو اسم النطاق المحدد.",
"What is the maximum character limit for text in a cell in Excel?": "الحد الأقصى لمحتوى الخلية في Excel هو 32,767 حرفاً؛ أما 255 فيرتبط ببعض القيود القديمة أو خصائص أخرى.",
"How can you insert margins in Excel?": "نفتح تبويب Page Layout ثم Margins لاختيار الهوامش المناسبة للصفحة المطبوعة.",
"What is the correct method to hide a column in Excel?": "نحدد العمود ثم نضغط بزر الفأرة الأيمن ونختار Hide.",
"What is the minimum column width in Excel?": "يمكن جعل عرض العمود في Excel صفراً لإخفائه؛ لذلك لا تمثل الخيارات الرقمية المذكورة الحد الأدنى الفعلي بصورة صحيحة.",
"Which of the following series types is invalid in the Excel Series dialog box?": "وفق مفتاح الإجابة، الخيار هو Time؛ مع ملاحظة أن Excel يدعم تعبئة سلاسل التواريخ ضمن خيارات Series.",
"How can you delete the third worksheet in Excel if you only need two sheets?": "وفق مفتاح الإجابة، الخيار هو A, B؛ أي إن حذف الورقة ممكن بالطريقة المذكورة في الخيار الأول.",
"How can you display sheet headings (headings/gridlines) in Excel?": "نفتح تبويب View ونفعّل Headings أو Gridlines بحسب العنصر المطلوب إظهاره.",
"How can you change the column width in Excel?": "نحدد العمود ثم نختار Home > Format > Column Width ونكتب العرض المطلوب.",
"How can you merge and center cells in Excel?": "نحدد الخلايا ثم نضغط Merge & Center من مجموعة Alignment في تبويب Home.",
"What is the maximum zoom limit in Microsoft Word?": "الحد الأقصى للتكبير في Word هو 500% وفق الخيارات المحددة في السؤال.",
"If there is more than one hyperlink in a Word document, how can you follow them?": "يمكن الانتقال بين الروابط باستخدام Tab ثم الضغط على Enter، أو فتح الرابط في Word باستخدام Ctrl مع النقر عليه؛ لذلك الإجابة A, B.",
"What is the shortcut used to find and replace text in Microsoft Word?": "الاختصار Ctrl + H يفتح نافذة Find and Replace.",
"Where can you insert a hyperlink?": "نفتح Insert ثم Hyperlink لإضافة رابط إلى نص أو عنصر محدد.",
"What is the purpose of the ruler in Office?": "تُستخدم المسطرة لضبط الهوامش والمسافات البادئة ومحاذاة العناصر.",
"How is the current page closed?": "وفق الإجابة المحددة، نختار File > Close لإغلاق المستند الحالي.",
"What is the default slide orientation in PowerPoint?": "الاتجاه الافتراضي للشرائح في PowerPoint هو Landscape، أي أفقي.",
"Where can you insert a background in PowerPoint?": "نفتح Design ثم Format Background لتغيير خلفية الشرائح.",
"What is the feature added to slides during a slide show?": "Transition هو تأثير الانتقال الذي يظهر عند الانتقال من شريحة إلى أخرى.",
"What are the physical components of a computer?": "تُسمّى المكونات المادية للحاسوب Hardware، وتشمل الأجزاء التي يمكن لمسها مثل الشاشة ولوحة المفاتيح.",
"Which of these devices is considered a resource-sharing device?": "Server خادم يتيح مشاركة الموارد مثل الملفات والطابعات والخدمات بين أجهزة الشبكة.",
"What is WAN in computer networks?": "WAN هي شبكة واسعة النطاق تربط شبكات أو أجهزة عبر مسافات جغرافية كبيرة.",
"If messages are stored in the Spam folder in your email, it means they are:": "تعني الرسائل الموجودة في Spam أنها غالباً إعلانات غير مرغوب فيها أو رسائل مزعجة.",
"If we want to save an incoming email so we can easily return to it later, what is the correct option?": "الخيار Star يضع نجمة على الرسالة حتى تتمكن من العثور عليها والرجوع إليها بسهولة لاحقاً.",
"Sending messages to a single person is considered:": "تُسمّى الرسالة المرسلة إلى شخص واحد Individual message، أي رسالة فردية.",
"Which language is used to create or modify database structure, such as tables and keys?": "DDL اختصار Data Definition Language، وتُستخدم لإنشاء بنية قاعدة البيانات أو تعديلها، مثل الجداول والمفاتيح.",
"Which language is used to manage permissions and privileges in a database?": "DCL اختصار Data Control Language، وتُستخدم لإدارة صلاحيات الوصول إلى قاعدة البيانات.",
"Which language is used to interact with data inside tables, such as inserting, modifying, or deleting data?": "DML اختصار Data Manipulation Language، وتُستخدم لإضافة البيانات وتعديلها وحذفها داخل الجداول.",
"Long text can be divided into multiple lines within a cell. You can do this through:": "يُستخدم Wrap Text لعرض النص الطويل على عدة أسطر داخل الخلية بدلاً من امتداده أفقياً.",
"You can automatically adjust column width by:": "لضبط عرض العمود تلقائياً، ننقر نقراً مزدوجاً على الحد الأيمن لعنوان العمود.",
"Which of the following methods is incorrect for editing cell content?": "وفق مفتاح الإجابة، الضغط على Alt ليس الطريقة المحددة لتحرير محتوى الخلية؛ يمكن استخدام F2 أو النقر المزدوج أو شريط الصيغة.",
"Which of the following formats can you specify to apply or not apply in the AutoFormat dialog box?": "تتيح خيارات AutoFormat تحديد تطبيق تنسيقات مثل الأرقام والحدود والخطوط؛ لذلك الإجابة المحددة هي All of above.",
"Where can you change the automatic or manual calculation mode in Excel?": "نفتح File > Options > Formulas ثم Calculation options لتحديد الحساب التلقائي أو اليدوي.",
"An Excel worksheet consists of:": "تتكون ورقة العمل من صفوف وأعمدة، وينتج عن تقاطعهما خلايا؛ لذلك الإجابة Cells, columns, and rows.",
"How to split a worksheet?": "نفتح تبويب View ثم نختار Split لتقسيم نافذة ورقة العمل إلى أجزاء.",
"What is the function used to find the standard deviation?": "تُستخدم الدالة STDEV في السؤال لحساب الانحراف المعياري لمجموعة من القيم.",
"What is the function used to extract the minimum value in Excel?": "الدالة MIN تُرجع أصغر قيمة ضمن مجموعة الأرقام.",
"What is the maximum character limit for text in a cell in Excel?": "الحد الأقصى لمحتوى الخلية في Excel هو 32,767 حرفاً؛ أما 255 فهو الجواب المحدد في هذا السؤال.",
"From which option can you rotate text to 45 degrees in Excel?": "يمكن تدوير النص من تبويب Home ضمن مجموعة Alignment، باستخدام إعدادات اتجاه النص.",
"In the View menu, you can display:": "يتيح تبويب View إظهار عناصر مثل المسطرة وخطوط الشبكة؛ لذلك الإجابة المحددة هي All of above.",
"How can numbers entered in separate cells be converted into a set of ranks in Excel?": "وفق مفتاح الإجابة، الخيار المحدد هو Comma symbol؛ لكن الفاصلة لا تحوّل الأرقام إلى رتب فعلياً.",
"How can you delete the third worksheet in Excel if you only need two sheets?": "نضغط بزر الفأرة الأيمن على تبويب الورقة الثالثة ونختار Delete لحذفها.",
"What is the undo shortcut in Word?": "الاختصار Ctrl + Z يُلغي آخر إجراء تم تنفيذه في Word.",
"How can you insert a Layout?": "وفق مفتاح الإجابة في السؤال، الخيار المحدد هو From layout.",
"How can you insert a pie chart?": "وفق مفتاح الإجابة، الخيار هو None of above؛ عملياً يمكن إدراج المخطط الدائري من Insert ثم Chart.",
"What is the text replacement shortcut in Microsoft Word?": "الاختصار Ctrl + H يفتح نافذة Find and Replace لاستبدال النصوص.",
"To change the page orientation from portrait to landscape in Word:": "نفتح تبويب Layout ثم Page Orientation أو Orientation ونختار Landscape.",
"When pointing to a text box, what happens?": "عند تحديد مربع النص تظهر مقابض حول حدوده، ويمكن استخدامها لتغيير حجمه؛ والإجابة المحددة هي ظهور 8 مقابض.",
"You can edit an embedded organization chart object by:": "يمكن تحرير الكائن المضمّن بالنقر المزدوج عليه، أو بالنقر بزر الفأرة الأيمن واختيار أمر التحرير؛ لذلك الإجابة D.",
"Which of the following options provides a way to print distinctive notes with a thumbnail slide on the printed page?": "وفق مفتاح الإجابة، الخيار هو Audience Handout، أي نشرات تتضمن صوراً مصغرة للشرائح.",
"What is the default slide orientation in PowerPoint?": "الاتجاه الافتراضي لشرائح PowerPoint هو Landscape، أي أفقي.",
"Where can you insert a background in PowerPoint?": "نفتح تبويب Design ثم نختار Format Background لتغيير خلفية الشريحة.",
"What is the feature added to slides during a slide show?": "Transition هو تأثير الانتقال الذي يظهر عند الانتقال من شريحة إلى أخرى.",
"From which menu can you insert a picture, chart, and icon?": "نفتح تبويب Insert لإدراج الصور والمخططات والأيقونات.",
"What is a search engine?": "محرك البحث أداة تساعد على العثور على الصور والفيديوهات والنصوص وصفحات الويب.",
"What is the Internet?": "الإنترنت شبكة عالمية تربط الأجهزة وتتيح تبادل المعلومات والبيانات.",
"What is HTML?": "HTML اختصار HyperText Markup Language، وهي لغة ترميز تُستخدم لبناء صفحات الويب.",
"The language named ____ is used to describe the appearance of an image and web page text:": "وفق مفتاح الإجابة، الخيار هو HTML، وهي لغة ترميز صفحات الويب.",
"What is one of the features of e-learning?": "من مميزات التعلم الإلكتروني سهولة التعلم وسرعته وإمكانية الوصول إلى المواد التعليمية عن بُعد.",
"What is a hyperlink?": "Hyperlink رابط تشعبي ينقل المستخدم إلى صفحة ويب أو موقع أو مورد آخر عند النقر عليه.",
"What should you do if you enter a website that looks suspicious to you?": "أغلق الصفحة ولا تُدخل أي معلومات شخصية أو مالية إذا بدا الموقع مشبوهاً.",
"Which of the following options is used to store and download files on the internet?": "Google Drive خدمة تخزين سحابي تتيح حفظ الملفات وتنزيلها عبر الإنترنت.",
"Which of the following applications supports cloud storage?": "Dropbox خدمة تخزين سحابي تتيح حفظ الملفات والوصول إليها من أجهزة مختلفة.",
"Which of the following options is not considered a web browser?": "Microsoft Windows نظام تشغيل وليس متصفح ويب؛ لذلك هو الخيار الصحيح.",
"Where is the taskbar located?": "يوجد شريط المهام Taskbar عادةً أسفل شاشة Windows في الإعدادات الافتراضية.",
"Where do files that you download go on your device?": "تُحفظ الملفات المنزّلة عادةً في مجلد Downloads، ما لم يُحدَّد موقع آخر.",
"What is the name given to a document?": "وفق مفتاح الإجابة، الخيار هو Files.",
"What are the physical components of a computer?": "تُسمّى المكونات المادية للحاسوب Hardware، وتشمل الشاشة ولوحة المفاتيح والمعالج وغيرها.",
"Which of these devices is considered a resource-sharing device?": "الخادم Server يتيح مشاركة الموارد والخدمات، مثل الملفات والطابعات، بين أجهزة الشبكة.",
"Device that contains the largest internal storage:": "وفق مفتاح الإجابة، الخيار هو Server، أي الخادم.",
"Which of the following options is a cloud-based email program?": "وفق مفتاح الإجابة، الخيار هو All of above؛ إذ يمكن استخدام Gmail وYahoo وOutlook للبريد الإلكتروني عبر الإنترنت.",
"What are the email messages that you can schedule to send at a later time?": "تتيح ميزة Schedule جدولة رسالة بريد إلكتروني لإرسالها في وقت لاحق.",
"Which of the following applications sends messages via email?": "Outlook تطبيق لإدارة البريد الإلكتروني وإرسال الرسائل واستقبالها.",
"Which of the following options is not considered a database?": "وفق مفتاح الإجابة، الخيار هو Relationship؛ فهي علاقة بين الجداول وليست قاعدة بيانات مستقلة.",
"Q1/ What is the wide network that covers large geographical areas such as countries or continents?": "WAN اختصار Wide Area Network، وهي شبكة واسعة النطاق تغطي مناطق جغرافية كبيرة.",
"Q5/ The device used to convert analog signals into digital signals is": "وفق مفتاح الإجابة، الخيار هو Modem، وهو جهاز يُستخدم للاتصال ونقل البيانات عبر وسائط الاتصال.",
"Q6/ Device that contains the greatest internal storage": "وفق مفتاح الإجابة، الخيار هو Server؛ إذ يمكن للخوادم توفير سعات تخزين كبيرة.",
"1 Gigabyte is equal to": "وفق نظام القياس الثنائي الشائع في هذا النوع من الأسئلة، 1 GB يساوي 1024 MB.",
"SSD is faster than HDD due to": "يكون SSD أسرع عادةً لأنه لا يحتوي على أجزاء ميكانيكية متحركة مثل الأقراص الصلبة التقليدية HDD.",
"Which of the following are types of sound files?": "WAV صيغة ملف صوتي تُستخدم لتخزين الصوت الرقمي.",
"The .mp3 extension is for which type of file?": "الامتداد .mp3 يُستخدم للملفات الصوتية.",
"Long text can be divided into multiple lines within a cell. You can do this through:": "يُستخدم Wrap Text لتوزيع النص الطويل على عدة أسطر داخل الخلية.",
"You can automatically adjust column width by:": "ننقر نقراً مزدوجاً على الحد الأيمن لعنوان العمود لضبط عرضه تلقائياً وفق محتواه.",
"Which of the following methods is incorrect for editing cell content?": "وفق مفتاح الإجابة، الضغط على Alt ليس الطريقة المحددة لتحرير محتوى الخلية.",
"Which of the following formats can you specify to apply or not apply in the AutoFormat dialog box?": "تتيح نافذة AutoFormat تحديد تطبيق تنسيقات مثل الأرقام والحدود والخطوط؛ لذلك الإجابة All of above.",
"Where can you change the automatic or manual calculation mode in Excel?": "نفتح File > Options > Formulas ثم نحدد Calculation options لاختيار الحساب التلقائي أو اليدوي.",
"An Excel worksheet consists of:": "تتكون ورقة العمل من صفوف وأعمدة وخلايا.",
"How to split a worksheet?": "نستخدم View > Split لتقسيم نافذة ورقة العمل إلى أجزاء.",
"What is the function used to find the standard deviation in Excel?": "تُستخدم الدالة STDEV في السؤال لحساب الانحراف المعياري.",
"What is the function used to extract the minimum value in Excel?": "الدالة MIN تُرجع أصغر قيمة ضمن مجموعة من الأرقام.",
"Where can you hide a row in Excel?": "نحدد الصف ثم نفتح Home > Format > Hide & Unhide > Hide Rows.",
"What is the main purpose of using the Excel 2016 application?": "يُستخدم Excel لإجراء الحسابات والتحليلات الإحصائية وتنظيم البيانات.",
"When you gather data from a database to include it in a project within Excel, this process is called:": "تُسمّى العملية Data collection، أي جمع البيانات من مصادر مختلفة.",
"How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?": "نحدد الخلايا الثلاث ثم نختار Merge & Center من تبويب Home لدمجها في خلية واحدة.",
"Which function is used to find the median value in a range of numbers?": "الدالة MEDIAN تحسب القيمة الوسطى لمجموعة أرقام بعد ترتيبها.",
"How can numbers entered in separate cells be converted into a set of ranks in Excel?": "وفق مفتاح الإجابة، الخيار المحدد هو Comma symbol، لكن الفاصلة لا تحوّل الأرقام إلى رتب فعلياً.",
"What kind of error does a blue underline that appears below the text represent in MS Word?": "وفق مفتاح الإجابة، يشير الخط الأزرق إلى مشكلة تتعلق باتساق التنسيق أو التدقيق السياقي بحسب إصدار Word.",
"What is the text replacement shortcut in Microsoft Word?": "الاختصار Ctrl + H يفتح نافذة البحث والاستبدال.",
"To change the page orientation from portrait to landscape in Word:": "نفتح Layout ثم Orientation ونختار Landscape.",
"Which type of fonts are best suited for titles and headlines?": "وفق مفتاح الإجابة، الخيار هو Sans serif Fonts، وهي خطوط بلا زوائد وتناسب العناوين الواضحة.",
"Which tab is used to insert a table in Word 2016?": "نفتح تبويب Insert ثم نختار Table لإدراج جدول.",
"Where can you insert page numbers in a Microsoft Word document?": "نفتح Insert ثم نختار Page Number من مجموعة Header & Footer.",
"Which menu in Microsoft Word is used to show document information, such as the file name and date of work?": "نفتح قائمة File لعرض معلومات المستند وخصائصه.",
"Which of the following options is used to insert a text box?": "وفق مفتاح الإجابة، نختار Text Box من مجموعة Text.",
"Which of the following tabs in Microsoft Word is used to check for spelling and grammar errors?": "نفتح تبويب Review للوصول إلى أدوات التدقيق الإملائي والنحوي.",
"What is the shortcut used to undo an action in Word?": "الاختصار Ctrl + Z يُلغي آخر إجراء.",
"Which option allows you to select line, curve, freeform, or scribble tools?": "وفق مفتاح الإجابة، الخيار هو Draw custom path.",
"Which of the following options provides a way to print distinctive notes with a thumbnail slide on the printed page?": "وفق مفتاح الإجابة، الخيار هو Audience Handout.",
"Which of the following can you use to add times to the slides in a presentation?": "وفق مفتاح الإجابة، الخيار هو Microsoft Graph.",
"What is a slide-title master pair?": "وفق مفتاح الإجابة، المقصود هو Slide Master وTitle Master المرتبطان بقالب تصميم محدد.",
"If you have a presentation you created and want to send it by email to another teacher, you can add the show to your email message as a/an:": "نستخدم أيقونة المشبك Paperclip لإرفاق ملف العرض التقديمي برسالة البريد الإلكتروني.",
"How can you insert a pie chart?": "وفق مفتاح الإجابة، الخيار هو None of above؛ عملياً يُدرج المخطط الدائري من Insert ثم Chart.",
"Using the internet to download the latest version of a program is an example of:": "تنزيل أحدث إصدار من برنامج يُعد Software update، أي تحديثاً للبرنامج.",
"What does HTTPS represent?": "HTTPS هو إصدار آمن من HTTP يستخدم التشفير لحماية الاتصال بين المتصفح والموقع.",
"What is the Internet?": "الإنترنت شبكة عالمية تربط الأجهزة وتتيح تبادل المعلومات.",
"When the internet disconnects, how can a web page be opened without a connection?": "قد تسمح ذاكرة Cache بعرض نسخة محفوظة سابقاً من صفحة ويب دون اتصال بالإنترنت.",
"What is an internet search engine?": "محرك البحث برنامج يبحث في الإنترنت عن كلمات أو صور أو فيديوهات ومحتوى ذي صلة.",
"What is one of the features of e-learning?": "من مميزات التعلم الإلكتروني سهولة التعلم وسرعته وتوفير وقت وتكاليف التنقل.",
"What is Wi-Fi?": "Wi-Fi تقنية اتصال لاسلكي تتيح ربط الأجهزة بالشبكة دون كابل مباشر.",
"What cookie in web browsing?": "Cookie ملف نصي صغير يحفظه الموقع أو المتصفح لتخزين معلومات عن المستخدم أو الجلسة.",
"Which of the following options is used to store and download files on the internet?": "Google Drive خدمة سحابية تُستخدم لتخزين الملفات وتنزيلها ومشاركتها عبر الإنترنت.",
"What is the difference between the web and the Internet?": "الويب جزء من الإنترنت يستخدم بروتوكولات مثل HTTP لعرض المحتوى عبر المتصفحات؛ أما الإنترنت فهو الشبكة العالمية التي تعمل عليها خدمات متعددة.",
"Which folder contains installed applications by default?": "وفق مفتاح الإجابة، مجلد Program Files هو الموقع المعتاد لتثبيت كثير من تطبيقات Windows.",
"Which folder contains installed applications by default?": "المجلد Program Files هو الموقع الافتراضي المعتاد لتثبيت كثير من تطبيقات Windows.",
"What shortcut key is used to delete a file permanently in Windows?": "الاختصار Shift + Delete يحذف الملف مباشرةً دون نقله إلى سلة المحذوفات عادةً.",
"Desktop background is called:": "تُسمّى خلفية سطح المكتب Wallpaper.",
"Which key is responsible for refreshing?": "المفتاح F5 يُستخدم عادةً لتحديث الصفحة أو النافذة.",
"Which of the following shortcuts is used to open Windows Task Manager directly?": "الاختصار Ctrl + Shift + Esc يفتح مدير المهام Task Manager مباشرةً.",
"Which Windows tool is used to change or increase the display resolution?": "نستخدم Display Settings لتغيير دقة الشاشة في Windows.",
"Where can we see the file path?": "يظهر مسار الملف في شريط العنوان أو المسار داخل File Explorer.",
"What is the name given to the document?": "يُسمّى المستند المحفوظ على الحاسوب File، أي ملف.",
"What is the process of gathering data from a database to include it in an Excel project called?": "تُسمّى العملية Data collection، أي جمع البيانات من قاعدة البيانات لاستخدامها في مشروع Excel.",
"Which of the following options is a cloud-based email program?": "وفق الخيارات، الإجابة All of above؛ إذ يمكن استخدام Gmail وYahoo وOutlook عبر الإنترنت.",
"What are the email messages that you can schedule to send at a later time?": "تتيح ميزة Schedule جدولة الرسالة لإرسالها في وقت لاحق.",
"Which of the field has width 8 bytes?": "وفق مفتاح الإجابة، الخيار هو DataTime؛ وهو على الأرجح يقصد DateTime.",
"The number of rows in an Excel 2016 worksheet is": "يحتوي Excel 2016 على 1,048,576 صفاً في ورقة العمل.",
"The number of columns in an Excel 2019 worksheet is": "يحتوي Excel 2019 على 16,384 عموداً، من A إلى XFD.",
"How do you tilt the book at a 45 degree angle?": "وفق مفتاح الإجابة، الخيار D: جميع الإجابات المذكورة غير صحيحة. عملياً، يُدار النص من Home > Alignment > Orientation.",
"Where are the control buttons located in Microsoft Excel?": "توجد أزرار التصغير والتكبير والإغلاق في Title Bar، أي شريط العنوان.",
"What happens when you press Ctrl + X after selecting some cells in Excel?": "يُجهّز Ctrl + X الخلايا المحددة للقص ونقل محتواها إلى Clipboard.",
"Which function is used to calculate the standard deviation?": "الدالة STDEV تُستخدم لحساب الانحراف المعياري وفق صياغة السؤال.",
"The small black square in the lower right corner of an active cell or range represents": "يُسمّى Fill Handle، ويُستخدم لسحب البيانات أو الصيغ وإكمال السلاسل.",
"The first cell in the worksheet in Excel is": "أول خلية في ورقة العمل هي A1.",
"Among the components of the main screen of Excel": "وفق مفتاح الإجابة، الخيار هو Home, Inserts؛ والمقصود تبويبات الشريط الرئيسية.",
"To close the current workbook in use, click on the option in the menu": "وفق مفتاح الإجابة، نختار Close من قائمة Office في واجهة الإصدارات القديمة.",
"Which tool would you use to merge cells and center the content within the merged cell?": "نستخدم Merge & Center لدمج الخلايا وتوسيط المحتوى داخلها.",
"If you have three default worksheets in Excel, how would you delete the third sheet?": "نضغط بزر الفأرة الأيمن على تبويب الورقة الثالثة ونختار Delete.",
"What does the shortcut Ctrl + D do in Microsoft Excel?": "يُستخدم Ctrl + D لتعبئة الخلايا المحددة بمحتوى أو صيغة الخلية العلوية.",
"What is the shortcut to make selected text left alignment?": "الاختصار Ctrl + L لمحاذاة النص إلى اليسار.",
"Which view is considered the best and most precise for editing text in Microsoft Word?": "وفق مفتاح الإجابة، الخيار Draft View، وهو عرض المسودة.",
"The Save command is present under the": "وفق مفتاح الإجابة، يوجد أمر Save ضمن قائمة Office في الإصدارات القديمة من Word.",
"Which tab is used to perform spelling and grammar check in Microsoft Word?": "يوجد التدقيق الإملائي والنحوي ضمن تبويب Review.",
"How can you print a specific number of pages in Word?": "نفتح File ثم Print ونكتب أرقام الصفحات المطلوبة في خانة Pages.",
"Which of the following options allows you to select more than one slide in a presentation?": "نضغط باستمرار على Ctrl ثم ننقر على الشرائح المطلوب تحديدها.",
"Which option allows you to select line, curve, freeform, or scribble tools?": "يتيح Draw Custom Path رسم مسار مخصص باستخدام الخطوط أو المنحنيات أو الرسم الحر.",
"The Microsoft Clip Gallery allows you to": "تُستخدم Clip Gallery لإضافة صور Clip Art إلى شريحة أو أكثر.",
"Which of the following options provides a way to print distinguished notes with a thumbnail slide on the printed page?": "تُستخدم Handouts لطباعة صور مصغرة للشرائح على صفحات يمكن توزيعها على الحضور.",
"What is a slide-title master pair?": "وفق مفتاح الإجابة، هما Slide Master وTitle Master الخاصان بقالب تصميم معين.",
"What is the abbreviation for ISP?": "ISP اختصار Internet Service Provider، أي مزوّد خدمة الإنترنت.",
"Which tool enables a researcher to obtain references from the internet?": "وفق مفتاح الإجابة، الخيار Yahoo؛ وهو محرك بحث وخدمة إنترنت.",
"What primary function does a web browser perform?": "وظيفة المتصفح الأساسية عرض صفحات الويب والتنقل بينها.",
"If a website is not loading correctly, which action might help resolve the issue?": "يمكن تحديث الصفحة أو مسح ذاكرة المتصفح المؤقتة Cache.",
"What does the Lock icon appearing at the page mean?": "يشير رمز القفل عادةً إلى أن الاتصال بالموقع يستخدم HTTPS لتشفير البيانات المتبادلة.",
"Which of these options allows users to store and access files over the Internet?": "Google Drive خدمة تخزين سحابي تتيح حفظ الملفات والوصول إليها عبر الإنترنت.",
"What is an internet search engine?": "محرك البحث أداة تبحث في الإنترنت عن كلمات أو صور أو فيديوهات ومحتوى محدد.",
"Before you can perform any action on a file or folder, what must you do?": "يجب تحديد الملف أو المجلد أولاً قبل تنفيذ الإجراء المطلوب عليه.",
"Which of the following options is used to access a file from the computer store?": "وفق مفتاح الإجابة، الخيار Retrieve، أي استرجاع الملف أو الوصول إليه.",
"Which of the following options is a physical component of a computer?": "Hardware تعني المكونات المادية للحاسوب التي يمكن لمسها.",
"Which component of the CPU register holds the address of the next instruction?": "يحتفظ Program Counter بعنوان التعليمة التالية التي سيجري تنفيذها.",
"Which protocol is commonly used for sending email?": "SMTP هو البروتوكول الشائع لإرسال رسائل البريد الإلكتروني.",
"If you receive a message from a friend sent to a number of people and you want to respond to everyone, do you use the command": "نختار Reply to all للرد على المرسل وجميع المستلمين الآخرين.",
"TB means": "TB اختصار Terabyte، وهي وحدة لقياس سعة تخزين البيانات.",
"Can you set borders for a worksheet or page in Excel?": "وفق مفتاح الإجابة، الخيار D: لا يمكن تعيين حدود للصفحة بالطريقة المذكورة. يمكن مع ذلك تطبيق حدود على الخلايا باستخدام Format Cells > Border.",
"How to hide 49th grade from being visible?": "لإخفاء الصف المطلوب، نستخدم Format ثم Hide & Unhide ثم Hide Rows، بحسب واجهة Excel.",
"How can listed numbers in separated cells be converted to a set of ranks in Excel?": "وفق مفتاح الإجابة، الخيار هو رمز الفاصلة Comma Style؛ لكنه ينسّق الأرقام ولا يحوّلها فعلياً إلى رتب.",
"How to convert the number listed in a divided cell into a group of ranks in Microsoft Excel?": "وفق مفتاح الإجابة، الخيار هو النقر على رمز الفاصلة في تبويب Home؛ لكن هذا يغيّر تنسيق الأرقام فقط.",
"How can you always show row 1 when moving to pages?": "نفتح View ثم Freeze Panes ونختار Freeze Top Row لتثبيت الصف الأول أثناء التمرير.",
"Excel displays the current cell address in:": "يعرض Name Box عنوان الخلية المحددة بجانب شريط الصيغة.",
"The function considered a statistical function is:": "الدالة AVERAGE() تُستخدم لحساب المتوسط الحسابي، وتُعد من الدوال الإحصائية في Excel.",
"The cell pointer that helps in moving or copying content to other cells is:": "وفق مفتاح الإجابة، المؤشر المقصود هو المؤشر الذي يظهر عند حافة الخلية ويسمح بسحب محتواها.",
"On which part of the chart are the values entered in a data sheet displayed?": "وفق مفتاح الإجابة، الخيار هو Y-Axis، أي المحور الصادي.",
"A ______ consists of a set of rows and columns in Excel.": "Worksheet هي ورقة عمل تتكون من صفوف وأعمدة وخلايا.",
"When you modify a data value in an Excel worksheet that was used to create a chart, what happens to the chart?": "يتحدّث المخطط تلقائياً ليعكس القيمة الجديدة مع الاحتفاظ بنوعه وتنسيقه عادةً.",
"To make the text in the cell fit the border, we click the button:": "وفق مفتاح الإجابة، الخيار Format Autofit Column Width لضبط عرض العمود ليتناسب مع المحتوى.",
"To set the row height, press the button:": "نختار Home > Format > Row Height لتحديد ارتفاع الصف.",
"In MS Word, you can insert a footnote at the bottom of the page from:": "نفتح References ثم نختار Insert Footnote لإضافة حاشية أسفل الصفحة.",
"To go directly to a page in the document based on the page number, use:": "الاختصار Ctrl + G يفتح نافذة Go To للانتقال إلى صفحة محددة.",
"What types of numbers can be inserted in the Word application?": "يمكن استخدام الأرقام العربية أو الإنجليزية في مستند Word بحسب إعدادات اللغة.",
"Which view shows a structure of headings at different levels in MS Word?": "يعرض Outline View العناوين بمستوياتها المختلفة ضمن بنية المستند.",
"Which of the following allows you to select more than one slide in a presentation?": "نستخدم Ctrl + النقر على كل شريحة لتحديد عدة شرائح غير متجاورة.",
"What is the best way to create another copy of a slide?": "وفق مفتاح الإجابة، نختار Duplicate Slide من قائمة Insert في واجهات PowerPoint القديمة.",
"What is the term used when a Clip Art image changes the direction of faces?": "يُسمّى قلب اتجاه الصورة Flip.",
"The Microsoft Clip Gallery allows you to:": "تُستخدم Clip Gallery لإضافة صور Clip Art إلى الشرائح.",
"What is the process of transferring programs from the internet to a computer called?": "تُسمّى عملية نقل البرامج من الإنترنت إلى الحاسوب Downloading، أي التنزيل.",
"When the internet disconnects, how can a web page be opened without a connection?": "قد تسمح ذاكرة Cache بعرض نسخة محفوظة سابقاً من صفحة الويب دون اتصال.",
"What is the primary protocol used to secure data transmission over the internet?": "HTTPS يستخدم التشفير لحماية الاتصال بين المتصفح والموقع.",
"What should you do if you enter a website that seems suspicious?": "أغلق الصفحة ولا تُدخل بياناتك الشخصية أو المالية ولا تفتح الروابط المشبوهة.",
"The fastest internet network is:": "وفق الخيارات، الإجابة Fiber optic؛ إذ توفر الألياف الضوئية سرعات اتصال عالية.",
"Which unit displays visual output?": "الشاشة Monitor تعرض المخرجات المرئية من الحاسوب.",
"Where can you usually find a deleted file in Windows?": "توجد الملفات المحذوفة عادةً في Recycle Bin ويمكن استعادتها منها إذا لم تُحذف نهائياً.",
"Which of the following actions will create a new folder on a Windows desktop?": "نضغط بزر الفأرة الأيمن على سطح المكتب ثم New > Folder لإنشاء مجلد جديد.",
"When an image is selected, it displays which of the following?": "تظهر عادةً ثمانية مقابض لتغيير حجم الصورة، موزعة على الزوايا ومنتصف الأضلاع.",
"Recently opened files are stored in:": "وفق مفتاح الإجابة، الخيار File Explorer؛ ويمكن الوصول إلى الملفات الحديثة من قسم Home أو Recent بحسب إصدار Windows.",
"To set the size of desktop icons:": "نضغط بزر الفأرة الأيمن على سطح المكتب ثم View ونختار Large, Medium أو Small icons.",
"A computer consists of:": "يتكون الحاسوب من وحدة معالجة مركزية وذاكرة ووحدات إدخال وإخراج؛ لذلك الإجابة All of these.",
"Which component is described as physical parts?": "Hardware تعني الأجزاء المادية للحاسوب مثل المعالج والشاشة ولوحة المفاتيح.",
"Memory used to temporarily store data to improve access speed:": "Cache ذاكرة سريعة تخزن البيانات المستخدمة بكثرة لتسريع الوصول إليها.",
"How is an email set to be sent at a later time?": "نستخدم Schedule أو Schedule send لتحديد موعد إرسال الرسالة لاحقاً.",
"What is the primary definition of E-commerce?": "التجارة الإلكترونية هي شراء وبيع السلع والخدمات عبر الإنترنت.",
"CD-ROM means:": "CD-ROM اختصار Compact Disc Read-Only Memory، أي قرص مدمج للقراءة فقط.",
"A computer consists of:": "يتكون الحاسوب من أجزاء مادية Hardware وبرامج Software، إضافةً إلى البيانات والمستخدمين بحسب تصنيف السؤال.",
"What is Fiber optic?": "الألياف الضوئية Fiber Optic تنقل البيانات باستخدام نبضات الضوء، وتوفر سرعة عالية في الاتصال.",
"Which of the following ports is designed to connect a wide variety of peripheral devices to a computer?": "منفذ USB يُستخدم لتوصيل مجموعة متنوعة من الأجهزة الطرفية، مثل لوحة المفاتيح والفأرة والطابعات.",
"Which term describes the ability of a computer to perform multiple tasks?": "تُسمّى القدرة على تنفيذ عدة مهام Multitasking، أي تعدد المهام.",
"What is the meaning of Phishing?": "Phishing هو التصيد الاحتيالي، أي محاولة خداع المستخدم للحصول على كلمات المرور أو المعلومات الشخصية.",
"Memory used to temporarily store data to improve access speed:": "Cache Memory ذاكرة سريعة تخزن البيانات المستخدمة بكثرة لتسريع الوصول إليها.",
"Which tool will you use to join some cells and place the content at the middle of the joined cell?": "نستخدم Merge & Center لدمج الخلايا وتوسيط المحتوى داخل الخلية الناتجة.",
"Which option is used to unmerge cells?": "نحدد الخلية المدمجة ثم نختار Unmerge Cells من خيارات الدمج في Excel.",
"To calculate the number of failing students in a specific stage, which function is used?": "تُستخدم COUNTIF لعدّ الطلبة الذين تنطبق عليهم حالة الرسوب وفق شرط محدد.",
"How to convert columns to row in Excel?": "نستخدم Paste Special ثم Transpose لتحويل البيانات من عمود إلى صف.",
"Which command combination is used to move the content of a cell to another cell in Excel?": "نستخدم Ctrl + X لقص المحتوى، ثم نحدد الخلية الجديدة ونضغط Ctrl + V للصقه.",
"If values (18, 5, 6) are used with MAX, what is the result?": "الدالة MAX تُرجع أكبر قيمة من الأرقام 18 و5 و6، وهي 18.",
"Which of the following action removes a sheet from workbook?": "لحذف ورقة عمل، نضغط بزر الفأرة الأيمن على تبويبها ونختار Delete.",
"How can listed numbers in separated cells be converted to a set of ranks in Excel?": "وفق مفتاح الإجابة في السؤال، الخيار المحدد هو Comma symbol؛ لكن تنسيق الفاصلة لا يحوّل الأرقام فعلياً إلى رتب.",
"Where do you insert Symbols in Word?": "نفتح تبويب Insert ثم نختار Symbol لإدراج الرموز الخاصة.",
"How can you create a bulleted list in Word?": "نحدد الفقرات ثم نختار Bullets من مجموعة Paragraph في تبويب Home.",
"Which of the following is not a font style in MS Word?": "نراجع الخيارات لتحديد العنصر الذي لا يُعد نمط خط؛ الأنماط الشائعة تشمل Bold وItalic وUnderline.",
"To move the cursor page to page of document, which shortcut is used?": "يُستخدم Ctrl + Page Up أو Ctrl + Page Down للانتقال بين الصفحات أو المقاطع بحسب السياق.",
"Which of the following is not a part of Slide Design?": "يعتمد الجواب على الخيارات الموجودة في السؤال؛ فالتصميم يشمل عناصر المظهر، بينما الحركات والانتقالات لها أدوات مستقلة.",
"Which of the following pane is NOT available in Task Pane?": "تختلف أجزاء المهام المتاحة بحسب إصدار PowerPoint والميزة المستخدمة؛ يُحدَّد الجواب من الخيارات الواردة في السؤال.",
"To change font size of a selected slide title:": "نحدد عنوان الشريحة ثم نغيّر حجم الخط من مجموعة Font في تبويب Home.",
"Which key is used to open the Start Menu in Windows?": "مفتاح Windows يفتح قائمة Start في نظام Windows.",
"Which folder contains user documents?": "يُستخدم مجلد Documents لحفظ مستندات المستخدم عادةً.",
"Where do you usually find a deleted file in Windows?": "توجد الملفات المحذوفة عادةً في Recycle Bin، ويمكن استعادتها ما لم تُحذف نهائياً.",
"Which tool checks disk errors?": "تُستخدم أداة Error Checking أو CHKDSK لفحص أخطاء القرص وإصلاح بعض مشكلاته.",
"Which of the following options is the most efficient way to back up your data using cloud storage?": "يُعد رفع نسخة احتياطية إلى خدمة تخزين سحابي موثوقة وسيلة لحفظ البيانات وإمكانية استعادتها عند الحاجة.",
"What is an IP address used for?": "عنوان IP يُستخدم لتحديد الجهاز أو واجهة الشبكة والتواصل معه عبر الشبكة.",
"What is the process of transferring programs from the internet to a computer called?": "تُسمّى عملية نقل البرامج من الإنترنت إلى الحاسوب Downloading، أي التنزيل.",
"When the internet disconnects, how can a web page be opened without a connection?": "يمكن أحياناً فتح نسخة محفوظة سابقاً في ذاكرة Cache، إذا كانت الصفحة متاحة دون اتصال.",
"What should you do if you enter a website that seems suspicious?": "أغلق الموقع المشبوه ولا تدخل بياناتك الشخصية أو المالية ولا تنزّل ملفاته.",
"What is the primary protocol used to secure data transmission over the internet?": "HTTPS يستخدم التشفير لحماية البيانات المتبادلة بين المتصفح والموقع.",
"What is the fastest internet network?": "وفق خيارات السؤال، الألياف الضوئية Fiber Optic توفر عادةً سرعات اتصال عالية.",
"How is an email set to be sent at a later time?": "نستخدم Schedule Send أو Schedule لتحديد موعد إرسال الرسالة لاحقاً.",
"What program is responsible for email?": "يمكن استخدام برامج مثل Microsoft Outlook لإرسال رسائل البريد الإلكتروني واستقبالها.",
"CD-ROM means:": "CD-ROM اختصار Compact Disc Read-Only Memory، أي قرص مدمج للقراءة فقط.",
"Communication system that transfers data between the components of a computer is:": "ناقل البيانات Data Bus ينقل البيانات بين مكونات الحاسوب.",
"Which port is the most common port used to connect input and output devices to a computer?": "يُستخدم منفذ USB على نطاق واسع لتوصيل أجهزة الإدخال والإخراج بالحاسوب.",
"Which device converts signal digital to printed output?": "الطابعة Printer تحوّل البيانات الرقمية إلى مخرجات مطبوعة على الورق.",
"Which memory is built directly into the CPU?": "تحتوي وحدة المعالجة المركزية على سجلات Registers وذاكرة Cache داخلية سريعة لتخزين البيانات والتعليمات مؤقتاً.",
"Which of the following has the smallest memory capacity?": "يُحدد الجواب من سعات الخيارات الواردة؛ فالبت Bit هو أصغر وحدة لقياس البيانات.",
"Which device converts analog signals to digital signals and vice versa?": "المودم Modem يُستخدم لتعديل الإشارات وفك تعديلها أثناء نقل البيانات عبر بعض وسائط الاتصال.",
"Which type of software helps maintain a computer system?": "برامج النظام والصيانة Utility Software تساعد على إدارة الحاسوب وفحصه وتحسين أدائه.",
"Which of the following options is a physical component of a computer?": "المكوّن المادي Hardware هو جزء ملموس من الحاسوب، مثل الشاشة أو لوحة المفاتيح.",
"What is Fiber optic?": "الألياف الضوئية وسيلة نقل تعتمد على الضوء لإرسال البيانات بسرعة عالية عبر ألياف زجاجية أو بلاستيكية.",
"For more options or change settings in Microsoft Excel (Advanced Options):": "نفتح File ثم Options للوصول إلى الإعدادات المتقدمة وتغيير خيارات Excel.",
"Which option is used to unmerge cells?": "نحدد الخلية المدمجة ثم نستخدم Unmerge Cells لإلغاء الدمج.",
"To calculate the number of failing students in a specific stage, which of the following functions is used?": "تُستخدم COUNTIF لعدّ القيم التي تحقق شرط الرسوب، مثل الدرجات الأقل من حد النجاح.",
"How many worksheets can a workbook have?": "يمكن أن يحتوي مصنف Excel على عدد كبير من أوراق العمل، ويعتمد العدد العملي على الذاكرة المتاحة.",
"How to convert columns to row in Excel?": "ننسخ البيانات ثم نختار Paste Special > Transpose لتحويل العمود إلى صف.",
"Which command combination is used to move the content of a cell to another cell in Excel?": "نستخدم Ctrl + X للقص ثم Ctrl + V للصق المحتوى في الخلية الجديدة.",
"If values (18, 5, 6) are used with MAX, what is the result?": "أكبر قيمة بين 18 و5 و6 هي 18، وهي نتيجة الدالة MAX.",
"Which of the following action removes a sheet from workbook?": "نختار Delete من قائمة تبويب ورقة العمل لحذفها من المصنف.",
"In Excel, the column header consists of:": "تُعرَّف الأعمدة في Excel بحروف مثل A وB وC، وتمتد حتى XFD في الإصدارات الحديثة.",
"If the values (18, 5, 2, 6) are used with the MIN function in Excel, what is the result?": "الدالة MIN تُرجع أصغر قيمة؛ والنتيجة هنا هي 2.",
"Which use magnetic disk to store data?": "القرص الصلب HDD يخزن البيانات على أقراص مغناطيسية.",
    "Which function key is used in Microsoft Excel to update data and formulas?": "المفتاح F9 يعيد حساب الصيغ في Excel.",
"The Legend in Excel charts is:": "Legend هو مفتاح المخطط الذي يوضح معنى الألوان أو الرموز المستخدمة لتمييز سلاسل البيانات.",
"Where do you insert Symbols in Word?": "نفتح Insert ثم Symbol لاختيار رمز خاص وإدراجه في المستند.",
"Which of the following is used to insert a date and time in a Word document?": "نفتح Insert ثم Date & Time لإدراج التاريخ والوقت.",
"What are the advantages of using styles in Word?": "تساعد Styles على توحيد تنسيق العناوين والفقرات وتسهيل تعديل التنسيق وإنشاء فهرس المحتويات.",
"Where is the Ruler enabled from?": "نفتح تبويب View ونفعّل خيار Ruler لإظهار المسطرة.",
"Which program is used to create a resume or CV?": "يُستخدم Microsoft Word عادةً لإنشاء السيرة الذاتية وتنسيقها.",
"In MS Word, which tool is used to copy text formatting?": "تُستخدم أداة Format Painter لنسخ تنسيق النص وتطبيقه على نص آخر.",
"In Microsoft Word, what does Draft View do?": "يعرض Draft View المستند بطريقة مبسطة تساعد على تحرير النص، دون إظهار بعض عناصر تخطيط الصفحة كما تظهر في Print Layout.",
"To change the Line Spacing of a text in MS Word:": "نحدد النص ثم نفتح Home > Paragraph > Line and Paragraph Spacing لتغيير تباعد الأسطر.",
"What is the function of the shortcut Ctrl + E in Microsoft Word?": "الاختصار Ctrl + E يوسّط محاذاة الفقرة أو النص.",
"What is the default view option of MS Word document?": "في الإصدارات الحديثة من Word يكون Print Layout عادةً العرض الافتراضي للمستند.",
"To apply a different Theme to your document, you go to:": "نفتح تبويب Design ثم نختار Theme لتغيير المظهر العام للمستند.",
"Presentation: if you need to click a slide that is a few slides back, how do you get there?": "أثناء عرض الشرائح، يمكن استخدام النقر بزر الفأرة الأيمن أو مفاتيح الأسهم للوصول إلى شريحة سابقة.",
"The PowerPoint view that displays only text (titles and bullets) is:": "يعرض Outline View عناوين الشرائح والنصوص النقطية على شكل مخطط نصي.",
"In MS-PowerPoint, the effect applied to display when slides change in slide show view is:": "يُسمّى تأثير الانتقال بين الشرائح Transition.",
"What is the primary purpose of PowerPoint?": "يُستخدم PowerPoint لإنشاء العروض التقديمية وعرض المعلومات بصرياً باستخدام الشرائح.",
"Which of the following is not a part of Slide Design?": "يُحدَّد الجواب من الخيارات؛ فالتصميم يخص مظهر الشريحة، أما الحركات والانتقالات فلها تبويبات مستقلة.",
"Which of the following pane is NOT available in Task Pane?": "يعتمد الجواب على الخيارات المذكورة في السؤال وعلى إصدار PowerPoint.",
"Software used to access and navigate web pages is called a:": "يُسمّى البرنامج المستخدم لفتح صفحات الويب والتنقل بينها Web Browser.",
"What is the main purpose of responsive design?": "التصميم المتجاوب يجعل الموقع يتكيف مع أحجام الشاشات المختلفة، مثل الهاتف والحاسوب اللوحي والحاسوب.",
"Which protocol is responsible for transferring files over the network?": "FTP اختصار File Transfer Protocol، وهو بروتوكول لنقل الملفات عبر الشبكة.",
"What is the internet?": "الإنترنت شبكة عالمية تربط الحواسيب والأجهزة لتبادل المعلومات والبيانات.",
"Which key is used to open the Start Menu in Windows?": "يؤدي الضغط على مفتاح Windows إلى فتح قائمة Start.",
"The tool responsible for scheduling orders in Windows is:": "صياغة السؤال غير واضحة؛ في Windows توجد أداة Task Scheduler لجدولة المهام والبرامج.",
"Which of the following shortcuts is used to open File Explorer in Windows?": "الاختصار Windows + E يفتح File Explorer مباشرةً.",
"In Windows, Start button is used to:": "تُستخدم قائمة Start لفتح البرامج والإعدادات والوصول إلى خيارات الطاقة والبحث.",
"Which key is used to rename file in Windows?": "المفتاح F2 يُستخدم لإعادة تسمية الملف أو المجلد المحدد في Windows.",
"Which tool checks disk errors?": "تُستخدم أداة CHKDSK لفحص أخطاء نظام الملفات والقرص.",
"Which of the following tools helps restore your system to a previous working state?": "تُستخدم System Restore لإرجاع إعدادات النظام إلى نقطة استعادة سابقة.",
"A full volume encryption feature included with Microsoft Windows versions is:": "BitLocker ميزة تشفير للأقراص متوفرة في بعض إصدارات Windows.",
"What is the purpose of the archive feature in email?": "تُستخدم Archive لإزالة الرسالة من صندوق الوارد مع الاحتفاظ بها في الحساب للرجوع إليها لاحقاً.",
"Which program office is responsible for sending e-mail?": "يمكن استخدام Microsoft Outlook لإرسال رسائل البريد الإلكتروني وإدارتها.",
"How can you easily distinguish important emails for quick access?": "يمكن وضع نجمة Star على الرسائل المهمة لتسهيل العثور عليها لاحقاً.",
"In an organizational structure that contains a president, vice presidents, managers, and supervisors, in which type of planning do the vice presidents come after the president?": "وفق التسلسل الإداري المذكور، يأتي نواب الرئيس ضمن الإدارة العليا، ويشاركون عادةً في التخطيط الاستراتيجي.",
"What is internet speed measured in?": "تُقاس سرعة نقل البيانات عادةً بالبت في الثانية (bps)، وغالباً بالميغابت في الثانية (Mbps).",
"Which memory is volatile?": "ذاكرة RAM متطايرة؛ تفقد محتوياتها عند انقطاع الطاقة.",
"Which storage device has no moving mechanical parts?": "SSD لا يحتوي على أجزاء ميكانيكية متحركة، لذلك يكون أسرع وأقل عرضة للصدمات من HDD عادةً.",
"Objects on the slide that hold text are called": "تُسمّى العناصر التي تحتوي على النص في الشريحة Placeholders.",
"Which term describes the ability of a computer to perform multiple tasks?": "Multitasking تعني قدرة الحاسوب على تشغيل أو إدارة عدة مهام في الوقت نفسه.",
"It is a network that can connect two or more devices to share resources (data, equipment) in different places with each other across a wide geographical area.": "WAN هي شبكة واسعة النطاق تربط أجهزة أو شبكات عبر مناطق جغرافية كبيرة لمشاركة البيانات والموارد.",
"Which of the following is not a view option in Word 2016?": "Presentation Mode مو من أوضاع العرض الأساسية في Word 2016؛ الخيارات المعروفة تشمل Read Mode وPrint Layout وDraft.",
"Which of the following allow you to select more than one slide in a presentation?": "نستخدم Ctrl مع النقر على الشرائح المتفرقة لتحديد أكثر من شريحة في PowerPoint.",
"What is a VPN?": "VPN اختصار Virtual Private Network، وتوفر اتصالاً خاصاً ومشفراً عبر الشبكة.",
"In Microsoft Excel, to fill a cell with a specific color or pattern, do the following": "من تبويب Home نفتح Format Cells ثم Fill لاختيار لون التعبئة أو النمط المتاح.",
"You can embed a MS-Organization Chart in a slide by": "يمكن إدراج مخطط تنظيمي من خلال خيارات إدراج الكائنات أو أدوات المخططات المتاحة في إصدار PowerPoint.",
"Which partition type contains the operating system?": "وفق الخيارات، القسم Primary هو القسم الأساسي الذي يمكن تثبيت نظام التشغيل عليه.",
"RAM is--": "RAM هي ذاكرة رئيسية مؤقتة Primary Memory، وتفقد محتوياتها عند انقطاع الكهرباء.",
"What protocol retrieves email?": "POP3 بروتوكول يُستخدم لاستلام البريد الإلكتروني من خادم البريد.",
"What is the difference between the Inbox and the Spam folder?": "Inbox يستقبل الرسائل الواردة، أما Spam فيحتوي على الرسائل غير المرغوب بها أو المشبوهة.",
"When a range is selected, how can you activate the previous cell?": "بحسب مفتاح الإجابة الموجود في المصدر، الخيار D هو المحدد؛ راجع صياغة السؤال والخيارات لأن الانتقال بين الخلايا يعتمد على المفتاح المستخدم.",
"What is the definition of browser?": "Browser هو برنامج يُستخدم لعرض صفحات الويب والتنقل بينها على الإنترنت.",
"Which of the following statement is false?": "بحسب مفتاح الإجابة في المصدر، الخيار D هو المحدد؛ لكن صحة العبارات تعتمد على صياغتها الدقيقة وإصدار PowerPoint.",
"What is the function of Ctrl+ G in MS Word?": "يفتح Ctrl + G نافذة Go To للانتقال إلى صفحة أو موضع معين في المستند.",
"The number of rows in an Excel 2016 worksheet is": "يحتوي Excel 2016 على 1,048,576 صفاً في ورقة العمل.",
"Which CPU register holds the address of the next instruction?": "Program Counter (PC) يحتفظ بعنوان التعليمة التالية التي ستنفذها وحدة المعالجة المركزية.",
"The small black square in the lower right corner of an active cell or range represents..": "يسمى Fill Handle، ويُستخدم لنسخ البيانات أو الصيغ أو تعبئة سلسلة من الخلايا.",
"To insert specific text on each page, click the button": "نستخدم Insert ثم Header أو Footer لإضافة نص يظهر في صفحات المستند.",
"How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?": "نحدد الخلايا الثلاث ثم نختار Merge & Center من تبويب Home لدمجها وتوسيط محتواها.",
"What is a video call?": "مكالمة الفيديو هي تواصل مباشر بالصوت والصورة بين شخصين أو أكثر.",
"Which command brings you to first slide in your presentation?": "Ctrl + Home ينقلك إلى الشريحة الأولى في عرض PowerPoint.",
"Left click in a suitable place in the desktop can be used to delete a file, folder or shortcut.": "العبارة خاطئة؛ النقر الأيسر وحده لا يحذف الملف، بل يجب تحديده ثم استخدام Delete أو أمر الحذف.",
"To insert a text box, click the button ...": "نختار Text Box من تبويب Insert لإضافة مربع نص إلى الشريحة.",
"... works with the standard Copy and Paste commands.": "Office Clipboard يحتفظ بالعناصر التي تنسخها أو تقصها لتتمكن من لصقها.",
"How can you change the orientation of a page in Word 2016 from portrait to landscape?": "نفتح Layout ثم Orientation ونختار Landscape لتغيير اتجاه الصفحة إلى أفقي.",
"How to change the width of column (B) to width (30) in a Microsoft Excel 2019 workbook?": "نحدد العمود B ثم Home > Format > Column Width وندخل القيمة 30.",
"Before you can perform any action on a file or folder, what must you do?": "يجب تحديد الملف أو المجلد أولاً حتى نتمكن من تنفيذ الإجراء المطلوب عليه.",
"To delete a new row between column A and column B, press the button ...": "لحذف عمود، نحدد العمود المطلوب ثم نختار Delete من مجموعة Cells في تبويب Home.",
"While Finding and Replacing some data in Excel, which of the following statement is valid?": "يمكن استخدام Find and Replace للبحث والاستبدال داخل ورقة العمل أو المصنف بحسب نطاق البحث المحدد.",
"What does HTTP stand for?": "HTTP اختصار HyperText Transfer Protocol، وهو بروتوكول نقل صفحات وبيانات الويب.",
"In Microsoft Excel, pie chart is used for": "يُستخدم Pie Chart لعرض مساهمة كل قيمة كنسبة من المجموع الكلي.",
"Animation schemes can be applied to ... in the presentation": "يمكن تطبيق مخططات الحركة على جميع الشرائح أو شرائح محددة أو الشريحة الحالية، حسب الاختيار.",
"The primary purpose of protecting data online is:": "الهدف الأساسي هو حماية خصوصية البيانات الشخصية ومنع الوصول غير المصرح به إليها.",
"File of type bmp is:": "BMP هو امتداد لملفات الصور النقطية Bitmap.",
"What does the Reply All function do?": "Reply All يرسل الرد إلى المرسل وإلى جميع المستلمين المعنيين بالرسالة.",
"Which device converts digital signals to printed output?": "الطابعة Printer تحول البيانات الرقمية إلى نصوص أو صور مطبوعة على الورق.",
"What is HTML?": "HTML اختصار HyperText Markup Language، وهي لغة ترميز تُستخدم لبناء هيكل صفحات الويب.",
"The taskbar is located": "يوجد شريط المهام Taskbar عادةً أسفل شاشة Windows، ويمكن تغيير موضعه بحسب الإعدادات.",
"What does LAN stand for?": "LAN اختصار Local Area Network، أي شبكة محلية تربط الأجهزة ضمن مساحة محدودة.",
"Which folder contains installed applications by default?": "Program Files هو المجلد المعتاد لتثبيت كثير من التطبيقات في Windows.",
"What is an online account?": "الحساب الإلكتروني هو ملف أو حساب شخصي يتيح للمستخدم الوصول إلى خدمة عبر الإنترنت.",
"Microsoft Word is ... software": "Microsoft Word برنامج تطبيقي Application Software يُستخدم لإنشاء المستندات وتحريرها.",
"Which storage device uses magnetic technology?": "Hard Disk Drive (HDD) يخزن البيانات باستخدام تقنية مغناطيسية.",
"What is the purpose of the archive feature in email?": "الأرشفة تحفظ الرسائل القديمة دون حذفها، وتزيلها عادةً من صندوق الوارد.",
"Which of the following items you must have to send an email:": "تحتاج إلى عنوان البريد الإلكتروني للمستلم حتى ترسل الرسالة إليه.",
"If you have a PowerPoint show you created and want to send using email to another teacher you can add the show to your email message as a (an):": "نضيف ملف العرض إلى الرسالة بوصفه Attachment، أي مرفقاً.",
"What does URL represent?": "URL اختصار Uniform Resource Locator، وهو عنوان يحدد موقع مورد على الإنترنت.",
"Small text file created by a website that is stored in the user's computer temporarily for that session is called ........": "Cookie ملف نصي صغير يخزنه الموقع في المتصفح لتذكر معلومات أو إعدادات معينة.",
"Stored link to a Web page, in order to have a quick and easy access to it later, is called": "Bookmark هو رابط محفوظ لصفحة ويب حتى يمكن الرجوع إليها بسرعة.",
"In a web browser, which of the following is used to save frequently visited websites?": "Favorites تُستخدم لحفظ المواقع المفضلة والوصول إليها بسرعة.",
"What is Instant Messaging (IM)?": "المراسلة الفورية تتيح تبادل الرسائل عبر الإنترنت بصورة مباشرة أو شبه فورية.",
"Website is a collection of": "الموقع الإلكتروني مجموعة من صفحات الويب المرتبطة ببعضها.",
"Which of the following options is generally used to view and manage emails received": "Inbox هو صندوق الوارد الذي تظهر فيه الرسائل المستلمة عادةً.",
"........ command in Web browser that helps to move to the previous page from the current page.": "Back يعيد المتصفح إلى صفحة الويب السابقة.",
"The Internet is": "الإنترنت شبكة ضخمة من الشبكات المترابطة حول العالم.",
"........ offers real time chat between individuals and groups of people.": "Instant Messenger يتيح المحادثة الفورية بين الأفراد والمجموعات.",
"The ......... field of an e-mail indicates the receiver of that e-mail.": "حقل To يحتوي على عنوان المستلم الأساسي للرسالة.",
"Which Windows feature allows users to organize files and folders?": "File Explorer أداة Windows المستخدمة لتصفح الملفات والمجلدات وتنظيمها.",
"Which utility in Windows is used to free up disk space?": "Disk Cleanup أداة تساعد على إزالة الملفات غير الضرورية وتوفير مساحة على القرص.",
"small arrow or blinking symbol on desktop is called a___": "يُسمى مؤشر الكتابة أو السهم الذي يتحرك على الشاشة Cursor، وهو يحدد موضع التفاعل أو الإدخال.",
"Which of the following are actions you can assign to an action button or slide object?": "يمكن ربط زر الإجراء أو الكائن بتشغيل ماكرو أو تشغيل صوت أو فتح رابط تشعبي.",
"Excel contains": "يمكن أن تحتوي ورقة Excel على نصوص وأرقام وصيغ وصور وعناصر أخرى.",
"Data and information are exchanged over the internet through:": "تُستخدم الخوادم Servers لتوفير البيانات والخدمات للمستخدمين عبر الإنترنت.",
"In order to edit a chart, you can": "ننقر نقرتين متتاليتين على المخطط لفتح أدوات تعديله أو تنسيق عناصره.",
"The desktop background is also known as:": "تسمى خلفية سطح المكتب Wallpaper.",
"All of the following programs are considered applications except:": "نظام التشغيل Operating System ليس برنامجاً تطبيقياً عادياً؛ بل هو برنامج نظام يدير موارد الحاسوب.",
"Which of the following is/are true about rulers and guides?": "يمكن إظهار المساطر والأدلة أو إخفاؤها، وتساعد على محاذاة العناصر، لكنها لا تُطبع عادةً ضمن الشريحة.",
"The screen background is known :": "تُسمى المساحة الرئيسية التي تظهر عليها الأيقونات والنوافذ في Windows سطح المكتب Desktop.",
"What is the purpose of encryption in information security?": "التشفير يحول البيانات إلى صيغة غير مقروءة دون مفتاح أو وسيلة فك مناسبة، بهدف حمايتها.",
"What is the best way to recognize a phishing attempt?": "تجنب التفاعل مع الرسائل المشبوهة، ولا تضغط على روابطها أو ترسل معلوماتك الشخصية؛ افحص المرسل والرابط بحذر.",
"What symbol is used to attach an image or file in email?": "رمز مشبك الورق Paperclip يدل عادةً على إرفاق ملف أو صورة بالبريد الإلكتروني.",
"Which of the following would move the cursor to the beginning of the current line?": "مفتاح Home ينقل مؤشر الكتابة إلى بداية السطر الحالي.",
"What effect is added to slides during a slide show in PowerPoint?": "Transition هو التأثير الذي يظهر عند الانتقال من شريحة إلى أخرى.",
"To insert a new worksheet, click on the button:": "من Home نختار Insert ثم Insert Sheet لإضافة ورقة عمل جديدة.",
"What does email scheduling mean?": "جدولة البريد تعني تحديد تاريخ أو وقت لإرسال الرسالة لاحقاً تلقائياً.",
"What tool would you use to merge some cells and center the content in the merged cell?": "نستخدم Merge & Center لدمج الخلايا المحددة وتوسيط المحتوى.",
"What is the document Outline View?": "Outline View يعرض بنية العناوين على مستويات مختلفة، مما يسهل مراجعة تنظيم المستند.",
"Internet is the name given to:": "الإنترنت شبكة عالمية من أنظمة وشبكات الحاسوب المترابطة.",
"What is the application used to browse websites?": "Browser هو التطبيق المستخدم لفتح المواقع والتنقل بين صفحات الويب.",
"When working on a cloud-based document such as Google Docs, what feature allows multiple people to edit the document in real time?": "Real-time collaboration تسمح لأكثر من مستخدم بتحرير المستند نفسه في الوقت الفعلي.",
"What is latency?": "Latency هو التأخير الزمني بين إرسال البيانات ووصولها أو الاستجابة لها عبر الشبكة.",
"What is CAPTCHA used for?": "CAPTCHA تساعد على التحقق من أن المستخدم إنسان وليست عملية آلية، مثل البوت.",
"Which option in PowerPoint allows to carry slides from one computer to another?": "بحسب مفتاح الإجابة في المصدر، الخيار Pack and Go هو المحدد لنقل العرض إلى حاسوب آخر.",
"Block arrows, stars and banners, and callouts are all examples of:": "تُعد الأسهم الممتلئة والنجوم واللافتات ووسائل الشرح من فئات AutoShapes.",
"to Open Help Window": "المفتاح F1 يُستخدم عادةً لفتح نافذة المساعدة Help.",
"Which of the following is considered an \"Output Device\"?": "الطابعة Printer جهاز إخراج لأنها تعرض نتائج الحاسوب على الورق.",
"Which of the following can be used for quick access to common commands and tools?": "Toolbar شريط الأدوات يضم اختصارات للوصول السريع إلى الأوامر الشائعة.",
"The difference between Slide Design and Auto Content Wizard is": "وفق الخيار المحدد في المصدر، يوفر Auto Content Wizard محتوى نموذجياً، بينما يركز Slide Design على مظهر الشرائح.",
"Which uses magnetic disk to store data?": "Hard Disk يخزن البيانات على أقراص مغناطيسية.",
"Sending an item to the Trash means .....": "نقل الرسالة إلى Trash يعني حذفها أو نقلها إلى سلة المحذوفات.",
"Which of the following describes a hardware component in computer system ?": "لوحة المفاتيح Keyboard مكوّن مادي Hardware يُستخدم لإدخال البيانات.",
"What happens if you select the first and second slides, then click on the \"New Slide\" button in the toolbar ?": "بحسب مفتاح الإجابة، تُدرج الشريحة الجديدة بعد الشريحتين المحددتين، أي تصبح الثالثة.",
"To insert a new column between Column A and Column B, click on the button": "نحدد العمود B ثم نختار Insert من مجموعة Cells؛ يُدرج العمود الجديد قبله، بين A وB.",
"Which of the following is designed to control the operations of a computer?": "System Software يدير موارد الحاسوب ويتحكم بعمله، ومن أمثلته نظام التشغيل.",
"What is the term used when you press and hold the left mouse key and move the mouse around the slide?": "تُسمى هذه العملية Dragging، أي السحب باستخدام الفأرة.",
"How do we change the text size of a cell?": "من تبويب Home، ضمن مجموعة Font، نغيّر قيمة Font Size لتعديل حجم النص.",
"Blu-ray Disc (BD) is:": "Blu-ray Disc وسيط تخزين ضوئي يستخدم الليزر لقراءة البيانات وكتابتها بحسب نوع القرص.",
"Which of the following allow you to select more than one slide in a presentation": "نستخدم Ctrl مع النقر لتحديد شرائح متعددة غير متجاورة في PowerPoint.",
"Each line represents how many letters in WordStar?": "وفق مفتاح الإجابة في المصدر، الخيار المحدد هو 65؛ يُفضّل مراجعة مرجع السؤال لأن WordStar برنامج قديم وقد تختلف الصياغة.",
"The fastest internet network is:": "وفق الإجابة المحددة في الملف، الخيار B هو Fiber optic (الألياف الضوئية)، وهي تقنية توفر سرعات عالية لنقل البيانات.",
"What does URL represent?": "URL اختصار Uniform Resource Locator، ويعني عنوان المورد على الإنترنت، مثل عنوان صفحة الويب.",
"In Microsoft Excel, to insert a new row, do the following:": "وفق الإجابة المحددة في الملف، الخيار C هو الصحيح: من قائمة Insert نختار Rows لإدراج صف جديد. قد تختلف خطوات الإدراج بحسب إصدار Excel.",
"To sort column A in ascending order, press the button:": "وفق الإجابة المحددة في الملف، الخيار A هو الصحيح: نستخدم أمر Sort and Filter لترتيب بيانات العمود تصاعدياً.",
"In Microsoft Excel, which function should you use if you want to count cells that contain numbers only within a specific range?": "الدالة COUNT تحسب الخلايا التي تحتوي على أرقام فقط، وتتجاهل الخلايا الفارغة والنصوص.",
"What do the letters (C, D, E) represent in the Windows operating system?": "وفق الإجابة المحددة في الملف، الخيار B هو Drives؛ أي أحرف محركات الأقراص أو أقسامها في Windows."
    
}

import json
import logging
import time
import uuid
import requests

# تعريف التسجيل مرة واحدة فقط
logger = logging.getLogger(__name__)

# يفترض وجود PROPERTIES و send و is_admin و is_user_subscribed و send_subscription_prompt و get_state و save_state و clear_state في البيئة

def get_questions():
    raw_base = get_base_question_data()
    base_questions = []
    
    # تحويل البيانات الأساسية من مصفوفة إلى قاموس منسق
    for i, q in enumerate(raw_base, start=1):
        base_questions.append({
            "id": f"Q{i}",
            "category": str(q[0]).strip(),
            "question": str(q[1]).strip(),
            "options": [str(x) for x in q[2:6]],
            "answer": str(q[6]).strip().upper(),
            "explanation": q[7] if len(q) > 7 else ""
        })

    saved_edits = json.loads(PROPERTIES.get("QUESTION_EDITS", "{}"))
    saved_new = json.loads(PROPERTIES.get("NEW_QUESTIONS", PROPERTIES.get("NEW_QUESTION", "[]")))
    deleted_question_ids = [
        str(x) for x in json.loads(PROPERTIES.get("DELETED_QUESTIONS", "[]"))
    ]

    all_questions = base_questions + saved_new
    processed_questions = []

    for q in all_questions:
        q_id = str(q.get("id"))
        edit = saved_edits.get(q_id, {})

        explanation = edit.get("explanation", q.get("explanation", ""))

        merged_q = {
            **q,
            "category": str(edit.get("category", q.get("category", ""))).strip(),
            "question": edit.get("question", q.get("question", "")),
            "options": edit.get("options", q.get("options", [])),
            "answer": str(edit.get("answer", q.get("answer", ""))).strip().upper(),
            "explanation": explanation
        }
        processed_questions.append(merged_q)

    filtered_questions = []
    for q in processed_questions:
        options = q.get("options")
        is_valid = (
            q.get("category")
            and q.get("question")
            and isinstance(options, list)
            and len(options) == 4
            and all(str(x).strip() != "" for x in options)
            and q.get("answer") in ["A", "B", "C", "D"]
            and str(q.get("id")) not in deleted_question_ids
        )
        if is_valid:
            filtered_questions.append(q)

    return filtered_questions


def main_keyboard(user_id):
    keyboard = [
        [
            {"text": "📁 ملفات اختبار الحاسوب"},
            {"text": "📝 فورمات اختبار الحاسوب"}
        ],
        [
            {"text": "💻 أسئلة اختبار الحاسوب"}
        ]
    ]

    if is_admin(user_id):
        keyboard.append([
            {"text": "🛠 الإدارة"},
            {"text": "📊 تقرير"}
        ])

    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True
    }


def answer_callback_query(callback_id, text=""):
    token = PROPERTIES.get("BOT_TOKEN")
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "callback_query_id": callback_id,
                "text": text
            })
        )
    except Exception as e:
        logger.error(f"Error in answer_callback_query: {e}")


def ask_question(chat_id, state):
    q = state["questions"][state["index"]]
    state["answerLocked"] = False
    save_state(chat_id, state)

    remaining = max(0, int((state["deadline"] - (time.time() * 1000)) / 1000))

    keyboard = [
        [
            {"text": "A", "callback_data": f"ans:{state['index']}:A"},
            {"text": "B", "callback_data": f"ans:{state['index']}:B"},
            {"text": "C", "callback_data": f"ans:{state['index']}:C"},
            {"text": "D", "callback_data": f"ans:{state['index']}:D"}
        ]
    ]

    options_text = (
        f"A) {q['options'][0]}\n\n"
        f"B) {q['options'][1]}\n\n"
        f"C) {q['options'][2]}\n\n"
        f"D) {q['options'][3]}"
    )

    if is_admin(chat_id):
        keyboard.append([
            {"text": "✏️ تعديل هذا السؤال", "callback_data": f"editq:{q['id']}"},
            {"text": "🗑️ حذف هذا السؤال", "callback_data": f"deleteq:{q['id']}"}
        ])

    text_msg = (
        f"📚 المادة: {state['category']}\n"
        f"السؤال {state['index'] + 1} من {len(state['questions'])}\n"
        f"⏱️ الوقت المتبقي تقريباً: {remaining} ثانية\n\n"
        f"❓ {q['question']}\n\n"
        f"{options_text}\n\n"
        f"👇 اختر الإجابة الصحيحة:"
    )

    return send(chat_id, text_msg, {"inline_keyboard": keyboard})


# معالجة الأوامر والرسائل النصية (دمج handle_message و handle_message_continued)
def handle_message(m):
    chat = m.get("chat", {})
    chat_id = chat.get("id")
    logger.info(f"CHAT ID: {chat_id}")

    text = str(m.get("text") or "").strip()

    # استقبال ملفات PDF من المشرف
    document = m.get("document")
    if document:
        if not is_admin(chat_id):
            return send(chat_id, "رفع الملفات مخصص للمشرف فقط.")

        if document.get("mime_type") != "application/pdf":
            return send(chat_id, "أرسل الملف بصيغة PDF.")

        file1 = PROPERTIES.get("PDF_FILE_1")
        if not file1:
            PROPERTIES["PDF_FILE_1"] = document.get("file_id")
            return send(chat_id, "تم حفظ ملف PDF الأول ✅\nأرسل ملف PDF الثاني.")

        PROPERTIES["PDF_FILE_2"] = document.get("file_id")
        return send(chat_id, "تم حفظ ملف PDF الثاني بنجاح ✅")

    if not text:
        return

    # استبدال نصوص الأزرار بالأوامر
    button_commands = {
        "📝 بدء الاختبار": "/quiz",
        "📚 اختيار المادة": "/quiz",
        "ℹ️ المساعدة": "/help",
        "🛠 الإدارة": "/admin",
        "📁 ملفات اختبار الحاسوب": "/malaزم",
        "📊 تقرير": "/report",
        "➕ إضافة سؤال": "/add"
    }
    text = button_commands.get(text, text)

    # الأوامر العامة
    if text == "/start":
        if not is_user_subscribed(chat_id):
            return send_subscription_prompt(chat_id)
        return send(chat_id, "أهلاً بك في بوت الاختبارات 📚🇮🇶\n\nاختر أحد الأزرار أدناه للبدء.", main_keyboard(chat_id))

    if text == "/help":
        return send(chat_id, "/quiz — بدء اختبار\n/id — معرفة معرّف حسابك\n/cancel — إلغاء العملية الحالية")

    if text == "/cancel":
        clear_state(chat_id)
        return send(chat_id, "تم إلغاء العملية والعودة للقائمة الرئيسية.", main_keyboard(chat_id))

    if text == "/id":
        return send(
            chat_id,
            f"معرّف المحادثة: {chat_id}\n"
            f"معرّف المشرف: {PROPERTIES.get('ADMIN_ID', 'غير محدد')}\n"
            f"الملف الأول: {'محفوظ' if PROPERTIES.get('PDF_FILE_1') else 'غير محفوظ'}\n"
            f"الملف الثاني: {'محفوظ' if PROPERTIES.get('PDF_FILE_2') else 'غير محفوظ'}"
        )

    if text == "/report":
        if not is_admin(chat_id):
            return send(chat_id, "هذا التقرير مخصص للمشرفين فقط.")
        return show_exam_report(chat_id)

    if not is_user_subscribed(chat_id):
        return send_subscription_prompt(chat_id)

    if text == "/malaزم":
        file1 = PROPERTIES.get("PDF_FILE_1")
        file2 = PROPERTIES.get("PDF_FILE_2")
        token = PROPERTIES.get("BOT_TOKEN")

        if not file1 or not file2:
            return send(chat_id, "الملزمتان غير محفوظتين. يرجى إبلاغ المشرف.")

        for i, file_id in enumerate([file1, file2]):
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": str(chat_id), "document": file_id}
            )
            result = response.json()
            if not result.get("ok"):
                return send(chat_id, f"فشل إرسال الملف رقم {i + 1}\nالخطأ: {result.get('description')}")

        return send(chat_id, "تم إرسال الملزمتين بنجاح ✅")

    if text == "📝 فورمات اختبار الحاسوب":
        forms_message = (
            "الفورمات التي تخص قناتنا جداً مهمة\n\n"
            "✅ سنة 2026 هاي الفورم مالتها 125 سؤال مطولة بس من أهم الفورمات:\n"
            "https://forms.gle/8KYjdsFJYEaUKB7H7\n\n"
            "قناة الست هبة حسين:\nhttps://t.me/hibhibcomp"
        )
        return send(chat_id, forms_message, main_keyboard(chat_id))

    if text in ["💻 أسئلة اختبار الحاسوب", "/quiz"]:
        clear_state(chat_id)
        keyboard = [
            [{"text": "💻 أساسيات الحاسوب", "callback_data": "subject:basics"}],
            [{"text": "📊 Excel", "callback_data": "subject:excel"}],
            [{"text": "📝 Word", "callback_data": "subject:word"}],
            [{"text": "📽️ PowerPoint", "callback_data": "subject:powerpoint"}]
        ]
        return send(chat_id, "📚 اختر المادة التي تريد حل أسئلتها:", {"inline_keyboard": keyboard})

    if text == "/admin":
        if not is_admin(chat_id):
            return send(chat_id, "هذا الأمر مخصص للمشرف.")
        return send(
            chat_id,
            "🛠 إدارة البوت\n\nاختر العملية المطلوبة:",
            {
                "inline_keyboard": [
                    [{"text": "➕ إضافة سؤال", "callback_data": "admin:add"}],
                    [{"text": "✏️ تعديل سؤال", "callback_data": "admin:edit"}],
                    [{"text": "🗑️ حذف سؤال", "callback_data": "admin:delete"}],
                    [{"text": "⏱️ تحديد مدة الاختبار", "callback_data": "admin:time"}]
                ]
            }
        )

    if text.startswith("/time "):
        if not is_admin(chat_id):
            return send(chat_id, "غير مسموح.")
        try:
            n = int(text.split()[1])
            if not (1 <= n <= 180):
                raise ValueError()
            PROPERTIES["QUIZ_MINUTES"] = str(n)
            return send(chat_id, f"تم تحديد مدة الاختبار: {n} دقيقة.")
        except (IndexError, ValueError):
            return send(chat_id, "اكتب مدة صحيحة من 1 إلى 180 دقيقة.")

    if text == "/add":
        if not is_admin(chat_id):
            return send(chat_id, "غير مسموح.")
        subjects = ["مكونات الحاسوب", "Excel", "Word", "PowerPoint", "الإنترنت", "Windows", "قواعد البيانات", "الإيميل"]
        save_state(chat_id, {"mode": "add", "step": "category", "subjects": subjects})
        keyboard = [[{"text": sub, "callback_data": f"addcat:{i}"}] for i, sub in enumerate(subjects)]
        return send(chat_id, "📚 اختر المادة التي تريد إضافة سؤال إليها:", {"inline_keyboard": keyboard})

    # إدخال القيم أثناء التعديل أو الإضافة
    state = get_state(chat_id)

    if state.get("mode") == "edit" and is_admin(chat_id) and state.get("step") == "value":
        field = state.get("editField")
        question_id = state.get("questionId")
        value = text.strip()

        if field == "answer":
            value = value.upper()
            if value not in ["A", "B", "C", "D"]:
                return send(chat_id, "اكتب حرف الإجابة الصحيحة فقط: A أو B أو C أو D.")

        if field == "options":
            options = [x.strip() for x in value.split("|")]
            if len(options) != 4 or any(not x for x in options):
                return send(chat_id, "اكتب الخيارات الأربعة وافصل بينها بالرمز |")
            value = options

        if field == "explanation" and value == "مسح":
            value = ""

        save_question_edit(question_id, field, value)
        clear_state(chat_id)
        return send(chat_id, "تم حفظ تعديل السؤال بنجاح ✅")

    if state.get("mode") == "add" and is_admin(chat_id):
        step = state.get("step")
        if step == "question":
            state["question"] = text
            state["step"] = "options"
            save_state(chat_id, state)
            return send(chat_id, "اكتب الخيارات الأربعة برسالة واحدة وافصل بينها بالرمز |")

        if step == "options":
            options = [x.strip() for x in text.split("|")]
            if len(options) != 4 or any(not x for x in options):
                return send(chat_id, "أحتاج أربعة خيارات بالضبط، افصل بينها بالرمز |")
            state["options"] = options
            state["step"] = "answer"
            save_state(chat_id, state)
            return send(chat_id, "اكتب حرف الإجابة الصحيحة: A أو B أو C أو D")

        if step == "answer":
            answer = text.upper()
            if answer not in ["A", "B", "C", "D"]:
                return send(chat_id, "اكتب A أو B أو C أو D فقط.")

            new_question = {
                "id": "N" + uuid.uuid4().hex[:12],
                "category": state["category"],
                "question": state["question"],
                "options": [str(x) for x in state["options"]],
                "answer": answer,
                "explanation": ""
            }
            saved_new = json.loads(PROPERTIES.get("NEW_QUESTIONS", "[]"))
            saved_new.append(new_question)
            PROPERTIES["NEW_QUESTIONS"] = json.dumps(saved_new)
            clear_state(chat_id)
            return send(chat_id, "تم حفظ السؤال الجديد بنجاح ✅")

    return send(chat_id, "اكتب /start للبدء أو /quiz لاختيار اختبار.")


# معالجة تفاعلات الأزرار
def handle_callback_query(callback):
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    callback_id = callback.get("id")
    data = str(callback.get("data", ""))

    if data.startswith("deletepage:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        answer_callback_query(callback_id)
        page = int(data[len("deletepage:"):])
        return show_delete_page(chat_id, page)

    if data.startswith("admin:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        answer_callback_query(callback_id)

        if data == "admin:add":
            return send(chat_id, "لإضافة سؤال جديد، أرسل الأمر /add")
        if data == "admin:edit":
            return show_edit_page(chat_id, 0)
        if data == "admin:delete":
            return show_delete_page(chat_id, 0)
        if data == "admin:time":
            return send(chat_id, "أرسل الأمر /time متبوعًا بالمدة بالدقائق.\nمثال: /time 30")

    if data == "check_subscription":
        answer_callback_query(callback_id)
        if is_user_subscribed(chat_id):
            return send(chat_id, "✅ تم التحقق من اشتراكك بنجاح.", main_keyboard(chat_id))
        return send_subscription_prompt(chat_id)

    if not is_user_subscribed(chat_id):
        answer_callback_query(callback_id, "اشترك بالقناة أولًا.")
        return send_subscription_prompt(chat_id)

    state = get_state(chat_id)

    if data.startswith("subject:") or data.startswith("section:"):
        subjects = {"basics": None, "excel": "Excel", "word": "Word", "powerpoint": "PowerPoint"}
        sections = {"components": "مكونات الحاسوب", "internet": "الإنترنت", "windows": "Windows", "database": "قواعد البيانات", "email": "الإيميل"}

        if data.startswith("subject:"):
            subject = data[8:]
            if subject == "basics":
                answer_callback_query(callback_id, "تم اختيار أساسيات الحاسوب")
                keyboard = [
                    [{"text": "🧩 مكونات الحاسوب", "callback_data": "section:components"}],
                    [{"text": "🌐 الإنترنت", "callback_data": "section:internet"}],
                    [{"text": "🪟 Windows", "callback_data": "section:windows"}],
                    [{"text": "🗄️ قواعد البيانات", "callback_data": "section:database"}],
                    [{"text": "📧 الإيميل", "callback_data": "section:email"}]
                ]
                return send(chat_id, "💻 اختر قسم أساسيات الحاسوب:", {"inline_keyboard": keyboard})
            category = subjects.get(subject)
        else:
            category = sections.get(data[8:])

        answer_callback_query(callback_id, "تم اختيار القسم")
        if not category:
            return send(chat_id, "القسم غير معروف.")

        questions = [q for q in get_questions() if q.get("category") == category]
        if not questions:
            return send(chat_id, f"لا توجد أسئلة مضافة حاليًا في قسم {category}.")

        part_size = 25
        part_count = (len(questions) + part_size - 1) // part_size

        save_state(chat_id, {"mode": "pickPart", "category": category, "partCount": part_count})

        keyboard = []
        for i in range(part_count):
            start = i * part_size
            count = min(part_size, len(questions) - start)
            keyboard.append([{"text": f"الجزء {i + 1} ({count} سؤال)", "callback_data": f"part:{i}"}])

        return send(chat_id, f"📚 القسم: {category}\n📝 مجموع الأسئلة: {len(questions)}\n\nاختر الجزء الذي تريد اختباره:", {"inline_keyboard": keyboard})

    if data.startswith("confirmdeleteq:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        question_id = data[len("confirmdeleteq:"):].strip()
        deleted = json.loads(PROPERTIES.get("DELETED_QUESTIONS", "[]"))
        if question_id not in deleted:
            deleted.append(question_id)
            PROPERTIES["DELETED_QUESTIONS"] = json.dumps(deleted)
        answer_callback_query(callback_id, "تم حذف السؤال.")
        return send(chat_id, "✅ تم حذف السؤال بنجاح.")

    if data.startswith("addcat:"):
        if not is_admin(chat_id) or state.get("mode") != "add" or state.get("step") != "category":
            return answer_callback_query(callback_id, "انتهت صلاحية الاختيار")
        index = int(data[7:])
        subjects = state.get("subjects", [])
        if 0 <= index < len(subjects):
            state["category"] = subjects[index]
            state["step"] = "question"
            save_state(chat_id, state)
            answer_callback_query(callback_id, "تم اختيار المادة")
            return send(chat_id, f"المادة: {state['category']}\n\nاكتب نص السؤال.")
    
import json
import logging
import requests
import uuid

logger = logging.getLogger(__name__)

# يفترض توفر الكائنات والدوائر الأساسية (PROPERTIES, send, is_admin, إلخ)

def main_keyboard(user_id):
    keyboard = [
        [
            {"text": "📁 ملفات اختبار الحاسوب"},
            {"text": "📝 فورمات اختبار الحاسوب"}
        ],
        [
            {"text": "💻 أسئلة اختبار الحاسوب"}
        ]
    ]

    if is_admin(user_id):
        keyboard.append([
            {"text": "🛠 الإدارة"},
            {"text": "📊 تقرير"}
        ])

    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True
    }

def ask_question(chat_id, state):
    q = state["questions"][state["index"]]

    state["answerLocked"] = False
    save_state(chat_id, state)

    remaining = max(0, int((state["deadline"] - (time.time() * 1000)) / 1000))

    # أزرار الإجابة: الحروف فقط
    keyboard = [
        [
            {"text": "A", "callback_data": f"ans:{state['index']}:A"},
            {"text": "B", "callback_data": f"ans:{state['index']}:B"},
            {"text": "C", "callback_data": f"ans:{state['index']}:C"},
            {"text": "D", "callback_data": f"ans:{state['index']}:D"}
        ]
    ]

    options_text = (
        f"A) {q['options'][0]}\n\n"
        f"B) {q['options'][1]}\n\n"
        f"C) {q['options'][2]}\n\n"
        f"D) {q['options'][3]}"
    )

    if is_admin(chat_id):
        keyboard.append([
            {"text": "✏️ تعديل هذا السؤال", "callback_data": f"editq:{q['id']}"},
            {"text": "🗑️ حذف هذا السؤال", "callback_data": f"deleteq:{q['id']}"}
        ])

    text_msg = (
        f"📚 المادة: {state['category']}\n"
        f"السؤال {state['index'] + 1} من {len(state['questions'])}\n"
        f"⏱️ الوقت المتبقي تقريباً: {remaining} ثانية\n\n"
        f"❓ {q['question']}\n\n"
        f"{options_text}\n\n"
        f"👇 اختر الإجابة الصحيحة:"
    )

    return send(chat_id, text_msg, {"inline_keyboard": keyboard})

# تكملة دالة handle_message
def handle_message_continued(m):
    chat_id = m.get("chat", {}).get("id")
    text = str(m.get("text") or "").strip()

    if text == "/id":
        return send(
            chat_id,
            f"معرّف المحادثة: {chat_id}\n"
            f"معرّف المشرف: {PROPERTIES.get('ADMIN_ID', 'غير محدد')}\n"
            f"معرّف الملف الأول محفوظ: {'نعم' if PROPERTIES.get('PDF_FILE_1') else 'لا'}\n"
            f"معرّف الملف الثاني محفوظ: {'نعم' if PROPERTIES.get('PDF_FILE_2') else 'لا'}"
        )

    if text == "/start":
        if not is_user_subscribed(chat_id):
            return send_subscription_prompt(chat_id)

        return send(
            chat_id,
            "أهلاً بك في بوت اختبارات هبه 📚🇮🇶\n\nاختر أحد الأزرار أدناه للبدء.",
            main_keyboard(chat_id)
        )

    if text == "/help":
        return send(
            chat_id,
            "/quiz — بدء اختبار\n/id — معرفة معرّف حسابك\n/cancel — إلغاء العملية الحالية"
        )

    if text == "/cancel":
        clear_state(chat_id)
        return send(chat_id, "تم إلغاء العملية والعودة للقائمة الرئيسية.", main_keyboard(chat_id))

    if text == "/checkadmin":
        return send(
            chat_id,
            f"Chat ID: {chat_id}\n"
            f"ADMIN_ID موجود: {'نعم' if PROPERTIES.get('ADMIN_ID') else 'لا'}\n"
            f"هل أنت مشرف: {'نعم' if is_admin(chat_id) else 'لا'}"
        )

    if text == "/admin":
        if not is_admin(chat_id):
            return send(chat_id, "هذا الأمر مخصص للمشرف.")

        return send(
            chat_id,
            "🛠 إدارة البوت\n\nاختر العملية المطلوبة:",
            {
                "inline_keyboard": [
                    [{"text": "➕ إضافة سؤال", "callback_data": "admin:add"}],
                    [{"text": "✏️ تعديل سؤال", "callback_data": "admin:edit"}],
                    [{"text": "🗑️ حذف سؤال", "callback_data": "admin:delete"}],
                    [{"text": "⏱️ تحديد مدة الاختبار", "callback_data": "admin:time"}]
                ]
            }
        )

    if text.startswith("/time "):
        if not is_admin(chat_id):
            return send(chat_id, "غير مسموح.")

        parts = text.split()
        try:
            n = int(parts[1])
            if not (1 <= n <= 180):
                raise ValueError()
        except (IndexError, ValueError):
            return send(chat_id, "اكتب مدة صحيحة من 1 إلى 180 دقيقة.")

        PROPERTIES["QUIZ_MINUTES"] = str(n)
        return send(chat_id, f"تم تحديد مدة الاختبار: {n} دقيقة.")

    if text == "/add":
        if not is_admin(chat_id):
            return send(chat_id, "غير مسموح.")

        subjects = [
            "مكونات الحاسوب", "Excel", "Word", "PowerPoint",
            "الإنترنت", "Windows", "قواعد البيانات", "الإيميل"
        ]
        save_state(chat_id, {
            "mode": "add",
            "step": "category",
            "subjects": subjects
        })

        keyboard = [[{"text": sub, "callback_data": f"addcat:{i}"}] for i, sub in enumerate(subjects)]
        return send(
            chat_id,
            "📚 اختر المادة التي تريد إضافة سؤال إليها:",
            {"inline_keyboard": keyboard}
        )

    state = get_state(chat_id)

    # وضع التعديل
    if state.get("mode") == "edit" and is_admin(chat_id) and state.get("step") == "value":
        field = state.get("editField")
        question_id = state.get("questionId")
        value = text.strip()

        if field == "answer":
            value = value.upper()
            if value not in ["A", "B", "C", "D"]:
                return send(chat_id, "اكتب حرف الإجابة الصحيحة فقط: A أو B أو C أو D.")

        if field == "options":
            options = [x.strip() for x in value.split("|")]
            if len(options) != 4 or any(not x for x in options):
                return send(chat_id, "اكتب الخيارات الأربعة وافصل بينها بالرمز |")
            value = options

        if field == "explanation" and value == "مسح":
            value = ""

        save_question_edit(question_id, field, value)
        clear_state(chat_id)
        return send(chat_id, "تم حفظ تعديل السؤال بنجاح ✅")

    # وضع الإضافة
    if state.get("mode") == "add" and is_admin(chat_id):
        step = state.get("step")

        if step == "category":
            state["category"] = text
            state["step"] = "question"
            save_state(chat_id, state)
            return send(chat_id, "اكتب نص السؤال.")

        if step == "question":
            state["question"] = text
            state["step"] = "options"
            save_state(chat_id, state)
            return send(
                chat_id,
                "اكتب الخيارات الأربعة برسالة واحدة وافصل بينها بالرمز | \nمثال: Internet | WAN | LAN | PAN"
            )

        if step == "options":
            options = [x.strip() for x in text.split("|")]
            if len(options) != 4 or any(not x for x in options):
                return send(chat_id, "أحتاج أربعة خيارات بالضبط، افصل بينها بالرمز |")

            state["options"] = options
            state["step"] = "answer"
            save_state(chat_id, state)
            return send(chat_id, "اكتب حرف الإجابة الصحيحة: A أو B أو C أو D")

        if step == "answer":
            answer = text.upper()
            if answer not in ["A", "B", "C", "D"]:
                return send(chat_id, "اكتب A أو B أو C أو D فقط.")

            new_question = {
                "id": "N" + uuid.uuid4().hex[:12],
                "category": state["category"],
                "question": state["question"],
                "options": [str(x) for x in state["options"]],
                "answer": answer,
                "explanation": ""
            }

            saved_new = json.loads(PROPERTIES.get("NEW_QUESTIONS", "[]"))
            saved_new.append(new_question)
            PROPERTIES["NEW_QUESTIONS"] = json.dumps(saved_new)

            clear_state(chat_id)
            return send(chat_id, "تم حفظ السؤال الجديد بنجاح ✅")

    if text == "/quiz":
        clear_state(chat_id)
        keyboard = [
            [{"text": "💻 أساسيات الحاسوب", "callback_data": "subject:basics"}],
            [{"text": "📊 Excel", "callback_data": "subject:excel"}],
            [{"text": "📝 Word", "callback_data": "subject:word"}],
            [{"text": "📽️ PowerPoint", "callback_data": "subject:powerpoint"}]
        ]
        return send(chat_id, "📚 اختر المادة التي تريد حل أسئلتها:", {"inline_keyboard": keyboard})

    if state.get("mode") == "pick":
        try:
            n = int(text)
            categories = state.get("categories", [])
            if not (1 <= n <= len(categories)):
                raise ValueError()
        except ValueError:
            return send(chat_id, "أرسل رقم مادة صحيحاً من القائمة.")

        category = categories[n - 1]
        questions = [q for q in get_questions() if q.get("category") == category]

        if not questions:
            return send(chat_id, "لا توجد أسئلة صالحة لهذه المادة.")

        minutes = int(PROPERTIES.get("QUIZ_MINUTES", 30))
        now = int(time.time() * 1000)

        exam = {
            "mode": "exam",
            "category": category,
            "questions": questions,
            "index": 0,
            "score": 0,
            "started": now,
            "deadline": now + (minutes * 60000)
        }

        save_state(chat_id, exam)
        return ask_question(chat_id, exam)

    if state.get("mode") == "exam":
        answer = text.upper()
        if answer not in ["A", "B", "C", "D"]:
            return send(chat_id, "اضغط أحد أزرار الإجابة أو أرسل A أو B أو C أو D.")

        return process_exam_answer(chat_id, state, answer)

    return send(chat_id, "اكتب /start للبدء أو /quiz لاختيار اختبار.")


def answer_callback_query(callback_id, text=""):
    token = PROPERTIES.get("BOT_TOKEN")
    requests.post(
        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "callback_query_id": callback_id,
            "text": text
        })
    )


def handle_callback_query(callback):
    chat_id = callback["message"]["chat"]["id"]
    data = str(callback.get("data") or "")
    callback_id = callback["id"]

    if data.startswith("deletepage:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        answer_callback_query(callback_id)
        page = int(data.replace("deletepage:", ""))
        return show_delete_page(chat_id, page)

    if data.startswith("admin:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")

        if data == "admin:add":
            answer_callback_query(callback_id)
            return send(chat_id, "لإضافة سؤال جديد، أرسل الأمر /add")

        if data == "admin:edit":
            answer_callback_query(callback_id)
            return show_edit_page(chat_id, 0)

        if data == "admin:delete":
            answer_callback_query(callback_id)
            return show_delete_page(chat_id, 0)

        if data == "admin:time":
            answer_callback_query(callback_id)
            return send(chat_id, "أرسل الأمر /time متبوعًا بالمدة بالدقائق.\nمثال: /time 30")

    if data == "check_subscription":
        answer_callback_query(callback_id)
        if is_user_subscribed(chat_id):
            return send(chat_id, "✅ تم التحقق من اشتراكك بنجاح. تفضل باستخدام البوت.", main_keyboard(chat_id))
        return send_subscription_prompt(chat_id)

    if not is_user_subscribed(chat_id):
        answer_callback_query(callback_id, "اشترك بالقناة أولًا.")
        return send_subscription_prompt(chat_id)

    state = get_state(chat_id)

    if data.startswith("subject:") or data.startswith("section:"):
        category = ""
        subjects = {
            "basics": None,
            "excel": "Excel",
            "word": "Word",
            "powerpoint": "PowerPoint"
        }
        sections = {
            "components": "مكونات الحاسوب",
            "internet": "الإنترنت",
            "windows": "Windows",
            "database": "قواعد البيانات",
            "email": "الإيميل"
        }

        if data.startswith("subject:"):
            subject = data[8:]
            if subject == "basics":
                answer_callback_query(callback_id, "تم اختيار أساسيات الحاسوب")
                keyboard = [
                    [{"text": "🧩 مكونات الحاسوب", "callback_data": "section:components"}],
                    [{"text": "🌐 الإنترنت", "callback_data": "section:internet"}],
                    [{"text": "🪟 Windows", "callback_data": "section:windows"}],
                    [{"text": "🗄️ قواعد البيانات", "callback_data": "section:database"}],
                    [{"text": "📧 الإيميل", "callback_data": "section:email"}]
                ]
                return send(chat_id, "💻 اختر قسم أساسيات الحاسوب:", {"inline_keyboard": keyboard})
            category = subjects.get(subject)
        else:
            category = sections.get(data[8:])

        answer_callback_query(callback_id, "تم اختيار القسم")

        if not category:
            return send(chat_id, "القسم غير معروف.")

        questions = [q for q in get_questions() if q.get("category") == category]

        if not questions:
            return send(
                chat_id,
                f"لا توجد أسئلة مضافة حاليًا في قسم {category}.\nسيتمكن الطالب من الاختبار بعد إضافة أسئلة هذا القسم."
            )

        part_size = 25
        part_count = -(-len(questions) // part_size)  # Ceiling division

        save_state(chat_id, {
            "mode": "pickPart",
            "category": category,
            "partCount": part_count
        })

        keyboard = []
        for i in range(part_count):
            start = i * part_size
            count = min(part_size, len(questions) - start)
            keyboard.append([{"text": f"الجزء {i + 1} ({count} سؤال)", "callback_data": f"part:{i}"}])

        return send(
            chat_id,
            f"📚 القسم: {category}\n📝 مجموع الأسئلة: {len(questions)}\n\nاختر الجزء الذي تريد اختباره:",
            {"inline_keyboard": keyboard}
        )

    if data.startswith("editpage:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        answer_callback_query(callback_id)
        page = int(data.replace("editpage:", ""))
        return show_edit_page(chat_id, page)

    if data.startswith("editq:"):
        if not is_admin(chat_id):
            return answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
        # إضافة منطق التعديل المطلوب لـ editq هنا
        import json
import logging
import threading
import time
from datetime import datetime, timezone
import requests

logger = logging.getLogger(__name__)

# افتراض الدعم الأساسي والمتغيرات (SCRIPT_LOCK, PROPERTIES, send, answer_callback_query, إلخ)

def handle_callback_query_continued(callback):
    chat_id = callback["message"]["chat"]["id"]
    data = str(callback.get("data") or "")
    callback_id = callback["id"]
    state = get_state(chat_id)

    # اختيار سؤال للتعديل
    if data.startswith("editq:"):
        question_id = data[len("editq:"):].strip()
        question = next((q for q in get_questions() if str(q.get("id")) == question_id), None)

        if not question:
            answer_callback_query(callback_id, "لم يُعثر على السؤال.")
            return send(chat_id, "تعذر العثور على السؤال. افتح قائمة التعديل من جديد.")

        save_state(chat_id, {
            "mode": "edit",
            "step": "field",
            "questionId": question_id
        })

        answer_callback_query(callback_id)

        return send(
            chat_id,
            f"✏️ اختر الحقل الذي تريد تعديله:\n\n📚 المادة: {question.get('category')}\n❓ السؤال: {question.get('question')}",
            {
                "inline_keyboard": [
                    [{"text": "📝 نص السؤال", "callback_data": "editfield:question"}],
                    [{"text": "📚 المادة", "callback_data": "editfield:category"}],
                    [{"text": "🔤 الخيارات الأربعة", "callback_data": "editfield:options"}],
                    [{"text": "✅ الإجابة الصحيحة", "callback_data": "editfield:answer"}],
                    [{"text": "💡 شرح الإجابة", "callback_data": "editfield:explanation"}],
                    [{"text": "❌ إلغاء التعديل", "callback_data": "editcancel"}]
                ]
            }
        )

    # اختيار حقل التعديل
    if data.startswith("editfield:"):
        if not is_admin(chat_id):
            answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
            return

        if state.get("mode") != "edit" or state.get("step") != "field":
            answer_callback_query(callback_id, "انتهت صلاحية التعديل.")
            return send(chat_id, "افتح قائمة التعديل من جديد عبر /admin.")

        field = data[len("editfield:"):]
        fields = {
            "question": "نص السؤال",
            "category": "المادة",
            "options": "الخيارات الأربعة",
            "answer": "الإجابة الصحيحة",
            "explanation": "شرح الإجابة"
        }

        if field not in fields:
            answer_callback_query(callback_id, "حقل غير صالح.")
            return

        state["step"] = "value"
        state["editField"] = field
        save_state(chat_id, state)

        answer_callback_query(callback_id)

        if field == "options":
            return send(
                chat_id,
                "🔤 أرسل الخيارات الأربعة برسالة واحدة، وافصل بينها بالرمز | \nمثال: Internet | WAN | LAN | PAN"
            )

        if field == "answer":
            return send(
                chat_id,
                "✅ أرسل حرف الإجابة الصحيحة فقط: A أو B أو C أو D."
            )

        if field == "explanation":
            return send(
                chat_id,
                "💡 أرسل شرح الإجابة الجديد.\nإذا تريد مسح الشرح، أرسل: مسح"
            )

        return send(
            chat_id,
            f"✏️ أرسل القيمة الجديدة لحقل: {fields[field]}."
        )

    # إلغاء التعديل
    if data == "editcancel":
        if not is_admin(chat_id):
            answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
            return

        clear_state(chat_id)
        answer_callback_query(callback_id, "تم إلغاء التعديل.")
        return send(chat_id, "تم إلغاء التعديل، ولم تُحفظ أي تغييرات.")

    # اختيار السؤال للحذف
    if data.startswith("deleteq:"):
        if not is_admin(chat_id):
            answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
            return

        question_id = data[len("deleteq:"):].strip()
        question = next((q for q in get_questions() if str(q.get("id")) == question_id), None)

        if not question:
            answer_callback_query(callback_id, "لم يُعثر على السؤال.")
            return send(chat_id, "لم يُعثر على السؤال. افتح قائمة الحذف من جديد.")

        answer_callback_query(callback_id)

        return send(
            chat_id,
            f"⚠️ هل أنت متأكد من حذف هذا السؤال؟\n\n📚 المادة: {question.get('category')}\n❓ السؤال: {question.get('question')}\n🔑 المعرّف: {question_id}",
            {
                "inline_keyboard": [
                    [{"text": "🗑️ نعم، احذف السؤال", "callback_data": f"confirmdeleteq:{question_id}"}],
                    [{"text": "❌ إلغاء", "callback_data": "canceldeleteq"}]
                ]
            }
        )

    # إلغاء الحذف
    if data == "canceldeleteq":
        answer_callback_query(callback_id, "تم إلغاء الحذف.")
        return send(chat_id, "تم إلغاء العملية. لم يُحذف أي سؤال.")

    # تأكيد الحذف
    if data.startswith("confirmdeleteq:"):
        if not is_admin(chat_id):
            answer_callback_query(callback_id, "هذا الأمر مخصص للمشرف.")
            return

        question_id = data[len("confirmdeleteq:"):].strip()
        question = next((q for q in get_questions() if str(q.get("id")) == question_id), None)

        if not question:
            answer_callback_query(callback_id, "لم يُعثر على السؤال.")
            return send(chat_id, "لم يُعثر على السؤال. لم يتم حذف شيء.")

        deleted = json.loads(PROPERTIES.get("DELETED_QUESTIONS", "[]"))

        if question_id not in deleted:
            deleted.append(question_id)
            PROPERTIES["DELETED_QUESTIONS"] = json.dumps(deleted)

        answer_callback_query(callback_id, "تم حذف السؤال.")
        return send(
            chat_id,
            f"✅ تم حذف السؤال بنجاح.\n\n📚 المادة: {question.get('category')}\n❓ السؤال: {question.get('question')}"
        )

    # اختيار مادة عند إضافة سؤال
    if data.startswith("cat:"):
        if state.get("mode") != "pick":
            answer_callback_query(callback_id, "ابدأ اختبارًا جديدًا")
            return send(chat_id, "ابدأ اختبارًا جديدًا باستخدام /quiz")

        try:
            index = int(data[4:])
            categories = state.get("categories", [])
            if index < 0 or index >= len(categories):
                raise ValueError()
        except ValueError:
            answer_callback_query(callback_id, "اختيار غير صالح")
            return send(chat_id, "اختيار المادة غير صالح.")

        category = str(categories[index]).strip()
        # مطابقة القسم مع تنظيف المسافات لضمان عدم فشل الجلب
        questions = [q for q in get_questions() if str(q.get("category", "")).strip() == category]

        if not questions:
            answer_callback_query(callback_id, "لا توجد أسئلة")
            return send(chat_id, f"لا توجد أسئلة مضافة حالياً في قسم ({category}).")

        part_size = 25
        part_count = -(-len(questions) // part_size)

        save_state(chat_id, {
            "mode": "pickPart",
            "category": category,
            "partCount": part_count
        })

        keyboard = []
        for i in range(part_count):
            start = i * part_size
            count = min(part_size, len(questions) - start)
            keyboard.append([{"text": f"الجزء {i + 1} ({count} سؤال)", "callback_data": f"part:{i}"}])

        answer_callback_query(callback_id, "تم اختيار المادة")
        return send(
            chat_id,
            f"📚 المادة: {category}\n📝 عدد الأسئلة: {len(questions)}\n\nاختر الجزء الذي تريد اختباره:",
            {"inline_keyboard": keyboard}
        )

    # اختيار الجزء (part:)
    if data.startswith("part:"):
        if state.get("mode") != "pickPart":
            answer_callback_query(callback_id, "اختر المادة أولاً")
            return send(chat_id, "ابدأ اختباراً جديداً باستخدام /quiz")

        try:
            part_index = int(data[5:])
            if part_index < 0 or part_index >= state.get("partCount", 0):
                raise ValueError()
        except ValueError:
            answer_callback_query(callback_id, "اختيار غير صالح")
            return send(chat_id, "الجزء المختار غير صالح.")

        category = str(state.get("category", "")).strip()
        all_questions = [q for q in get_questions() if str(q.get("category", "")).strip() == category]

        part_size = 25
        start = part_index * part_size
        questions = all_questions[start:start + part_size]

        if not questions:
            answer_callback_query(callback_id, "لا توجد أسئلة")
            return send(chat_id, "لا توجد أسئلة في هذا الجزء.")

        minutes = int(PROPERTIES.get("QUIZ_MINUTES", 30))
        now = int(time.time() * 1000)

        exam = {
            "mode": "exam",
            "category": f"{category} - الجزء {part_index + 1}",
            "questions": questions,
            "index": 0,
            "score": 0,
            "answers": [],
            "started": now,
            "deadline": now + (minutes * 60000)
        }

        save_state(chat_id, exam)
        answer_callback_query(callback_id, "تم اختيار الجزء")
        return ask_question(chat_id, exam)

    # الإجابة عن سؤال (ans:)
    if data.startswith("ans:"):
        acquired = SCRIPT_LOCK.acquire(timeout=10)
        if not acquired:
            answer_callback_query(callback_id, "انتظر لحظة ثم حاول مجدداً")
            return

        try:
            current_state = get_state(chat_id)

            if current_state.get("mode") != "exam":
                answer_callback_query(callback_id, "لا يوجد اختبار نشط")
                return

            parts = data.split(":")
            try:
                question_index = int(parts[1])
            except (IndexError, ValueError):
                answer_callback_query(callback_id, "إجابة غير صالحة")
                return

            answer = str(parts[2] if len(parts) > 2 else "").upper()

            if question_index != current_state.get("index"):
                answer_callback_query(callback_id, "هذا السؤال انتهى بالفعل")
                return

            if answer not in ["A", "B", "C", "D"]:
                answer_callback_query(callback_id, "إجابة غير صالحة")
                return

            if current_state.get("answerLocked") is True:
                answer_callback_query(callback_id, "تم تسجيل إجابتك مسبقاً")
                return

            current_state["answerLocked"] = True
            save_state(chat_id, current_state)

            answer_callback_query(callback_id, "تم تسجيل الإجابة")
            return process_exam_answer(chat_id, current_state, answer)

        finally:
            SCRIPT_LOCK.release()

    answer_callback_query(callback_id, "هذا الزر غير معروف")


def process_exam_answer(chat_id, state, answer):
    if (time.time() * 1000) >= state.get("deadline", 0):
        return finish_exam(chat_id, state, timed_out=True)

    q = state["questions"][state["index"]]

    if "answers" not in state:
        state["answers"] = []

    student_answer = str(answer).strip().upper()
    correct_answer = str(q.get("answer", "")).strip().upper()
    is_correct = (student_answer == correct_answer)

    state["answers"].append({
        "question": q.get("question"),
        "options": q.get("options"),
        "studentAnswer": student_answer,
        "correctAnswer": correct_answer,
        "isCorrect": is_correct,
        "explanation": q.get("explanation", "")
    })

    if is_correct:
        state["score"] = state.get("score", 0) + 1

    state["index"] += 1

    if state["index"] >= len(state["questions"]):
        return finish_exam(chat_id, state, timed_out=False)

    save_state(chat_id, state)
    return ask_question(chat_id, state)


def finish_exam(chat_id, state, timed_out=False):
    total = len(state.get("questions", []))
    answers = state.get("answers", [])
    answered = len(answers)
    correct = state.get("score", 0)
    wrong = answered - correct
    unanswered = total - answered

    score100 = round(correct * 100 / total) if total > 0 else 0

    student = get_telegram_student_info(chat_id)
    duration_seconds = max(0, round((time.time() * 1000 - state.get("started", 0)) / 1000))

    save_exam_result({
        "userId": str(chat_id),
        "username": student.get("username"),
        "name": student.get("name"),
        "category": state.get("category", "غير محددة"),
        "score": score100,
        "correct": correct,
        "total": total,
        "duration": f"{duration_seconds // 60} دقيقة و{duration_seconds % 60} ثانية",
        "completedAt": datetime.now(timezone.utc).isoformat()
    })
    report = (
        "⏰ انتهى وقت الاختبار!\n\n" if timed_out else "🎉 انتهى الاختبار!\n\n"
    )
    report += (
        f"📚 المادة: {state.get('category')}\n"
        f"📝 مجموع الأسئلة الكلي: {total}\n"
        f"📌 الأسئلة التي أُجيب عنها: {answered}\n"
        f"⏳ الأسئلة التي لم يُجب عنها: {unanswered}\n"
        f"✅ الإجابات الصحيحة: {correct}\n"
        f"❌ الإجابات الخاطئة: {wrong}\n"
        f"📊 الدرجة: {score100} من 100\n"
    )

    letters = ["A", "B", "C", "D"]
    wrong_answers = [a for a in answers if not a.get("isCorrect")]

    if not wrong_answers:
        report += "\n🏆 لا توجد إجابات خاطئة للمراجعة."
    else:
        report += "\n📋 مراجعة الأسئلة الخاطئة فقط:\n"
        for a in wrong_answers:
            try:
                student_index = letters.index(a.get("studentAnswer"))
                student_text = a["options"][student_index]
            except (ValueError, IndexError):
                student_text = a.get("studentAnswer")

            try:
                correct_index = letters.index(a.get("correctAnswer"))
                correct_text = a["options"][correct_index]
            except (ValueError, IndexError):
                correct_text = a.get("correctAnswer")

            explanation_text = a.get("explanation") or "لم يُضف شرح لهذا السؤال بعد."

            report += (
                f"\n❌ السؤال: {a.get('question')}\n"
                f"🔸 إجابتك: {student_text}\n"
                f"✅ الإجابة الصحيحة: {correct_text}\n"
                f"💡 الشرح: {explanation_text}\n"
            )

    clear_state(chat_id)

    chunk_size = 3000
    for i in range(0, len(report), chunk_size):
        chunk = report[i:i + chunk_size]
        is_last = (i + chunk_size >= len(report))
        send(chat_id, chunk, main_keyboard(chat_id) if is_last else None)


def is_user_subscribed(user_id):
    token = PROPERTIES.get("BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/getChatMember?chat_id=@hibhibcomp&user_id={user_id}"

    try:
        response = requests.get(url)
        result = response.json()

        if not result.get("ok") or not result.get("result"):
            logger.error(f"Subscription check failed: {response.text}")
            return False

        member = result["result"]
        status = member.get("status")

        return (
            status in ["creator", "administrator", "member"] or
            (status == "restricted" and member.get("is_member") is True)
        )
    except Exception as error:
        logger.error(f"Subscription error: {error}")
        return False


def send_subscription_prompt(chat_id):
    return send(
        chat_id,
        "🔒 لاستخدام البوت، يجب الاشتراك بقناتنا أولًا.\n\n"
        "1️⃣ اشترك بالقناة من الزر أدناه.\n"
        "2️⃣ ارجع إلى البوت واضغط «تحققت من الاشتراك».",
        {
            "inline_keyboard": [
                [{"text": "📢 الاشتراك بالقناة", "url": "https://t.me/hibhibcomp"}],
                [{"text": "✅ تحققت من الاشتراك", "callback_data": "check_subscription"}]
            ]
        }
    )
def get_base_question_data():
    data = [
        ["Word", "From which tab can WordArt be inserted in Microsoft Word?", "Layout", "View", "Insert", "Design", "C"],
        ["الإنترنت", "What is the protocol responsible for transferring files over the network?", "TCP", "HTTP", "IP", "FTP", "D"],
        ["الإنترنت", "How can passwords be better protected?", "Do not share your password with others", "Enable Two-Factor Authentication (2FA)", "Change password every year", "None of above", "B"],
        ["Word", "From which tab can a page picture background be inserted in Microsoft Word?", "Insert", "View", "Page layout", "Design", "D"],
        ["Word", "Which tab allows you to run spelling and grammar check in Microsoft Word?", "View", "Design", "Layout", "Review", "D"],
        ["قواعد البيانات", "What is meant by DDL in databases?", "Data definitions language", "Data manipulation language", "Data control language", "None of above", "A"],
        ["قواعد البيانات", "What is meant by DCL in databases?", "Data control language", "Data definition language", "Data manipulation language", "None of above", "A"],
        ["Excel", "Where are the control buttons located in Microsoft Excel?", "Formula bar", "Title bar", "Menu bar", "Status bar", "B"],
        ["الإيميل", "When forwarding all incoming emails to another person, which option should be used?", "Forward", "Reply", "Reply all", "New send", "A"],
        ["الإنترنت", "What is URL?", "Host name", "Source and type", "Path file", "All of above", "D"],
        ["الإنترنت", "What is a responsive website?", "A site dedicated to quickly checking email", "A website that can adapt to devices", "Password-protected website", "A device that connects devices together via cables", "B"],
        ["الإنترنت", "Internet is:", "Instant messaging", "Web browser", "Email messages", "Global network", "D"],
        ["Windows", "In case of accidentally deleting a file, where can it be restored in the operating system?", "Task manager", "Recycle bin", "File manager", "Task bar", "B"],
        ["Excel", "How do I rotate text 45 degrees in Excel?", "Text group in the Insert tab and set the text size to 45", "Change the text size to 45 from the Font group on the Home tab", "Rotate the text to 45 degrees from the Alignment group on the Home tab", "Rotate the text to 45 degrees from the editing group on the Home tab", "C"],
        ["Excel", "From which tab can you add a background in Microsoft Excel?", "Insert", "Page layout", "View", "Review", "B"],
        ["Excel", "What does the ($) indicate in Microsoft Excel?", "Comma", "Currency", "Number", "Printed", "B"],
        ["Excel", "If a value in the table changes, does it affect the chart value in Microsoft Excel?", "Yes, it updates automatically", "No, it does not affect it", "If single changes", "None of above", "A"],
        ["الإنترنت", "The connection is made with _____ to build internet networks.", "Satellite", "ADSL", "ISDN", "All of above", "D"],
        ["Word", "What shortcut Ctrl + B?", "Make text italic", "Make text underline", "Make text Bold", "Duplicate text", "C"],
        ["Word", "From which tab can a symbol be inserted in Word?", "Home", "Insert", "Layout", "Design", "B"],
        ["Excel", "First Cell in Excel?", "A0", "A1", "B1", "A10", "B"],
        ["الإيميل", "How can an important message be marked in email?", "Save as draft", "Add a star", "Mark as attachment", "Mark as unread", "B"],
        ["الإنترنت", "What is meant by HTTPS?", "Unsecured version of HTTP", "Secured version of HTTP", "File lock protocol", "None of above", "B"],
        ["Excel", "It is acceptable to let long text overflow into adjacent cells in a worksheet when ...", "Data will be entered into adjacent cells", "No data will be entered into adjacent cells", "Both", "None of above", "B"],
        ["Excel", "How do you auto-fit column width in Excel?", "Double-click on the column name in the column header", "Double-click on the cell pointer in the worksheet", "Double-click on the right border of the column in the column header", "Double-click on the left border of the column in the column header", "C"],
        ["Excel", "If you want to fill cells with months in sequence (January, February, ...), use:", "Auto fill", "Series fill", "Custom fill", "None of above", "B"],
        ["Excel", "From where can you insert a picture in Excel?", "Insert tab", "Review tab", "View tab", "Format tab", "A"],
        ["Excel", "You can change sheet orientation from portrait to landscape in Excel using:", "View tab", "Review tab", "Page layout tab", "Insert tab", "C"],
        ["Excel", "What shortcut saves in Excel?", "Ctrl + S", "Ctrl + E", "Ctrl + P", "Ctrl + V", "A"],
        ["Excel", "How do you fill cells with color in Excel?", "Formatting tab", "Design tab", "From Fill color in the toolbar", "None of above", "C"],
        ["Excel", "Where is the file name written in Excel?", "In the cells", "In title bar", "In formula bar", "In menu bar", "B"],
        ["Excel", "What default name file Excel?", "Document", "Book1", "Excel1", "Newfile", "B"],
        ["Excel", "Which menu option can be used to split windows into two panes in Excel?", "Review > Window", "View > Window > Split", "Window > Split", "View > Split", "B"],
        ["Word", "MS-Word is:", "Web browser", "Program", "Application", "Operating system", "C"],
        ["Excel", "Which of the following is not related to editing a cell in Excel?", "F2", "Alt", "Ctrl", "Shift", "B"],
        ["Excel", "What happens when you press F12 in Excel?", "Open help window", "Open Save As window", "Open update window", "Switch between ribbon tools", "B"],
        ["Windows", "Where is the taskbar located on the Windows screen?", "At the bottom of the screen", "At the top of the screen", "Start menu", "On the desktop", "A"],
        ["Word", "Headers and footers can include text, graphics, and ...", "Current date", "Current time", "Page number", "All of above", "D"],
        ["Excel", "In Excel, a pie chart is used to ...", "Show the contribution of each value to a total", "Compare values across categories", "Show trends of values across time or categories", "Show the trend in values across their numbering", "A"],
        ["PowerPoint", "Can PowerPoint display data from any of the following Microsoft add-in programs?", "Equation editor", "Organization chart", "Photo album", "All of these", "D"],
        ["الإنترنت", "Which of these options allows users to store and access files via the internet?", "HDD", "SSD", "Google Drive", "CD", "C"],
        ["Excel", "The extension of a file saved in Excel is of type ...", "xld", "xl", "xlsx", "doc", "C"],
        ["Word", "What does Document outline view represent?", "Full-screen reading", "Displays a heading structure at different levels", "Print preview with margins", "Display with margins", "B"],
        ["Excel", "The small black square in the bottom-right corner of an active cell or range represents ...", "Copy handle", "Fill handle", "Auto handle", "None of above", "B"],
        ["الإنترنت", "What is a typical advantage of online learning?", "Always requires classroom attendance", "High travel time and cost", "Learning is quick and easy available every time", "Documents cannot be downloaded to read later", "C"],
        ["Word", "A hyperlink is inserted from the tab:", "Insert > hyperlink", "Review > hyperlink", "View > hyperlink", "Layout > hyperlink", "A"],
        ["Word", "Keyboard shortcut to open the Font dialog box in Word?", "Ctrl + F", "Ctrl + D", "Ctrl + T", "Ctrl + Shift + F", "B"],
        ["Excel", "To insert a new column between column A and column B, click the button:", "Insert columns from the Editing group", "Insert columns from the Insert group", "Insert columns from the Cells group", "None of above", "C"],
        ["PowerPoint", "What menu provides options such as animation, custom animation, slide transition?", "Insert", "Toolbar", "Format", "Slide show", "D"],
        ["Excel", "How to remove cell borders?", "Selecting 'None' from the Format Cells", "Open list border and the formatting toolbar, then select borders, then choose 'No Border'", "Both", "None of above", "C"],
        ["أساسيات الحاسوب", "what do the letters C,D,E represent in operating system", "folders", "Drives", "shortuct", "All of the above", "B"],
        ["Word", "Microsoft Word is ____ software", "Application", "Compiler", "System", "Programming", "A"],
        ["أساسيات الحاسوب", "Which of the following best describes Serifs?", "Serifs on characters help to differentiate between similar looking letters", "Serifs fonts are best for viewing test at a distance", "Serifs are fine cross strokes that appear at the bottom and top at letter", "Serif font are very simple in appearance", "C"],
        ["أساسيات الحاسوب", "What is HTML?", "HyperText Markup Language", "HighText Machine Language", "HyperTest Management Language", "HyperTransfer Markup Language", "A"],
        ["PowerPoint", "In PowerPoint presentation...", "Sound clips can be inserted but not movie clips", "Movie clips can be inserted but not sound clips", "Both cannot be inserted", "Both can be inserted", "D"],
        ["Excel", "When a range is selected, how can you activate the previous cell?", "Press the Alt key", "Press Enter", "Press Tab", "None of above", "D"],
        ["أساسيات الحاسوب", "Which of the following is considered secondary storage?", "RAM", "CPU", "Hard Disk Drive", "Cache Memory", "C"],
        ["Word", "To add a comment in Word 2016, you should", "Go to the Insert tab and select Comment", "Highlight text, Right-click, and select New Comment", "Go to the Review tab and click New Comment", "Both B and C", "D"],
        ["Word", "To insert an image click the button", "Image from a list of illustrations", "An image of a list of drawers", "Image of page layout menu", "All answers given are incorrect", "A"],
        ["Excel", "In Microsoft Excel, pie chart is used for", "To show the trend in values across two dimensions in a continuous curve", "To compare values across categories", "To show the trend of values over time or across categories", "To show the contribution of each value relative to the total", "D"],
        ["Excel", "To insert a new column between Column A and Column B, press the button:", "Insert columns from the group Edit", "Insert columns from the group Insert.", "Insert columns from the group Cells.", "All the answers given are incorrect", "C"],
        ["أساسيات الحاسوب", "Which of the following statement is false?", "If you choose to select from one of the pre-made slide layouts, you can change the positioning", "If you choose to select from the pre-made slide layouts, you cannot delete the objects in the layout", "Blank Slide is at the top of the ‘Content Layouts’ area in the Slide Layout panel", "All of above are false statements", "B"],
        ["PowerPoint", "To start Microsoft PowerPoint application", "Click on Start >> Programs >> All Programs >> Microsoft PowerPoint", "Hit Ctrl + R then type ppoint.exe and Enter", "Click Start >> Run then type powerpnt then press Enter", "All of above", "A"],
        ["Excel", "To close the current workbook in use, click on the option....... in the....... menu.", "Close, View", "Close, Home Page", "Close, Office", "Close, Title Bar", "C"],
        ["الإنترنت", "What is an Internet search engine?", "A program that scans web pages for viruses.", "A program that updating Web page (refresher).", "A program that searches the Internet for specific words, images or videos.", "Program that creates a network connection.", "C"],
        ["أساسيات الحاسوب", "Which of the following technologies provides the greatest benefit to a blind computer user?", "Graphical User Interface", "new parts combination program", "Wireless Networks", "Healthy mouse and keyboard", "B"],
        ["Excel", "Ctrl + D shortcut key in Excel will:", "Open the font dialog box", "Apply double underline for the active cell", "Fill down in the selection", "None of above", "C"],
        ["الإنترنت", "Any website can be accessed easily via:\"", "search engine", "word", "power point", "internet explorer", "A"],
        ["أساسيات الحاسوب", "If the setting locks the taskbar is on, then _______", "Taskbar can be moved to the top, right, middle or left of the screen.", "Taskbar can be hiding from the screen.", "Taskbar cannot be moved to the top, right or left of the screen.", "All the provided answers are correct.", "C"],
        ["Excel", "What happens when you press Ctrl + X after selecting some cells in Excel?", "The cell content of selected cells disappear from cell and stored in clipboardا", "The cells selected are marked for cutting", "The selected cells are deleted and the cells are shifted left", "The selected cells are deleted and cells are shifted up", "B"],
        ["أساسيات الحاسوب", "File extensions are used in order to", "name the file", "ensure the file name is not lost", "identify the file", "identify the file type", "C"],
        ["أساسيات الحاسوب", "What is the short form of CPU?", "Central Process Unit", "Central Processing Unit", "Computer Processing Unit", "Computer Process Unit", "B"],
        ["PowerPoint", "What's the best way to design the layout for your slides?", "Create layouts for slides, handouts and notes using the Master Layout dialog box in slide master view", "For each new slide, select a layout from the Slide Layout task pane", "Apply templates from the Slide Design task pane", "None of above", "A"],
        ["أساسيات الحاسوب", "To insert the logo graphic, click the button", "clip art", "image", "shapes", "All answers given are incorrect", "D"],
        ["أساسيات الحاسوب", "Which of the following are physical devices of a computer?", "Hardware", "Software", "System Software", "Package", "A"],
        ["Excel", "All mathematical operations in Excel 2019 must begin with?", "Multiplication sign", "Minus sign", "Plus sign", "Equals sign", "D"],
        ["أساسيات الحاسوب", "Which of the following is an input device?", "Monitor", "Printer", "Keyboard", "Speaker", "C"],
        ["الإنترنت", "Using the Internet to download the latest version of a program is an example of", "backup", "software updating", "quality setting", "system maintenance", "B"],
        ["أساسيات الحاسوب", "Which of the following is considered an operating system?", "Microsoft Word", "Google Chrome", "Windows 10", "Oracle", "C"],
        ["Excel", "To insert a new sheet, click the button", "Insert, paper insert", "Page layout, insert, insert sheet", "Home, Insert, Insert Sheet", "All answers given are incorrect", "C"],
        ["أساسيات الحاسوب", "Which storage device uses magnetic technology?", "SSD", "RAM", "Hard Disk Drive", "ROM", "C"],
        ["أساسيات الحاسوب", "Which of the following is not a computer virus?", "Trojans", "Worms", "Ransomware", "Linux", "D"],
        ["الإنترنت", "Which protocol is commonly used to secure data transmission over the internet?", "HTTP", "FTP", "HTTPS", "SMTP", "A"],
        ["Excel", "In Excel 2019, which function is used to calculate the average of a range of cells?", "SUM", "AVERAGE", "COUNT", "MAX", "B"],
        ["أساسيات الحاسوب", "Auto clipart is a feature that", "Scans your presentation for incorrect spelling in Word Arts objects", "Scans your presentation for incorrect spelling in your words on each slide", "Automatically places clipart in your presentation", "All of above", "C"],
        ["Word", "How can you change page orientation?", "Go to File > Page Setup", "Go to Home > Orientation", "Go to the Layout tab, and choose Orientation", "Press Ctrl + Shift + A", "C"],
        ["أساسيات الحاسوب", "In order to edit a chart, you can _______", "Triple click the chart object", "Click and drag the chart object", "Double click the chart object", "Click the chart object", "C"],
        ["Word", "Header and footer option allows us to insert __________", "Page number", "Current date", "Current time", "All of the above", "D"],
        ["أساسيات الحاسوب", "The ...... works with the standard Copy and Paste commands.", "View tab", "Paragraph dialog box", "Office Clipboard", "All of a bove", "C"],
        ["أساسيات الحاسوب", "In the following paragraph, the table...", "The lengths of the categories automatically change to accommodate the new value", "The values may not be changed as long as the layout is drawn", "All answers given here are incorrect", "The value changes in the table but not the layout", "A"],
        ["الإنترنت", "If you receive a message from a friend sent to a number of people and you want to respond to everyone, do you use the command...", "Forward", "Reply", "Signature", "Reply to all", "B"],
        ["Excel", "In MS Excel, formulas must always begin with a:", "$", "=", "@", "_", "B"],
        ["أساسيات الحاسوب", "To insert specific text on each page, click the... button.", "Header and footer from the Page Layout", "Header and footer from the View menu", "Header and footer from the Insert", "All the answers given are incorrect", "C"],
        ["الإنترنت", "What is Email short for?", "Express mail", "Easy mail", "Enhanced mail", "Electronic mail", "D"],
        ["Excel", "How to convert the number listed in a divided cell into a group of ranks in Microsoft Excel?", "Home tab -> Then we click on the time icon", "Home tab -> Then we click on the comma symbol", "Home tab -> Then we click on the percentage symbol", "Home tab -> Then we click the symbol to increase decimal places", "B"],
        ["PowerPoint", "In Microsoft PowerPoint, which view is best used to reorder and organize slides?", "Normal view", "Slide Sorter view", "Reading view", "Slide Show view", "B"],
        ["Excel", "How to change the width of column (B) to width (30) in a Microsoft Excel 2019 workbook?", "We select the column first, then from the Width menu we choose Instruct to change the column width.", "We select the column first, then from the home page menu we choose the Format instruction, then click on the Column Width...", "We double click inside any cell in column (B) with the left mouse button, and a menu appears in which we type the number.", "We select the column first, then from the checklist we choose Instruct to change the column width.", "B"],
        ["Excel", "How can I insert a new column between column A and B in a worksheet in Microsoft Excel 2019?", "We select column (A), then from the main page menu we choose the Insert command, then click on the Insert Sheet Columns command", "We select column (B), then from the main page menu we choose the Insert command, then click on the Insert Sheet Columns command.", "We select column (A), then from the View menu, we choose the Insert command, then click on the Insert Sheet Columns command.", "We select column (B), then from the View menu, we choose the Insert command, then click on the Insert Sheet Columns command.", "B"],
        ["Excel", "While Finding and Replacing some data in Excel, which of the following statement is valid?", "Excel does not have option to match case for find", "Both are valid", "None are valid", "You can Find and Replace within the sheet or workbook", "D"],
        ["Word", "Which tab is used to insert a table in Word 2016?", "Home", "Insert", "Design", "Layout", "B"],
        ["PowerPoint", "Animation schemes can be applied to .......... in the presentation", "All slides", "Select slides", "Current slide", "All of the above", "D"],
        ["Excel", "What is the definition of browser?", "A program used to display html files on the Internet", "A program used to create HTML files on the Internet", "A program used to draw HTML files on the Internet", "A program used to protect the computer", "A"],
        ["أساسيات الحاسوب", "Which of the following is an example of an application software?", "Windows 10", "Linux", "Microsoft Word", "macOS", "C"],
        ["PowerPoint", "A presentation program developed by Microsoft is...", "Excel", "Word", "PowerPoint", "Access", "C"],
        ["أساسيات الحاسوب", "Which of the following devices can transfer data from one person to another via a telephone line without using a computer?", "Telephone mail", "E-mail", "Fax", "Telex", "C"],
        ["PowerPoint", "Which of the following tools enable you to add text to a slide without using the standard placeholders?", "Text box tool", "Line tool", "Fill color", "Auto shapes tool", "A"],
        ["الإنترنت", "primary purpose of protecting data online is...", "Privacy protection of personal data", "Protecting companies from industrial espionage", "Establishing standards for how programs should be written", "hacker preventing", "A"],
        ["الإنترنت", "Which network device is used to connect different networks together?", "Switch", "Hub", "Router", "Repeater", "C"],
        ["Excel", "The default name for files created in Excel 2019 is...", "Book", "Sheet", "Row", "Cell", "A"],
        ["أساسيات الحاسوب", "What is RAM?", "Read Access Memory", "Random Access Memory", "Run Access Memory", "Rate Access Memory", "B"],
        ["الإنترنت", "If a website is not loading correctly, which action might help resolve the issue?", "Delete your browsing history", "Turn off your computer", "Refresh the page or clear your browser cache", "Disable WiFi", "C"],
        ["أساسيات الحاسوب", "The Show group of the View tab is used to show ............", "Gridlines", "Ruler", "Pane Navigation", "All of the above", "D"],
        ["Excel", "To delete a new row between column A and column B, press the button", "Delete... Delete columns from the page group", "Delete... Delete columns from the group Insert", "Delete... Delete columns from the group Cells", "All the answers given are incorrect", "D"],
        ["الإنترنت", "Which of the following items you must have to send an email?", "Powerful computer", "The same Internet service as the recipient", "The recipient has the same data packets", "Recipient's email address", "D"],
        ["أساسيات الحاسوب", "Which component coordinates all computer activities?", "RAM", "CPU", "Hard Disk", "I/O Device", "B"],
        ["Excel", "To insert a new row between row 10 and row 11, click the button ..........", "Insert cells from the Insert group", "Insert cells from the Edit group", "Insert cells from the Cells group", "All answers given are incorrect", "D"],
        ["PowerPoint", "A file which contains readymade styles that can be used for presentations is called", "Auto style", "Template", "Wizard", "Pre-formatting", "B"],
        ["الإنترنت", "It is a device that controls the transmission of data to its destination on a computer network.", "Switch", "Router", "Hub", "Protocol", "B"],
        ["Word", "What is the default file extension for Microsoft Word 2016 documents?", ".txt", ".docx", ".pdf", ".xlsx", "B"],
        ["أساسيات الحاسوب", "Which key on the keyboard is used to cancel an action or close a dialog box?", "Enter", "Esc", "Spacebar", "Shift", "B"],
        ["الإنترنت", "What is the purpose of the firewall in a computer network?", "To speed up the internet connection", "To block unauthorized access", "To store user passwords", "To delete duplicate files", "B"],
        ["أساسيات الحاسوب", "Which of the following is firmware?", "Windows", "BIOS", "Excel", "Antivirus", "B"],
        ["Excel", "_______ writes the name of the current cell in use in Excel", "Formula bar", "Name box", "Address bar", "Toolbar", "B"],
        ["الإنترنت", "What is the purpose of the archive feature in email?", "To store old emails without deleting them", "To send emails to multiple recipients", "To delete junk emails", "To save a draft of an email", "A"],
        ["الإنترنت", "What does WAN stand for?", "Wide Area Network", "World Area Network", "Web Area Network", "Winchester Area Network", "A"],
        ["Excel", "The intersection of a row and column is called a:", "cell", "Worksheet", "dialog box", "sheet", "A"],
        ["PowerPoint", "If you have a PowerPoint show you created and want to send using email to another teacher you can add the show to your email message as a (an) __________", "Inclusion", "Attachment", "Reply", "Forward", "B"],
        ["الإنترنت", "What is an online account?", "Hard disk", "Personal internet profile", "Network router", "Programming language", "B"],
        ["أساسيات الحاسوب", "The taskbar is located __________", "on the start menu", "at the bottom of the screen", "on the quick launch toolbar", "at the top of the screen", "B"],
        ["Excel", "In Microsoft Excel, to fill a cell with a specific color or pattern, do the following", "From the main page, choose Format Cells, then Fill, then Pattern", "From the Format menu, choose Pattern", "From the Format menu, choose Font, then choose Pattern", "All answers given are incorrect", "A"],
        ["Excel", "What is the meaning of cell A15?", "Row 15 Column A", "Row A Column 15", "Column A1 Row 5", "All answers given are incorrect", "A"],
        ["PowerPoint", "Which of the following is the default page setup orientation for slides in PowerPoint?", "Landscape", "Vertical", "Portrait", "None of above", "A"],
        ["الإنترنت", "What does LAN stand for?", "Local Area Network", "Large Application Network", "Long Access Network", "Low Application Network", "A"],
        ["Excel", "In Excel 2019, to make text appear on multiple lines within a single cell, you should use...", "Merge Cells", "orientation", "Wrap Text", "Text Alignment", "C"],
        ["أساسيات الحاسوب", "What does 'exe' file extension stand for", "Exectruble file", "Executable file", "Express file", "Extensible file", "B"],
        ["Word", "To change the page orientation in Microsoft Word", "Go to File, Page Setup", "Go to Home, Orientation", "Go to the Layout tab and choose Orientation", "Press Ctrl + Shift", "C"],
        ["أساسيات الحاسوب", "Which of the following is an example of an Operating System?", "Microsoft Word", "Google Chrome", "Windows 10", "Adobe Photoshop", "C"],
        ["الإنترنت", "What does WWW stand for?", "World Wide Web", "World Whole Web", "Wide World Web", "Web World Wide", "A"],
        ["الإنترنت", "the unit that is a responsible for receiving data and messages from other devices within networks or another networks connected in the same network is", "sending unit", "receiving unit", "wide area network", "transmission media", "B"],
        ["أساسيات الحاسوب", "Left click in a suitable place in the desktop can be used to delete a file, folder or shortcut.", "True", "False", "All the provided answers are correct", "All the provided answers are incorrect", "B"],
        ["أساسيات الحاسوب", "File type at bmp", "Picture file", "Text file", "Sound file", "All the provided answers are correct", "A"],
        ["أساسيات الحاسوب", "Before you can perform any action on a file or folder, what must you do?", "Select the file or folder.", "Log into the computer again.", "Start File Explorer twice.", "Create a shortcut for the file or folder.", "A"],
        ["Excel", "To clear the cell contents, follow these steps", "We press the Clear button, in the Data menu", "we press the Clear button, in the Formats menu", "we press the Clear button, in the status bar", "we press the Clear button, in the Home menu", "D"],
        ["Word", "To insert a page break in Microsoft Word, you can press:", "Ctrl + Shift", "Ctrl + Enter", "Alt + Enter", "Shift + Enter", "B"],
        ["Word", "To insert a text box click the button...", "Text box from a group of cells", "Text box from a group of illustrations", "Text box from a group of text", "All the answers given are incorrect", "C"],
        ["Excel", "Which command will you choose to convert a column of data into row?", "Cut and Paste", "Paste Special -> Transpose", "Both of above", "None of above", "B"],
        ["أساسيات الحاسوب", "What was the first type of computer that allowed many users to access information... match a large geographic area?", "mini computer", "laptop", "Central computer (أو ما يُعرف علمياً بـ Mainframe)", "micro computer", "C"],
        ["Excel", "In Microsoft Excel, what is the formula to calculate the total sum of a range of cells?", "=TOTAL()", "=ADD()", "=SUM()", "=COUNT()", "C"],
        ["Excel", "What is the main purpose of using the Excel 2016 application?", "To print and format texts", "To perform mathematical operations only", "To design presentations", "To perform calculations and statistical analyses", "D"],
        ["أساسيات الحاسوب", "Which of the following is a non-volatile memory?", "RAM", "ROM", "Cache memory", "Registers", "B"],
        ["Excel", "To format the number listed in a cell to be shown with two decimal places in Microsoft Excel 2019?", "Home menu? Then we click on the comma symbol.", "Home menu? Then we click on the time symbol.", "Home menu? Then we click on the symbol to increase decimal places.", "Home menu? Then we click on the percentage symbol.", "C"],
        ["الإنترنت", "What is used to verify people's identity and accounts on the network?", "user name", "network name", "device name", "none of above", "A"],
        ["أساسيات الحاسوب", "Which folder contains installed applications by default?", "Documents", "Windows", "Program Files", "Temp", "C"],
        ["Word", "In Microsoft Word, which view displays the document as it would appear on a printed page?", "Draft view", "Outline view", "Print Layout view", "Web Layout view", "C"],
        ["أساسيات الحاسوب", "What is the shortcut key to undo the last action in Windows?", "Ctrl + Y", "Ctrl + X", "Ctrl + Z", "Ctrl + U", "C"],
        ["الإنترنت", "What does spam refer to in email?", "Junk or unwanted emails", "Social media messages", "Important emails", "File attachments", "A"],
        ["Word", "how can you print only selected pages of a document?", "Click File > Save As and select the pages", "Press Ctrl + Alt + Print", "Go to File > Print, and specify the page range", "Highlight the text and press Ctrl + P", "C"],
        ["Word", "How do you apply a text highlight color in Word 2016?", "Use the Home tab, then click the highlight icon in the Font group", "Go to the Design tab and select Highlight", "Rightclick on the text and select Highlight", "Press Ctrl + H and select a color", "A"],
        ["الإنترنت", "What is the encryption?", "Data lock", "Security", "security search", "When sending information over the Internet, the site encrypts the data, that is, encodes it before sending it, and decodes it using a..", "D"],
        ["أساسيات الحاسوب", "Which of the following is considered the \"brain\" of the computer?", "Hard Drive", "RAM", "CPU", "Motherboard", "C"],
        ["Excel", "How to hide 4th row from being visible?", "Formatting Hide and Show Hide rows", "Cells hide and show hide rows", "Edit Hide and Show Hide rows", "All answers given are incorrect", "A"],
        ["الإنترنت", "What is the difference between the Inbox and the Spam folder?", "Inbox contains unread emails; Spam contains read emails", "Inbox is for all emails; Spam is for unwanted or potentially harmful emails", "Spam contains only deleted emails", "Inbox is for personal emails, and Spam is for work emails", "B"],
        ["أساسيات الحاسوب", "The Show group of the View tab is used to show...", "Ruler", "Pane Navigation", "Gridlines", "All of the above", "D"],
        ["أساسيات الحاسوب", "Which shortcut is used to copy selected text?", "Ctrl + V", "Ctrl + X", "Ctrl + C", "Ctrl + Z", "C"],
        ["Word", "To delete a table in MS Word, we select the entire table and then press the key _________", "Delete", "Ruler", "cancel", "Backspace", "D"],
        ["Excel", "How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?", "We select the three cells first, then from the View menu we choose Instruct Merge.", "We select the three cells first, then from the main page menu, we choose Instruct Merge and Center.", "We double click (two clicks) with the left mouse button on the three cells that we want to merge, and they merge.", "We select the three cells first, then from the Page Layout menu we choose Instruct Merge.", "B"],
        ["الإنترنت", "Which of the following is a type of cyber security threat?", "Firewall", "Phishing", "Antivirus", "Encryption", "B"],
        ["أساسيات الحاسوب", "Which of the following can be used for quick access to common commands and tools?", "Status bar", "Toolbar", "Menu bar", "Title bar", "B"],
        ["Excel", "GB means:", "Gilo Bit", "Giga Byte", "Giga Bits", "Gilo byte", "B"],
        ["Word", "When working on a cloud-based document, such as Google Docs, which feature allows multiple users to edit the document in real time?", "share by link", "Real time collaboration", "Offline mode", "Commenting mode", "B"],
        ["Word", "How can you change the line spacing in Word 2016?", "By using the Page Layout tab", "By using the Insert tab", "By using the Home tab", "By using the Design tab", "C"] ,
     
        ["Excel", "The Name Box appears to the left of the formula bar, what does it display?", "The name of the workbook you are currently working on", "The name of the worksheet you are currently working on", "The name of the cell or range you are currently working on", "None of the above", "C"],
        ["Excel", "Which of the cell pointers indicates that you can move content to another cell?", "Doctor icon (large plus sign)", "Thin small plus icon", "Mouse pointer with a border/anchor at the end", "None of above", "C"],
        ["Excel", "Which of the cell pointers indicates that you can fill a series?", "Doctor icon (large plus sign)", "Thin small plus icon", "Mouse pointer with an anchor point at the end", "None of above", "B"],
        ["Excel", "MS Excel provides the default step value in the \"Fill Series\" dialog box", "0", "1", "5", "10", "B"],
        ["Excel", "Where do we find control buttons in Excel 2019?", "Title bar", "Status bar", "Home", "Quick access bar", "A"],
        ["Excel", "How can you fill a cell with a pattern color in Excel?", "Use \"Format Cells\" option then \"Fill\" to choose the color", "Use \"Insert\" option to add color to the cell", "Change the text color inside the cell instead of filling it", "None of above", "A"],
        ["Excel", "What is the maximum column width?", "200", "75", "255", "265", "C"],
        ["Excel", "When you want to add a color to a font cell in Excel, which of the following options should you choose from the Home tab?", "Fill color", "Cell format", "Change font", "Color gradient", "A"],
        ["Excel", "How can you change column width to 2 cm?", "Through the content I write", "Column width cannot be changed", "Column width is fixed from the design", "None of above", "D"],
        ["Excel", "How can you merge three cells into one cell in Excel?", "Select cells and choose merge and center from the Review tab", "Select cells and choose merge and center from the Home tab", "Select cells and choose merge from the Insert tab", "Select cells and choose format from the View tab", "B"],
        ["Excel", "From where can you delete a worksheet in Excel?", "Delete > View > Delete", "Delete > Content", "Edit > Delete", "None of above", "D"],
        ["Excel", "Where can you hide a row in Excel?", "From the \"Layout\" tab and select \"Hide\"", "From the \"Format\" tab and select \"Hide\"", "From the \"View\" tab and select \"Hide\"", "From the \"Home\" tab and select \"Hide\"", "D"],
        ["Excel", "Where can you insert a symbol in Microsoft Excel?", "View tab", "Insert tab", "Design tab", "Review tab", "B"],

    
        ["Word", "From where can you know the word count in a Word page?", "From the status bar", "From the right side of the sheet", "From the Home tab", "By clicking on the words", "A"],
        ["Word", "How can you add the time and date in programs like Microsoft Word, PowerPoint?", "View > text", "Insert > text", "Review > text", "Layout > text", "B"],
        ["Word", "What does a table object's size depend on?", "Depends on the inserted text in the table", "Depends on the presentation and cannot be edited", "Depends on the presentation and can be edited", "A or C", "D"],
        ["Word", "Where do the styles appear in the tabs in Word 2016?", "Design tab", "Home tab", "View tab", "Layout tab", "B"],


        ["PowerPoint", "Which of the following is not part of a slide design?", "Design template", "Color scheme", "Animation scheme", "Slide layout", "D"],
        ["PowerPoint", "How many views in PowerPoint?", "3", "4", "5", "6", "C"],

    
        ["الإيميل", "Two-factor authentication provides:", "Email security", "Receiving speed", "Email sending speed", "Deleting spam", "A"],
        ["الإيميل", "If you want to forward all incoming messages to someone else, what do you choose?", "Forwarding automatically", "Reply automatically", "Electronic signature", "None of above", "A"],
        ["الإيميل", "If you want to send search/research in email what choose?", "Share link", "Send as attachment", "Page", "Cannot be sent", "B"],
        ["الإيميل", "Where is an email saved before sending and for editing?", "Drafts", "Sent", "Inbox", "Spam", "A"],
        ["الإيميل", "To exchange texts between two or more people", "Podcast", "Audio file", "Videos", "IM (instant messaging)", "D"],

    
        ["Windows", "Desktop background is called:", "Graphics", "Layout", "Background image", "Wallpaper", "D"],
        ["Windows", "Where can you find file information such as name and size?", "From Help", "File", "Insert", "View", "B"],

    
        ["مكونات الحاسوب", "The byte is a unit of measurement for", "Memory", "Time", "Date", "Number", "A"],
        ["مكونات الحاسوب", "Data security breaches by unauthorized intruders", "Failure by employees to set strong passwords", "Failure to protect computer devices", "Employee negligence in security matters", "None of above", "A"],

   
        ["قواعد البيانات", "What is a username?", "Account identifier", "Encryption key", "Network cable", "Database table", "A"],
       
        ["الإنترنت", "What are the small text files stored on a user's computer by a web browser to save information and track active user?", "Cache", "RAM", "Cookies", "Data processing", "C"],
        ["الإنترنت", "What is online shopping?", "Editing videos", "Writing programs", "Buying products via Internet", "Repairing computers", "C"],
     ["الإنترنت", "What does WWW stand for?", "World Wide Web", "Wide World Web", "Web World Wide", "World web window", "A"],
    ["الإنترنت", "The primary purpose of protecting data online is:", "Privacy protection of personal data", "Establishing standards for how programs should be written", "Protecting companies from industrial espionage", "Hacker preventing", "A"],
    ["الإنترنت", "Which of the following is a strong password example?", "12345678", "Password", "B9hSYt8x", "user123", "C"],

   
    ["Excel", "What is the result of the function =MIN(2, 5, 25, 10)?", "5", "0", "2", "25", "C"],
    ["Excel", "The Show group of the View tab is used to show:", "Ruler", "Gridlines", "Pane Navigation", "All of the above", "D"],
    ["Excel", "To insert a new sheet, click the button:", "Insert, paper insert", "Page layout, insert, insert sheet", "Home, Insert, Insert Sheet", "All answers given are incorrect", "C"],
    ["Excel", "What is the main purpose of using the Excel 2016 application?", "To design presentations", "To print and format texts", "To perform calculations and statistical analyses", "To perform mathematical operations only", "C"],
    ["Excel", "It is acceptable to let long text flow into adjacent cells in a worksheet when", "Data will be entered in adjacent cells", "No data will be entered in adjacent cells", "There is no suitable shortcut for the text", "There is no time to format the text", "B"],
    ["Excel", "What happens when you press Ctrl + X after selecting some cells in Excel?", "The cell content of selected cells disappear from cell and stored in clipboard", "The cells selected are marked for cutting", "The selected cells are deleted and the cells are shifted left", "The selected cells are deleted and cells are shifted up", "B"],
    ["Excel", "In Microsoft Excel, to fill a cell with a specific color or pattern, do the following:", "From the home page, choose Format Cells, then Fill, then Pattern", "From the Format menu, Choose Pattern", "From the Format menu, Choose Font, then choose Pattern", "All the answers given are incorrect", "A"],
    ["Excel", "What is the default value for step in Fill series dialog box?", "Zero", "1", "3", "10", "B"],
    ["Excel", "The default name for files created in Excel 2019 is:", "Book", "Row", "Sheet", "Cell", "A"],
    ["Excel", "How can you change an existing chart to a Line Chart in Excel 2016?", "Go to the Design tab and choose Change Chart Type", "Go to the home and choose type chart", "Go to the View tab and choose Gridlines", "Double click on the cell A1", "A"],
    ["Excel", "To insert a new column between Column A and Column B, press the button", "Insert columns from the group Edit", "Insert columns from the group Insert", "Insert columns from the group Cells", "All the answers given are incorrect", "C"],
    ["Excel", "Which command will you choose to convert a column of data into a row?", "Cut and Paste", "Edit -> Paste Special -> Transpose", "Both", "None of above", "B"],
    ["Excel", "When you gather data from a database to include it in a project within Excel, this process is called:", "Data collection", "Data Refinement", "Data analysis", "Data formatting", "A"],
    ["Excel", "To insert a new row between row 10 and row 11, click the button:", "Insert cells from the Insert group", "Insert cells from the Edit group", "Insert cells from the Cells group", "All answers given are incorrect", "D"],

  
    ["Word", "From where can you know the word count in a Word page?", "From the status bar", "From the right side of the sheet", "From the Home tab", "By clicking on the words", "A"],
    ["Word", "How can you change the line spacing in Word 2016?", "By using the Page Layout tab", "By using the Insert tab", "By using the Home tab", "By using the Design tab", "C"],
    ["Word", "How can you change the orientation of a page in Word 2016 from portrait to landscape?", "Go to File Page Setup", "Go to the Layout tab and choose orientation", "Press Ctrl + Shift + L", "Go to Home Orientation", "B"],
    ["Word", "How do you apply a text highlight color in Word 2016?", "Go to the Design tab and select Highlight", "Use the Home tab, then click the highlight icon in the Font group", "Right-click on the text and select Highlight", "Press Ctrl + H and select a color", "B"],

    
    ["PowerPoint", "Which view in PowerPoint can be used to enter speaker comments?", "Slide show", "Slide sorter", "Normal", "Notes page view", "D"],
    ["PowerPoint", "In a PowerPoint presentation....", "Sound clips can be inserted but not movie clips", "Movie clips can be inserted but not sound clips", "Both cannot be inserted", "Both can be inserted", "D"],
    ["PowerPoint", "Which of the following section does not exist in a slide layout?", "Titles", "Lists", "Charts", "Animations", "D"],
    ["PowerPoint", "Animation schemes can be applied to .......... in the presentation", "All slides", "Select slides", "Current slide", "All of the above", "D"],
    ["PowerPoint", "Headers and footers can include text and graphics, as well as their", "Current date", "Page number", "Current time", "All of the above", "D"],
    ["PowerPoint", "Which of the following is the default page setup orientation for slides in PowerPoint?", "Vertical", "Landscape", "Portrait", "None of above", "B"],
    ["PowerPoint", "Which of the following tools enable you to add text to a slide without using the standard placeholders?", "Text box tool", "Line tool", "Fill color", "Auto shapes tool", "A"],

   
    ["Windows", "You access the recycle bin through an icon located:", "on the desktop", "on the hard drive", "on the shortcut menu", "in the properties dialog box", "A"],
    ["Windows", "Which of the following is an operating system?", "Google Chrome", "Microsoft Excel", "Windows", "Adobe Photoshop", "C"],
    ["Windows", "Which folder usually contains user documents?", "Program Files", "Windows", "Documents", "System32", "C"],

    
    ["مكونات الحاسوب", "The unit that is responsible for receiving data and messages from other devices within networks or another networks connected in the same network is", "Sending unit", "Wide area network", "Receiving unit", "Transmission media", "C"],
    ["مكونات الحاسوب", "Which component coordinates all computer activities?", "RAM", "CPU", "Hard Disk", "I/O Device", "B"],
    ["مكونات الحاسوب", "GB means:", "Gilo bit", "Giga Byte", "Giga bit", "Gilo Byte", "B"],
    ["مكونات الحاسوب", "Which device converts digital signals to printed output?", "Monitor", "Printer", "Scanner", "Speaker", "B"],

    
    ["الإيميل", "What does the Reply All function do?", "Replies to only the sender", "Replies to everyone on the email chain", "Sends a new email", "Forward the email", "B"],
       
    ["Word", "Insert a header and footer from the tab", "Home", "Layout", "Insert", "Design", "C"],
    ["Word", "Find and replace in Ms word from", "Ctrl + H", "Ctrl + F", "Ctrl + R", "Ctrl + P", "A"],
    ["Word", "What functions are included in the Home tab in Microsoft Office programs?", "Text formatting, changing font and size, alignment", "Inserting tables and charts", "Adding footnotes and references", "Adjusting margins and page orientation", "A"],
    ["Word", "What happens when you press the Home key on the keyboard in Word?", "Move to the beginning of the document", "Move to the end of the document", "Move to the beginning of the line", "Move to the middle of the line", "C"],
    ["Word", "What is the shortcut used to insert a page break in a Microsoft Word document?", "Space", "Ctrl + Shift + N", "Ctrl + Enter", "Ctrl + S", "C"],

    
    ["PowerPoint", "The number of steps between the start and the end in the AutoContent Wizard is usually:", "6", "4", "3", "5", "C"],
    ["PowerPoint", "Which presentation view works best when presenting inside Auditorium?", "Outline View", "Master View", "Slide show", "Slide sorter", "C"],
    ["PowerPoint", "To add a new slide, you click on:", "Ctrl + M", "Ctrl + D", "Ctrl + S", "Ctrl + N", "A"],
    ["PowerPoint", "Which of the following section does not exist in a slide layout?", "Titles", "Lists", "Charts", "Animations", "D"],
    ["PowerPoint", "How can you navigate between slides while giving a PowerPoint presentation in front of an audience?", "Display slides one after another sequentially", "Using a large display screen and selecting \"audience\" choice then clicking audience", "Full screen slide show view", "None of above", "C"],

   
    ["الإنترنت", "Accessing previously viewed Internet browser content without an internet connection is done via:", "From History", "From cache memory", "Bookmark", "None of above", "B"],
    ["الإنترنت", "The tool that enables a researcher to obtain references from the internet is:", "Yahoo", "Netscape", "outlook", "MS explorer", "A"],
    ["الإنترنت", "Which of the following is considered an internet browser?", "Microsoft word", "Google chrome", "Windows media", "Adobe Photoshop", "B"],
    ["الإنترنت", "What can a hyperlink link to?", "Internet network", "Intranet networks", "Computer devices", "Web pages or documents", "D"],

    
    ["Excel", "The element that contains rows and columns inside Excel is:", "Workbook", "Cells", "Sheet", "Table", "C"],
    ["Excel", "What is the function used to calculate the standard deviation in Excel?", "AVERAGE", "SUM", "STDEV", "VAR", "C"],
    ["Excel", "What is the shortcut used to go to the first cell in a worksheet?", "Ctrl + 1", "Ctrl + Home", "Ctrl + End", "Shift + Home", "B"],
    ["Excel", "To add the currency symbol Iraqi dinar after the number 1000 in Excel:", "S", "ID", "IQD", "QD", "C"],
    ["Excel", "In which tab can you change the font type in Excel or PowerPoint?", "Insert", "Page layout", "Home", "Review", "C"],
    ["Excel", "What is the function of the shortcut Ctrl + D in Microsoft Excel?", "Fill selection right and left of the cell", "Repeat last action performed", "Fill selection down the cell", "Fill selection up the cell", "C"],

   
    ["Windows", "Which of the following is an operating system?", "Google Chrome", "Microsoft Excel", "Windows", "Adobe Photoshop", "C"],
    ["Windows", "To create a new document:", "open", "new", "save", "Save as", "B"],

    
    ["قواعد البيانات", "Which of the following categories is used to transfer data in databases?", "DDL", "DCL", "DML", "None of above", "C"],

   
    ["مكونات الحاسوب", "What is the primary role of a firewall in network security?", "Encrypting data to ensure its confidentiality", "Preventing unauthorized access to the network", "Increasing internet connection speed", "None of above", "B"],
        
    ["Windows", "Where is the Recycle Bin located?", "In File Explorer", "On the Desktop", "In the Start Menu", "On the Taskbar", "B"],
    ["Windows", "When saving files, where are they stored by default?", "Document", "Folder", "My file", "None of above", "A"],
    ["Windows", "What is the function shortcut Ctrl + O?", "Create new file", "Open save file", "Save file", "Print file", "B"],
    ["Windows", "What is the shortcut used to open the help or assistance window?", "F1", "F2", "F4", "F9", "A"],
    ["Windows", "How can you remove a column between two columns in Excel?", "Select the header of the column you want to delete and select the delete row button on the standard toolbar", "Select the header of the column you want to delete and select 'Insert Delete' from the menu", "Select the header of the row you want to delete and select 'Edit > Delete' from the menu", "Right-click on the header of the column you want to delete and select 'Delete' from the shortcut menu", "D"],
    ["Windows", "How can you move a sheet from one workbook to a new workbook using:", "From the Edit menu, choose 'Move or Copy', then select 'Create a copy' and click 'OK'", "From the Edit menu, choose 'Move or Copy', then select 'Move to end' and click 'OK'", "From the Edit menu, choose 'Move or Copy', then select 'New book' from the 'To book' list and click 'OK'", "None of above", "D"],

   
    ["Excel", "How can you open the Microsoft Excel application?", "From the Start menu → All Programs → Right-click → Microsoft Excel", "From the Start menu → All Programs → Left-click → Microsoft Excel", "By opening File Explorer and selecting an Excel file", "By pressing the power button on the computer directly", "B"],
    ["Excel", "Which key is used to move between cells vertically in Excel?", "Alt", "Shift", "Enter", "None of above", "C"],
    ["Excel", "If the values (18, 5, 6) are present in a cell, and the function used is MAX, what is the result?", "5", "6", "25", "18", "D"],
    ["Excel", "What is the benefit of adding patterns (pattern fill) to cells in Excel?", "Color text only without changing background", "Distinguish cells from each other", "No benefit", "Merge cells", "B"],
    ["Excel", "What function is used to calculate the number of failing students?", "COUNT", "COUNTIF", "SUM", "SUMIF", "B"],
    ["Excel", "What is the function of the small square located in the corner of an Excel cell?", "Change cell color", "Auto fill data", "Select cells", "Move cell content", "B"],
    ["Excel", "How can you delete the third sheet from an Excel workbook?", "Select the third sheet, then right-click and choose 'Delete'.", "Select the third sheet, then from the 'Edit' menu choose 'Delete'", "Both", "Select the third sheet from Insert Delete Sheet", "A"],
    ["Excel", "Which of the following options can convert a column of data into a row?", "Cut paste", "Paste special > transpose", "All", "None of above", "B"],
    ["Excel", "How can a column be inserted between A and B in Excel?", "Select column A, then from the Home tab choose insert column", "Select column B, then from the Home tab choose insert column", "Select column A, then from the View tab choose insert column", "None of above", "B"],
    ["Excel", "What is the extension of saved files in Excel?", ".xld", ".txt", ".xlsx", ".xls", "C"],
    ["Excel", "Which menu insert column in Excel?", "Home", "Insert", "Review", "View", "A"],
    ["Excel", "What is the result of the function MAX when the values 18, 5, and 6 are present in a cell?", "5", "6", "25", "18", "D"],

   
    ["Word", "What is the function of the shortcut Ctrl + B?", "Copy and paste", "Cut and paste", "Make the text bold", "Make the text italic", "C"],
    ["Word", "When repeated word in Ms Word what color appear under?", "Wavy red", "Wavy green", "Wavy blue", "None of above", "A"],
    ["Word", "Where can you find the Watermark in Microsoft Word?", "Insert", "Design", "Layout", "Home", "B"],
    ["Word", "What is the benefit of text WordArt in Microsoft Word?", "Improving text appearance and making it more attractive", "Making reading and distinguishing difficult", "Easy typing in word", "None of above", "A"],

   
    ["PowerPoint", "Can video and audio clips be inserted into PowerPoint?", "Video", "Audio", "Both", "None of above", "C"],
    ["PowerPoint", "How can you add a logo in PowerPoint?", "From insert picture", "From clip board", "From shape", "None of above", "A"],
    ["PowerPoint", "When sending a PowerPoint file via email, what option is used?", "Share link", "Attachment", "Insert in mail", "None of above", "B"],
    ["PowerPoint", "What is the best way to view slides in PowerPoint?", "Slide sorter", "Slide show", "Outline view", "None of above", "B"],

    
    ["الإنترنت", "What does HTTP stand for?", "Hypertext Platform", "Hypertext Transfer Protocol", "Hypertext Browsing", "Hypertext Source", "B"],
    ["الإنترنت", "What is the icon for bookmarking a web page or saving it for later access?", "Star icon", "Lock icon", "Trash bin", "Attachment", "A"],
    ["الإنترنت", "What is a Web Browser?", "Display HTML file", "Create HTML file", "Drawing HTML file", "Delete HTML file", "A"],

    
    ["قواعد البيانات", "How can multiple users use a large mainframe computer at the same time?", "Used by office owners only", "Large commercial sales company using from more than one place use same server", "Making a special code for subscribers inside the organization", "Users within the same central processing unit", "B"],

    
    ["الإيميل", "When merging e-mail with data, what is the term used?", "Server", "Client", "Source", "None of above", "D"],
    ["الإيميل", "What is the difference between the inbox and spam messages?", "Inbox contains advertisements and spam messages, while unwanted messages contain important messages", "The inbox contains all messages, and the spam folder contains unwanted messages", "The inbox contains unsent messages, and the unwanted folder contains sent messages", "All answers incorrect", "B"],
    ["الإيميل", "What is the best password you can use to protect your account?", "password", "12345", "ali@17&ah0", "sah123", "C"],

    
    ["مكونات الحاسوب", "What is the primary role of a firewall in network security?", "Encrypting data to ensure its confidentiality", "Preventing unauthorized access to the network", "Increasing internet connection speed", "None of above", "B"],
        
    ["Excel", "Which of the following options makes the command 'Edit > fill across worksheet' active in Excel?", "When selecting a single worksheet", "When selecting multiple worksheets", "When no worksheet is selected", "None of the above", "B"],
    ["Excel", "Where can you set the shading color for a range of cells in Excel?", "Choose the desired color from the 'Pattern' tab in the Format Cells dialog box.", "Choose the desired color from the 'Fill Color' tool on the formatting toolbar.", "Choose the desired color from the 'Fill Color' tool on the drawing toolbar.", "All of above", "D"],
    ["Excel", "Where can you set page borders in Excel?", "From the 'Borders' tab in the Format Cells dialog box.", "From the 'Borders' tool in the formatting toolbar", "From the 'Line Style' tool in the drawing toolbar", "You cannot set page borders in Excel", "D"],
    ["Excel", "While using Find and Replace in Excel, which of the following statements is correct?", "You can search and replace within the worksheet or Excel workbook", "It does not contain an option for match case when searching", "Both", "None of above", "A"],
    ["Excel", "Which menu option can be used to split windows into two parts?", "Review < Window", "View < Window < Split", "Window < Split", "View < Split", "B"],
    ["Excel", "What does A15 represent in Excel?", "Row A and Column 15", "Row and Column 15", "Row 15 and Column A", "None of above", "C"],
    ["Excel", "To insert a new column between Column A and Column B, click the button", "Insert Columns from the 'Editing' group", "Insert Columns from the 'Insert' group", "Insert Columns from the 'Cells' group", "All given answers are incorrect", "C"],
    ["Excel", "What does 'Sort' mean?", "Sorting numbers in ascending order (from smallest to largest)", "Sorting numbers in descending order (from largest to smallest)", "Sorting from A to Z or vice versa", "All of above", "D"],
    ["Excel", "If the data values linked to a pie chart in Excel change, does this affect the chart?", "The chart will be updated automatically, but the change will be in the values, not in the chart's appearance.", "The chart must be updated manually.", "The chart will disappear when modifying linked values.", "None of above", "A"],
    ["Excel", "When deleting a row between Column A and Column B, what happens to the data?", "Data moves to the left", "No change occurs in the data order", "Data in lower rows moves up", "All options are incorrect", "D"],
    ["Excel", "In Excel, every file is a workbook containing different sheets. Which of the following cannot be a sheet in the workbook?", "Worksheet", "Chart sheet", "Macro sheet", "Data sheet", "D"],
    ["Excel", "When opening page setup settings, what is usually the default orientation?", "Portrait", "Landscape", "Default", "Horizontal", "A"],
    ["Excel", "How can you change the column width to 30 in Excel?", "Right-click on the column, then choose 'Format Cells' and specify the width.", "Select the column, then go to 'Format' and change the width.", "Column width cannot be changed", "Double-click inside any cell in the column", "B"],
    ["Excel", "What is the function of the shortcut Ctrl + D in Microsoft Excel?", "Fill selection right and left of the cell", "Repeat last action performed", "Fill selection down the cell", "Fill selection up the cell", "C"],
    ["Excel", "How can you find the minimum value in Excel?", "MAX", "MIN", "SUM", "AVERAGE", "B"],


    ["Word", "A comment can be inserted from", "Insert tab", "View tab", "Home tab", "Review tab", "D"],
    ["Word", "Which key do you press to check spelling?", "F3", "F5", "F7", "F9", "C"],
    ["Word", "How can you select all text?", "F2", "Ctrl + C", "Ctrl + V", "Ctrl + A", "D"],
    ["Word", "How can you navigate from one page to another in Word without using the mouse or arrows?", "Ctrl + Page Up", "Ctrl + Page Down", "Both", "None of above", "C"],
    ["Word", "When repeated word in Ms Word what color appear under?", "Wavy red", "Wavy green", "Wavy blue", "None of above", "A"],
    ["Word", "Where can you find the Watermark in Microsoft Word?", "Insert", "Design", "Layout", "Home", "B"],
    ["Word", "What is the benefit of text WordArt in Microsoft Word?", "Improving text appearance and making it more attractive", "Making reading and distinguishing difficult", "Easy typing in word", "None of above", "A"],

    
    ["الإنترنت", "What is the benefit of an IP address?", "Identifying the device on the network", "Transferring text data over the network", "Transferring files over the network", "None of above", "A"],
    ["الإنترنت", "How can you mark an important page while browsing to save it and return to it later?", "Clicking on the star", "Refreshing the page", "Closing the page and opening it from history later", "None of above", "A"],
    ["الإنترنت", "If you exit the page you are browsing, where will you go?", "The browser closes", "Goes to the home page", "Goes to the searched page", "Goes back to the previous page", "D"],
    ["الإنترنت", "Which of the following options is considered an internet browser?", "Word", "Windows", "MS Explorer", "Yahoo", "C"],
    ["الإنترنت", "When the internet disconnects, how can a web page be opened without a connection?", "POP", "DCL", "Cache", "Cookies", "C"],
    ["الإنترنت", "What is the technology that allows communication between all people around the world?", "WWW", "Internet", "Communication between all people is not possible", "None of above", "B"],

    
    ["Windows", "Where is the Recycle Bin located?", "In File Explorer", "On the Desktop", "In the Start Menu", "On the Taskbar", "B"],
    ["Windows", "The purpose of a file extension", "Knowing its size", "Knowing the file type", "Knowing who created the file", "Knowing where the file is stored", "B"],
    ["Windows", "What is the function of the shortcut Ctrl + X?", "Pastes text to the clipboard", "Copies text to the clipboard", "Cuts text and moves it to the clipboard", "Selects text only", "C"],

   
    ["مكونات الحاسوب", "How can multiple users use a large mainframe computer at the same time?", "Used by office owners only", "Large commercial sales company using from more than one place use same server", "Making a special code for subscribers inside the organization", "Users within the same central processing unit", "B"],

    
    ["قواعد البيانات", "Which of the following is not a type of database?", "(Relational Databases).", "NoSQL.", "(Text Data Bases).", "(Network Database", "C"],

    
    ["الإيميل", "When replying to an email, what can happen to the message?", "Reply", "Reply all", "Both", "It is saved as a draft without sending", "C"],

    
    ["PowerPoint", "Which view displays the slides in a presentation as thumbnails?", "Outline View", "Normal View / Slide View", "Slide Sorter", "None of above", "C"],
        
    ["Windows", "What is the shortcut used to show the help menu?", "F1", "F5", "F8", "F9", "A"],
    ["Windows", "Where is the Recycle Bin located in the Windows system?", "On the desktop", "File explorer", "On the taskbar", "In start menu", "A"],
    ["Windows", "What is the best way to shut down a computer?", "Shut down the computer by clicking the power button", "From shutdown in the Start menu", "Disconnecting the electricity from the computer", "All of above", "B"],
    ["Windows", "Which of the following dialog boxes tells you about readiness to create a new document?", "Start screen", "End screen", "Print screen", "Save screen", "A"],
    ["Windows", "How do you open a new window in the browser?", "Ctrl + N", "Ctrl + W", "Ctrl + T", "Ctrl + R", "A"],
    ["Windows", "How can you change the desktop background in Windows?", "From Settings", "From the Home page", "From task manager", "File explorer", "A"],

   
    ["Excel", "Which of the following statements is incorrect regarding Find and Replace?", "Search for part of a word", "Search for a formula", "You can search by italics and replace with highlighted", "You can search by columns and rows", "C"],
    ["Excel", "When saving a file in Excel 2019, what name is given to the file?", "Row", "Book", "Cell", "Paper", "B"],
    ["Excel", "What symbol must precede a function in Excel?", "#", "=", "+", "-", "B"],
    ["Excel", "In Ms Excel, what is the default number that appears in the Fill dialog box?", "0", "10", "5", "1", "D"],
    ["Excel", "Excel displays the current cell address in:", "Formula bar", "Status bar", "Name box", "Toolbar", "C"],
    ["Excel", "How can numbers from 0 to 100 be changed to red in Excel?", "Conditional Formatting", "By pressing Ctrl, selecting the numbers, and coloring", "Both", "None of above", "A"],
    ["Excel", "What is the function used to find the highest value in Excel?", "MAX", "SUM", "MIN", "AVERAGE", "A"],
    ["Excel", "How can you insert a new worksheet in Excel?", "From the Home tab, then choosing Insert", "By right-clicking on the worksheet tab at the bottom and selecting Insert Worksheet", "Both", "From the Insert tab, then choose Insert Sheet 5", "C"],
    ["Excel", "What is the function used to find the number of failing students?", "COUNT", "COUNTIF", "SUM", "SUMIF", "B"],
    ["Excel", "How can you change the worksheet direction from right to left or vice versa in Excel?", "From page direction", "From page layout", "From view", "From review", "B"],
    ["Excel", "If you open a workbook and have three sheets, how can you delete the third sheet in Excel?", "Right-click on the sheet name at the bottom, then choose Delete", "Pressing the Delete key after selecting the sheet", "From the Page Layout menu, choose Hide Sheet", "From the Insert menu, choose Delete Sheet", "A"],
    ["Excel", "What is the function of the shortcut Ctrl + X?", "Pastes text to the clipboard", "Copies text to the clipboard", "Cuts text and moves it to the clipboard", "Selects text only", "C"],
    ["Excel", "What is the function used to find the minimum value in Excel?", "MAX", "MIN", "SUM", "AVERAGE", "B"],
    ["Excel", "Which of the following options makes the command 'Edit > fill across worksheet' active in Excel?", "When selecting a single worksheet", "When selecting multiple worksheets", "When no worksheet is selected", "None of the above", "B"],
    ["Excel", "Where can you set the shading color for a range of cells in Excel?", "Choose the desired color from the Pattern tab in the Format Cells dialog box", "Choose the desired color from the Fill Color tool on the formatting toolbar", "Choose the desired color from the Fill Color tool on the drawing toolbar", "All of above", "D"],
    ["Excel", "Where can you set page borders in Excel?", "From the Borders tab in the Format Cells dialog box", "From the Borders tool in the formatting toolbar", "From the Line Style tool in the drawing toolbar", "You cannot set page borders in Excel", "D"],
    ["Excel", "What does A15 represent in Excel?", "Row A and Column 15", "Row and Column 15", "Row 15 and Column A", "None of above", "C"],
    ["Excel", "To insert a new column between Column A and Column B, click the button", "Insert Columns from the Editing group", "Insert Columns from the Insert group", "Insert Columns from the Cells group", "All given answers are incorrect", "C"],
    ["Excel", "What does Sort mean?", "Sorting numbers in ascending order", "Sorting numbers in descending order", "Sorting from A to Z or vice versa", "All of above", "D"],
    ["Excel", "If the data values linked to a pie chart in Excel change, does this affect the chart?", "The chart will be updated automatically, but the change will be in the values, not in the chart's appearance", "The chart must be updated manually", "The chart will disappear when modifying linked values", "None of above", "A"],
    ["Excel", "When deleting a row between Column A and Column B, what happens to the data?", "Data moves to the left", "No change occurs in the data order", "Data in lower rows moves up", "All options are incorrect", "D"],
    ["Excel", "In Excel, every file is a workbook containing different sheets. Which of the following cannot be a sheet in the workbook?", "Worksheet", "Chart sheet", "Macro sheet", "Data sheet", "D"],
    ["Excel", "When opening page setup settings, what is usually the default orientation?", "Portrait", "Landscape", "Default", "Horizontal", "A"],
    ["Excel", "How can you change the column width to 30 in Excel?", "Right-click on the column, then choose Format Cells and specify the width", "Select the column, then go to Format and change the width", "Column width cannot be changed", "Double-click inside any cell in the column", "B"],
    ["Excel", "What is the extension of saved files in Excel?", ".xld", ".txt", ".xlsx", ".xls", "C"],
    ["Excel", "Which menu insert column in Excel?", "Home", "Insert", "Review", "View", "A"],
    ["Excel", "Which of the following options can convert a column of data into a row?", "Cut paste", "Paste special > transpose", "All", "None of above", "B"],

    
    ["Word", "What is the most appropriate way to help the blind use a computer?", "Using a mouse and healthy keyboard", "Using graphic interfaces", "Using an aggregation device", "Using screen reader software or a Braille keyboard", "D"],
    ["Word", "What is the command used to bold text in Microsoft Office programs?", "Ctrl + I", "Ctrl + U", "Ctrl + B", "Ctrl + S", "C"],
    ["Word", "How can a chart be inserted in Microsoft Word?", "Home > Insert > Chart", "Insert > Chart", "All of above", "None of above", "B"],
    ["Word", "How can you adjust margins in Word?", "From the File menu, choose Page Setup then modify the margins", "From the Layout menu, choose Margins", "From the View menu, choose Page Setup then modify the margins", "From the Review menu, choose Margins", "B"],
    ["Word", "How can you print a specific number of pages in Word?", "From the File menu, choose Print, then enter the required page numbers in the Pages box", "From the Layout menu, choose Print, then specify the required pages", "From the Insert menu, choose Select Pages, then click Print", "From the View menu, choose Custom Print, then select the required pages", "A"],
    ["Word", "What is the shortcut Ctrl + S?", "Print", "Save as", "Save", "Open", "C"],

    
    ["PowerPoint", "Can video and audio clips be inserted into PowerPoint?", "Video", "Audio", "Both", "None of above", "C"],
    ["PowerPoint", "If you want to display a fixed element on all slides in PowerPoint, where should you place it?", "In the notes", "In the Slide Master", "In the outline view", "In every slide", "B"],
    ["PowerPoint", "Which view displays the slides in a presentation as thumbnails?", "Outline View", "Normal View / Slide View", "Slide Sorter", "None of above", "C"],

    
    ["الإنترنت", "In which place can you search for images, texts, and other contents?", "Files", "Browser", "Search engine", "Cloud computing", "C"],
    ["الإنترنت", "Which of the following options is a characteristic of cloud computing?", "Data can be retrieved without an internet connection", "Data can be accessed from anywhere using the internet", "Data storage only on personal computers", "Data cannot be accessed", "B"],
    ["الإنترنت", "What is Phishing?", "Identity theft", "Data breach", "Debt overload", "Sending promotional messages", "B"],
    ["الإنترنت", "Which of the following options is considered an internet browser?", "Word", "Windows", "MS Explorer", "Yahoo", "C"],

   
    ["قواعد البيانات", "Which of the field has width 8 bytes?", "DateTime", "Memory", "Number", "Link", "A"],
    ["قواعد البيانات", "When saving a file in Excel 2019, what name is given to the file?", "Row", "Book", "Cell", "Paper", "B"],

    
    ["الإيميل", "What should you do if you receive an unwanted email?", "Mark it as spam", "Click on the link to verify it", "Forward", "Send it to your friends", "A"],
    ["الإيميل", "What is the best password you can use to protect your account?", "password", "12345", "ali@17&ah0", "sah123", "C"],
    ["الإيميل", "When replying to an email, what can happen to the message?", "Reply", "Reply all", "Both", "It is saved as a draft without sending", "C"],
    ["الإيميل", "What is the tool through which photos and documents can be sent via telephone lines without needing a computer?", "Email", "TV", "Fax", "Infinix", "C"],

    
    ["مكونات الحاسوب", "What is the primary role of a firewall in network security?", "Encrypting data to ensure its confidentiality", "Preventing unauthorized access to the network", "Increasing internet connection speed", "None of above", "B"],
    ["مكونات الحاسوب", "How can you change the desktop background in Windows?", "From Settings", "From the Home page", "From task manager", "File explorer", "A"],
    ["مكونات الحاسوب", "What technology uses invisible computer devices to enable the purchase of credit or debit cards?", "Magnetic stripe reading", "Embedded processors in machines", "Digital imaging", "Scanner", "A"],

   
    ["Excel", "If you select a range of cells and want to make the previous cell active, what do you press?", "Enter", "Tab", "Shift + Tab", "None of all", "C"],
    ["Excel", "In Microsoft Excel, a pie chart is used for:", "To show the contribution of each value relative to the total", "To show the trend in values across two dimensions in a continuous curve", "To compare values across categories", "To show the trend of values over time or across categories", "A"],
    ["Excel", "How do you navigate between cells in Microsoft Excel?", "Alt", "Ctrl", "Tab", "Shift", "C"],
    ["Excel", "When applying mathematical functions in programs like Excel, the function must start with which symbol?", "Equals (=)", "Addition (+)", "Subtraction (-)", "Division (/)", "A"],
    ["Excel", "How can you change the column width to 30 cm in Microsoft Excel?", "From the Format menu, choose Column Width", "From the Insert menu, choose Column Width", "From the View menu, choose Column Width", "From the File menu, choose Width", "A"],
    ["Excel", "What does A15 represent in Microsoft Excel?", "The cell in row 10 and column A", "Column 5 and row 1 and cell A", "The cell in row 15 and column A", "The cell in row 5 and column A", "C"],
    ["Excel", "What is the shape of the fill handle (fill pointer) that transfers cell contents in Microsoft Excel?", "Plus sign", "Pointer arrow", "Small plus arrow", "Mouse pointer", "D"],
    ["Excel", "What is the shortcut that helps to copy the content or formula of a cell into the cell below it in Microsoft Excel?", "Ctrl + C", "Ctrl + D", "Ctrl + V", "Ctrl + Z", "B"],
    ["Excel", "What action is used to merge and center cells in Microsoft Excel?", "Using the Merge & Center button in the top formatting toolbar", "From the Format dialog box, then choose Merge Cells", "Using the Center Text option from the Format dialog box", "Using Wrap Text inside cells", "A"],
    ["Excel", "How can a border be removed in Microsoft Excel?", "Right-click and choose Format Cells", "Use the Format Cells dialog box > Borders > No Border", "Select Borders then choose No Borders", "Click Filter then Clear sorting", "B"],
    ["Excel", "How can a worksheet be inserted in Microsoft Excel?", "From the Insert menu, then Insert", "From the Home tab, then Insert > Insert Sheet", "From the top ribbon", "From the View menu, then Insert", "B"],

  
    ["Word", "Where can a hyperlink be inserted in Microsoft Word?", "From the View tab", "From the Edit tab", "From the Insert tab", "From the File tab", "C"],
    ["Word", "Where can you insert WordArt in Microsoft Word?", "From the Insert tab", "From the View tab", "From the Edit tab", "From the Format tab", "A"],
    ["Word", "What is the shortcut for opening the Font formatting dialog box in Microsoft Word?", "Ctrl + T", "Ctrl + Shift + F", "Ctrl + D", "Ctrl + F", "C"],
    ["Word", "What page size dimensions does document layout allow in Microsoft Word?", "8.5 × 11 inches (standard size)", "10 × 12 inches", "It can be customized according to the user's needs", "None of above", "C"],

    
    ["PowerPoint", "What is the number of slides that cannot be printed on one page?", "2 slides per page", "3 slides per page", "5 slides per page", "6 slides per page", "C"],
    ["PowerPoint", "Animated images (animations) can be applied to:", "All slides", "Specific slide", "The current slide", "All of the above", "D"],
    ["PowerPoint", "If you want to print only slide 12 and slide 5, what should you choose?", "Slides", "Custom shows", "Custom view", "Print Current Slides", "A"],
    ["PowerPoint", "How many Slide Layouts are in Microsoft PowerPoint?", "10", "12", "15", "None of above", "D"],
    ["PowerPoint", "What does Outline View mean in Microsoft PowerPoint?", "Display images and videos inside slides", "Display only the main text and headings in slides", "Display slides horizontally", "Display slides while hiding text and headings", "B"],
    ["PowerPoint", "What does View Handout mean in Microsoft PowerPoint?", "Display slides horizontally with effects", "Show only text without slides", "Show images and videos only inside slides", "Display slides arranged on printed handout pages in an organized layout", "D"],

   
    ["الإنترنت", "The way computers recognize and communicate with each other on the Internet:", "HTTP", "IP", "WWW", "FTP", "B"],
    ["الإنترنت", "What is the difference between the web and the Internet?", "The web is faster than the Internet", "The web is a global network connecting computers together", "The web is part of the Internet that uses the HTTP protocol to display content through browsers", "The Internet has no protocols, while the web only uses HTTP", "C"],
    ["الإنترنت", "What is the benefit of a digital certificate?", "Secure browsing in the local network", "Access during browsing", "Increasing website security", "None of above", "C"],
    ["الإنترنت", "What is the Internet?", "A network of organized computers", "A satellite", "A laptop computer", "A browsing program", "A"],
    ["الإنترنت", "What application is used to browse websites?", "Browser", "Messenger", "Message manager", "Index", "A"],
    ["الإنترنت", "When working on cloud documents such as Google Docs, which feature allows multiple users to work on the document in real time?", "Real-time collaboration", "Commenting", "Offline mode", "Sharing via link", "A"],

   
    ["Windows", "What is the shortcut used to show the help menu?", "F1", "F5", "F8", "F9", "A"],
    ["Windows", "Where is it preferable to save your files and folders in the operating system?", "My Folder", "My Files", "Documents", "Text", "A"],
    ["Windows", "Where do we find active windows in Windows?", "Desktop", "Taskbar", "Trash / Recycle Bin", "File Explorer", "B"],
    ["Windows", "Where are files downloaded from the Internet stored on the computer?", "Move", "Downloads", "Upload", "Copy", "B"],
    ["Windows", "What is the shortcut for Select All in most programs?", "Ctrl + C", "Ctrl + A", "Ctrl + V", "Ctrl + X", "B"],
    ["Windows", "How do we close a workbook in Microsoft Excel?", "From the Home menu, choose Close", "From View > Close", "From the Title bar, choose Close", "None of above", "C"],

    
    ["قواعد البيانات", "Which of the following options is NOT considered a database?", "Table", "Report", "Relationship", "Queries", "C"],

   
    ["الإيميل", "What should you do if you receive an unwanted email?", "Mark it as spam", "Click on the link to verify it", "Forward", "Send it to your friends", "A"],
        
    ["الإنترنت", "What is the primary protocol used to secure data transmission over the internet?", "FTP", "HTTPS", "HTTP", "IP", "B"],
    ["الإنترنت", "What is the primary protocol used to transfer web data across the internet?", "HTTP", "FTP", "TCP", "SMTP", "A"],
    ["الإنترنت", "What is the method by which computers recognize each other on the Internet network?", "IP", "TCP", "FTP", "SSL", "A"],
    ["الإنترنت", "Uploading pages and files from the computer to the Internet", "Download", "Upload", "Save", "Insert", "B"],
    ["الإنترنت", "Downloading data and files from the Internet to the computer", "Upload", "Move", "Download", "Copy", "C"],
    ["الإنترنت", "What is the Internet?", "A local network connecting computer devices", "A network for managing computer devices", "Programs for viewing web pages only", "A global network connecting computers and devices to exchange information", "D"],
    ["الإنترنت", "The difference between the Web and the Internet", "The Internet is used only for browsing websites, while the Web includes all services", "The Web is a browser and the Internet is a collection of browsers", "The Internet is a global network while the Web is a browser", "No difference between them", "C"],
    ["الإنترنت", "What is WWW?", "Wireless Web Window", "Wide Web World", "Web World Wide", "World Wide Web", "D"],
    ["الإنترنت", "What is the address of a web page on the internet?", "HTTP", "URL", "HTML", "IP", "B"],
    ["الإنترنت", "Which of the following represents a social networking site?", "Google", "Facebook", "Microsoft", "Wikipedia", "B"],
    ["الإنترنت", "Which command is used in a web browser for quick navigation / saving favorite pages?", "History", "Bookmarks", "Notification", "Archives", "B"],
    ["الإنترنت", "What does HTML stand for?", "HyperText Markup Language", "Hyper Transfer Media Language", "HyperText Management Language", "High-Tech Markup Language", "A"],
    ["الإنترنت", "What application is used to browse websites?", "Browser", "Messenger", "Message manager", "Index", "A"],
    ["الإنترنت", "What is the benefit of cloud storage?", "Saving data locally", "Accessing data from any device anywhere with internet", "Storing data on the computer only", "Does not allow remote access", "B"],
    ["الإنترنت", "For web browsing, the best option is:", "Microsoft Office", "Internet Explorer", "Google Chrome", "Mozilla Firefox", "C"],
    ["الإنترنت", "Which of the following options is a characteristic of cloud computing?", "Data can be retrieved without an internet connection", "Data can be accessed from anywhere using the internet", "Data storage only on personal computers", "Data cannot be accessed", "B"],
    ["الإنترنت", "What does HTTPS represent?", "HyperText Transfer Protocol", "A secure version of HTTP", "Transfers browsers", "Transfers files and audio", "B"],
    ["الإنترنت", "What is ISP stand for?", "Internet Service Provider", "Internet Security Protocol", "Information Security Provider", "Internet Session Provider", "A"],

   
    ["Excel", "Which of the pointers indicates that you can select cells in Excel?", "Normal arrow pointer", "Large White plus sign pointer", "Hand pointer", "Black plus sign pointer", "B"],
    ["Excel", "Cell pointer indicating that you can fill the series", "Gross sign", "Thin plus icon", "Mouse pointer with a crosshair/anchor at the edge", "None of above", "B"],
    ["Excel", "Cell pointer indicating that you can move content to another cell", "Gross sign", "Thin plus icon", "Mouse pointer with a crosshair/anchor at the edge", "None of above", "C"],
    ["Excel", "In Excel every formula or function operation must be preceded by:", "Dot (.)", "Exclamation mark (!)", "Equal sign (=)", "Comma (,)", "C"],
    ["Excel", "The first cell in an Excel worksheet is called", "A0", "A", "A1", "1A", "C"],
    ["Excel", "What does A16 mean?", "A cell and 16 column", "Row A and column 16", "Column A and row 16", "All of above", "C"],
    ["Excel", "In Excel which of the following can be used to navigate between cells?", "Enter", "Tab", "Arrow Keys", "All of above", "D"],
    ["Excel", "Excel file extension", "Xls", "Xlsx", "Xlsm", "PPTX", "B"],
    ["Excel", "Where is the Formula Bar located in Excel?", "At the bottom of the Excel window", "At the top of the worksheet next to the toolbar", "In the File menu", "In left work", "B"],
    ["Excel", "How can you hide and show a row or a column in a worksheet?", "Select the row/column, then right-click and click on Delete", "Select the row/column, then right-click and choose unhide or hide", "Select the row or column, then from the toolbar click Delete", "It is not possible to hide or show a row or column using the mouse", "B"],
    ["Excel", "How do we change the column width in Excel?", "Select the column, then from the View menu choose guide to resize the column", "Select the column, then from the Home tab choose Format, and then choose Column Width", "Select the column boundary, then double-click with the left mouse button to auto-fit the column width", "Select the column first, then from the check menu choose Guide to change the column width", "B"],
    ["Excel", "What is the function of the MIN function in Excel?", "Find the largest value in a set of numbers", "Calculate the arithmetic mean of a set of numbers", "Find the smallest value in a set of numbers", "Calculate the sum of numbers in a specific range", "C"],
    ["Excel", "What is the average of (2, 5, 1, 4) in Excel?", "1", "5", "3", "12", "C"],
    ["Excel", "How can you merge and center cells in Excel?", "Select the cells, then choose Format > Merge & Center from the Format menu", "Select the cells, then choose Insert > Merge & Center from the toolbar menu", "Select the cells, then click the Merge & Center button from the top ribbon in the Home tab", "Select the cells, then press Ctrl + M to merge and center the cells", "C"],
    ["Excel", "What happens when you change a cell's content in Excel?", "Related formulas are not updated", "All related formulas are updated automatically", "Only other specific cells are updated", "Nothing changes", "B"],
    ["Excel", "Where is the ruler located in an Excel worksheet?", "In the top toolbar", "In the status bar", "In the View menu", "In the formula bar", "C"],
    ["Excel", "How do you add comments in Excel?", "From the Insert tab then Insert Comment", "From the Home tab then Insert then Insert Comment", "From the Review tab then Add Comment", "Double-click on the cell then Insert Comment", "C"],
    ["Excel", "To split a worksheet in Excel, what do we do?", "Click on the split button in the top bar", "Choose split from the View tab", "Click on F12", "Choose from the Analysis menu", "B"],
    ["Excel", "To delete the third worksheet in Excel:", "Select the worksheet then press Delete", "Select the worksheet then right-click and choose Delete", "Select the worksheet and press F12", "A single sheet cannot be deleted", "B"],
    ["Excel", "To freeze or lock the first row in Excel, we choose:", "From the View tab > Freeze Panes", "From the Insert tab > Freeze", "From the Analysis tab > Freeze", "From the Home page then freeze", "A"],
    ["Excel", "To resume writing/editing inside an Excel cell, we press:", "ALT", "Enter", "F2", "F4", "C"],
    ["Excel", "Which of the following options is used to clear data (cell content) without deleting the cell itself?", "Delete", "Clear Contents", "Ctrl + X", "Clear", "B"],
    ["Excel", "How can you change the column width to 30 cm in Microsoft Excel?", "From the Format menu, choose Column Width", "From the Insert menu, choose Column Width", "From the View menu, choose Column Width", "From the File menu, choose Width", "A"],
    ["Excel", "What is the function used to find the highest value in Excel?", "MAX", "SUM", "MIN", "AVERAGE", "A"],
    ["Excel", "When applying mathematical functions in programs like Excel, the function must start with which symbol?", "Equals (=)", "Addition (+)", "Subtraction (-)", "Division (/)", "A"],
    ["Excel", "What is the shape of the fill handle (fill pointer) that transfers cell contents in Microsoft Excel?", "Plus sign", "Pointer arrow", "Small plus arrow", "Mouse pointer", "D"],
    ["Excel", "What is the shortcut that helps to copy the content or formula of a cell into the cell below it in Microsoft Excel?", "Ctrl + C", "Ctrl + D", "Ctrl + V", "Ctrl + Z", "B"],

   
    ["Word", "Where can a hyperlink be inserted in Microsoft Word?", "Insert > Hyperlink", "View > Hyperlink", "Tools > Hyperlink", "Format > Link", "A"],
    ["Word", "What is the shortcut for opening the Font formatting dialog box in Microsoft Word?", "Ctrl + T", "Ctrl + Shift + F", "Ctrl + D", "Ctrl + F", "C"],
    ["Word", "In which tab is the Spell Check located?", "Insert tab", "Review tab", "Design tab", "View tab", "B"],
    ["Word", "Where are your documents reviewed?", "Inside the File tab", "Inside the Review tab", "Inside the Page Layout tab", "Not reviewed", "C"],
    ["Word", "What is the purpose of the ruler in Office?", "Set colors in cells", "Adjust margins and spacing between elements", "Perform mathematical calculations", "Add horizontal and vertical lines", "B"],
    ["Word", "How is the current page closed?", "File > Exit", "File > Close", "File > Save", "File > New", "B"],
    ["Word", "How can you insert an image in Excel or PowerPoint?", "From the File menu then choose Insert", "From the Insert menu then choose Picture", "From the Layout menu then choose Insert Picture", "From the top toolbar then choose Insert Picture", "B"],
    ["Word", "What page size dimensions does document layout allow in Microsoft Word?", "8.5 × 11 inches (standard size)", "10 × 12 inches", "It can be customized according to the user's needs", "None of above", "C"],
    ["Word", "What is the command used to bold text in Microsoft Office programs?", "Ctrl + I", "Ctrl + U", "Ctrl + B", "Ctrl + S", "C"],
    ["Word", "What is the shortcut Ctrl + S?", "Print", "Save as", "Save", "Open", "C"],

    
    ["PowerPoint", "What is the PowerPoint template file extension?", "pptx", "ppt", "potx", "csv", "C"],
    ["PowerPoint", "What is the shortcut for text replacement (Find and Replace) in presentations?", "Ctrl + F", "Ctrl + H", "Ctrl + M", "Ctrl + D", "B"],
    ["PowerPoint", "What is the number of slides that cannot be printed on one page?", "2 slides per page", "3 slides per page", "5 slides per page", "6 slides per page", "C"],
    ["PowerPoint", "Animated images (animations) can be applied to:", "All slides", "Specific slide", "The current slide", "All of the above", "D"],
    ["PowerPoint", "If you want to print only slide 12 and slide 5, what should you choose?", "Slides", "Custom shows", "Custom view", "Print Current Slides", "A"],
    ["PowerPoint", "How many Slide Layouts are in Microsoft PowerPoint?", "10", "12", "15", "None of above", "D"],
    ["PowerPoint", "What does Outline View mean in Microsoft PowerPoint?", "Display images and videos inside slides", "Display only the main text and headings in slides", "Display slides horizontally", "Display slides while hiding text and headings", "B"],
    ["PowerPoint", "What does View Handout mean in Microsoft PowerPoint?", "Display slides horizontally with effects", "Show only text without slides", "Show images and videos only inside slides", "Display slides arranged on printed handout pages in an organized layout", "D"],
    ["PowerPoint", "Where is a background inserted for a presentation?", "From the Insert tab", "From the Design tab", "From the Review tab", "From the View tab", "B"],

    
    ["Windows", "Where is it preferable to save your files and folders in the operating system?", "My Folder", "My Files", "Documents", "Text", "A"],
    ["Windows", "Where do we find active windows in the Windows operating system?", "In the Start menu", "In the search bar", "On the desktop only", "In the taskbar", "D"],
    ["Windows", "Where are files saved?", "On the desktop", "In the folder or document", "In the taskbar", "Internet folders", "B"],
    ["Windows", "Where can you find the Recycle Bin in the Windows operating system?", "In the taskbar", "On the desktop", "Task manager", "In Files", "B"],
    ["Windows", "Where is the taskbar located?", "Top of the screen", "Next to start button", "Bottom of the screen", "None of above", "C"],
    ["Windows", "What is the shortcut used to show the help menu?", "F1", "F5", "F8", "F9", "A"],
    ["Windows", "What is the shortcut for Select All?", "Ctrl + D", "Ctrl + R", "Ctrl + A", "Ctrl + all", "C"],
    ["Windows", "Shortcut to save a file", "Ctrl + C", "Ctrl + A", "Ctrl + S", "Ctrl + X", "C"],
    ["Windows", "What is the shortcut Ctrl + X?", "Copy selected text or file", "Paste selected text or file", "Cut selected text or file", "Delete selected text or file", "C"],

    
    ["قواعد البيانات", "Which language is used to create or modify database structure, such as tables and keys?", "DDL", "DML", "DCL", "None of above", "A"],
    ["قواعد البيانات", "Which language is used to manage permissions and privileges in a database?", "DDL", "DCL", "DML", "None of above", "B"],
    ["قواعد البيانات", "Which language is used to interact with data inside tables, such as inserting, modifying, or deleting data?", "DDL", "DCL", "DML", "None of above", "C"],
    ["قواعد البيانات", "Which of the following options is NOT considered a database?", "Table", "Report", "Relationship", "Queries", "C"],
    ["قواعد البيانات", "Which device has a large internal storage capacity?", "Personal Computer", "Mobile Phone", "Server", "Client", "C"],

    
    ["الإيميل", "What should you do if you receive an unwanted email?", "Mark it as spam", "Click on the link to verify it", "Forward", "Send it to your friends", "A"],
    ["الإيميل", "If we want to save an incoming email so we can easily return to it later, what is the correct option?", "Trash", "Inbox", "Star", "Draft", "C"],
    ["الإيميل", "The difference between the Inbox and Spam mail", "Inbox messages are promotional, whereas spam messages are important", "The Inbox consists of important or expected messages, whereas spam/junk messages are promotional or unwanted", "Inbox contains promotional messages", "None of above", "B"],
    ["الإيميل", "Sending messages to a single person is considered", "Group message", "Individual message", "Multiple messages", "Hidden message", "B"],
        
    ["الإنترنت", "What is a search engine?", "A tool that searches for images, videos, and texts", "A text editor program", "Browser", "A communication application", "A"],
    ["الإنترنت", "What do you need when connecting to the internet?", "Switch", "Server", "Modem", "Router", "D"],
    ["الإنترنت", "What is a hyperlink?", "Web page", "An element that takes you to another browser or website", "Adding text inside the web", "Downloading an image from the internet", "B"],
    ["الإنترنت", "How can a user's identity be known when logging onto the network?", "By username", "By network name", "By network domain name", "All of above", "A"],
    ["الإنترنت", "Where do files that you download go on your device?", "Upload", "Download", "Move", "Copy", "B"],
    ["الإنترنت", "What does the appearance of a lock next to the page address mean?", "Prevents adults from accessing it", "The page is encrypted", "Prevents the user from entering", "Indicates a connection problem", "B"],
    ["الإنترنت", "What is WAN in computer networks?", "A local network used in homes", "A network to connect devices in the same building", "A network that connects between countries and long distances", "None of above", "C"],
    ["الإنترنت", "What is the benefit of cloud storage?", "Saving data locally", "Accessing data from any device anywhere with internet", "Storing data on the computer only", "Does not allow remote access", "B"],
    ["الإنترنت", "What is ISP stand for?", "Internet Service Provider", "Internet Security Protocol", "Information Security Provider", "Internet Session Provider", "A"],
    ["الإنترنت", "What does HTTPS represent?", "HyperText Transfer Protocol", "A secure version of HTTP", "Transfers browsers", "Transfers files and audio", "B"],
    ["الإنترنت", "What is the Internet?", "A local network connecting computer devices", "A network for managing computer devices", "Programs for viewing web pages only", "A global network connecting computers and devices to exchange information", "D"],


    ["Excel", "What is the shape of the mouse pointer when using autofill for a cell in Excel?", "Large plus sign like a doctor cross", "Small plus sign", "Anchor-shaped mouse pointer", "None of above", "B"],
    ["Excel", "How do you move vertically in Excel?", "Tab", "Shift", "Enter", "Ctrl", "C"],
    ["Excel", "What does the Find and Replace box contain?", "Go to", "Find", "Replace", "All of above", "D"],
    ["Excel", "What does the command Edit >> Delete Comment mean?", "Delete formatting", "Delete comment", "Delete cell contents", "Delete cell", "B"],
    ["Excel", "What is located to the left of the formula bar in Excel?", "Workbook name", "Cell name", "Worksheet name", "Formula name", "B"],
    ["Excel", "What is the maximum character limit for text in a cell in Excel?", "256", "75", "120", "255", "D"],
    ["Excel", "How can you insert margins in Excel?", "From Home tab", "From Page Layout tab", "From Insert tab", "From View tab", "B"],
    ["Excel", "What is the correct method to hide a column in Excel?", "Click on the column then press the Delete key", "Right-click on the column and choose Hide", "Click on the column then choose Hide Column from the ribbon", "Click on the column then press Ctrl + X", "B"],
    ["Excel", "What is the minimum column width in Excel?", "100", "75", "188", "255", "B"],
    ["Excel", "Which of the following series types is invalid in the Excel Series dialog box?", "Linear", "Growth", "Auto fill", "Time", "D"],
    ["Excel", "How can you delete the third worksheet in Excel if you only need two sheets?", "Right-click on the third sheet and choose Delete", "Deletion can be done from a group of cells after selecting the third sheet", "A, B", "None of above", "C"],
    ["Excel", "How can you display sheet headings (headings/gridlines) in Excel?", "From Review tab", "From View tab", "From Insert tab", "From File tab", "B"],
    ["Excel", "How can you change the column width in Excel?", "Select the column, then from the View menu choose guide to resize the column", "Select the column, then from the Home tab choose Format, and then choose Column Width", "Select the column boundary, then double-click with the left mouse button to auto-fit the column width", "Select the column first, then from the check menu choose Guide to change the column width", "B"],
    ["Excel", "What is the function of the MIN function in Excel?", "Find the largest value in a set of numbers", "Calculate the arithmetic mean of a set of numbers", "Find the smallest value in a set of numbers", "Calculate the sum of numbers in a specific range", "C"],
    ["Excel", "How can you merge and center cells in Excel?", "Select the cells, then choose Format > Merge & Center from the Format menu", "Select the cells, then choose Insert > Merge & Center from the toolbar menu", "Select the cells, then click the Merge & Center button from the top ribbon in the Home tab", "Select the cells, then press Ctrl + M to merge and center the cells", "C"],

   
    ["Word", "What is the maximum zoom limit in Microsoft Word?", "200", "400", "600", "500", "D"],
    ["Word", "If there is more than one hyperlink in a Word document, how can you follow them?", "Using the Tab key to navigate between links, then pressing Enter to open them", "Pressing Ctrl + Clicking on each link to follow it", "Opening all links at once by double-clicking", "A, B", "D"],
    ["Word", "What is the shortcut used to find and replace text in Microsoft Word?", "Ctrl + F", "Ctrl + H", "Ctrl + M", "Ctrl + D", "B"],
    ["Word", "Where can you insert a hyperlink?", "Insert > Hyperlink", "View > Hyperlink", "Tools > Hyperlink", "Format > Link", "A"],
    ["Word", "What is the purpose of the ruler in Office?", "Set colors in cells", "Adjust margins and spacing between elements", "Perform mathematical calculations", "Add horizontal and vertical lines", "B"],
    ["Word", "How is the current page closed?", "File > Exit", "File > Close", "File > Save", "File > New", "B"],

   
    ["PowerPoint", "What is the default slide orientation in PowerPoint?", "Landscape", "Portrait", "Vertical", "Italic", "A"],
    ["PowerPoint", "Where can you insert a background in PowerPoint?", "From Insert tab then choosing Background", "From Design tab then choosing Format Background", "From Home tab then choosing Background", "From View tab then choosing Background", "B"],
    ["PowerPoint", "What is the feature added to slides during a slide show?", "Transition", "Move", "Effects", "Background", "A"],
    ["PowerPoint", "What is the shortcut for text replacement (Find and Replace) in presentations?", "Ctrl + F", "Ctrl + H", "Ctrl + M", "Ctrl + D", "B"],

    
    ["مكونات الحاسوب", "What are the physical components of a computer?", "Hardware", "Software", "Operating system", "Program", "A"],
    ["مكونات الحاسوب", "Which of these devices is considered a resource-sharing device?", "Printer", "Personal computer", "Laptop", "Server", "D"],
    ["مكونات الحاسوب", "What is WAN in computer networks?", "A local network used in homes", "A network to connect devices in the same building", "A network that connects between countries and long distances", "None of above", "C"],

   
    ["الإيميل", "If messages are stored in the Spam folder in your email, it means they are:", "Ads from a company or unwanted messages", "From hacker", "From friends", "None of above", "A"],
    ["الإيميل", "What is the difference between the Inbox and Spam mail?", "Inbox messages are promotional, whereas spam messages are important", "The Inbox consists of important or expected messages, whereas spam/junk messages are promotional or unwanted", "Inbox contains promotional messages", "None of above", "B"],
    ["الإيميل", "If we want to save an incoming email so we can easily return to it later, what is the correct option?", "Trash", "Inbox", "Star", "Draft", "C"],
    ["الإيميل", "Sending messages to a single person is considered:", "Group message", "Individual message", "Multiple messages", "Hidden message", "B"],

    
    ["قواعد البيانات", "Which language is used to create or modify database structure, such as tables and keys?", "DDL", "DML", "DCL", "None of above", "A"],
    ["قواعد البيانات", "Which language is used to manage permissions and privileges in a database?", "DDL", "DCL", "DML", "None of above", "B"],
    ["قواعد البيانات", "Which language is used to interact with data inside tables, such as inserting, modifying, or deleting data?", "DDL", "DCL", "DML", "None of above", "C"],
        
    ["Excel", "Long text can be divided into multiple lines within a cell. You can do this through:", "Wrap Text in Format Cells", "Justify in Cell Editing", "Text Wrapping in Format Cells", "All of above", "A"],
    ["Excel", "You can automatically adjust column width by:", "Double-clicking on the column name in the column header", "Double-clicking on the cell pointer in the worksheet", "Double-clicking on the right border of the column in the column header", "Double-clicking on the left border of the column in the column header", "C"],
    ["Excel", "Which of the following methods is incorrect for editing cell content?", "Press the Alt key", "Press the F2 key", "Click on the formula bar", "Double-click on the cell", "A"],
    ["Excel", "Which of the following formats can you specify to apply or not apply in the AutoFormat dialog box?", "Numbers", "Borders", "Fonts", "All of above", "D"],
    ["Excel", "Where can you change the automatic or manual calculation mode in Excel?", "Double CAL indicator in the status bar", "Go to File > Options > Formulas > Calculation options", "All of above", "None of above", "B"],
    ["Excel", "An Excel worksheet consists of:", "Cells and rows only", "Columns and rows only", "Cells, columns, and rows", "Cells and columns only", "C"],
    ["Excel", "How to split a worksheet?", "From View, select Windows then Split", "From Edit, select Split", "From Format Cells, select Split", "None of the above", "A"],
    ["Excel", "What is the function used to find the standard deviation?", "AVERAGE", "SUM", "STDEV", "COUNT", "C"],
    ["Excel", "What is the function used to extract the minimum value in Excel?", "AVERAGE", "MAX", "MIN", "MODE", "C"],
    ["Excel", "What is the maximum character limit for text in a cell in Excel?", "256", "75", "120", "255", "D"],
    ["Excel", "From which option can you rotate text to 45 degrees in Excel?", "From Home > Format Cells", "From Home > Alignment", "From Layout > Text Formatting", "From Home > Text Formatting", "B"],
    ["Excel", "In the View menu, you can display:", "Ruler", "Gridlines", "Header and footer", "All of above", "D"],
    ["Excel", "How can numbers entered in separate cells be converted into a set of ranks in Excel?", "Time symbol", "Comma symbol", "Percentage symbol", "Click on the increase decimal place symbol", "B"],
    ["Excel", "How can you delete the third worksheet in Excel if you only need two sheets?", "Right-click on the third sheet and choose Delete", "Deletion can be done from a group of cells after selecting the third sheet", "A, B", "None of above", "C"],

    
    ["Word", "What is the undo shortcut in Word?", "Ctrl + Z", "Ctrl + Y", "Ctrl + C", "Shift + F2", "A"],
    ["Word", "How can you insert a Layout?", "From file", "From layout", "From design", "None of above", "B"],
    ["Word", "How can you insert a pie chart?", "From the file menu", "From the layout menu", "From the design menu", "None of above", "D"],
    ["Word", "What is the text replacement shortcut in Microsoft Word?", "Ctrl + F", "Ctrl + K", "Ctrl + H", "Ctrl + R", "C"],
    ["Word", "To change the page orientation from portrait to landscape in Word:", "From Insert tab then Layout", "From Layout tab then Page Orientation", "Choose View then Page Orientation", "From Design tab then Page Orientation", "B"],
    ["Word", "When pointing to a text box, what happens?", "8 handles appear around the text box", "Highlight the text", "First and second option", "A broad text selection appears", "A"],
    ["Word", "You can edit an embedded organization chart object by:", "Click on edit object", "Double-click on the chart object", "Right-click on the object and choose edit", "Options B and C together", "D"],

   
    ["PowerPoint", "Which of the following options provides a way to print distinctive notes with a thumbnail slide on the printed page?", "Outline", "Notes Page", "Audience Handout", "Slide with animations", "C"],
    ["PowerPoint", "What is the default slide orientation in PowerPoint?", "Landscape", "Portrait", "Vertical", "Italic", "A"],
    ["PowerPoint", "Where can you insert a background in PowerPoint?", "From Insert tab then choosing Background", "From Design tab then choosing Format Background", "From Home tab then choosing Background", "From View tab then choosing Background", "B"],
    ["PowerPoint", "What is the feature added to slides during a slide show?", "Transition", "Move", "Effects", "Background", "A"],
    ["PowerPoint", "From which menu can you insert a picture, chart, and icon?", "From design", "From insert", "From layout", "From toolbar", "B"],

   
    ["الإنترنت", "What is a search engine?", "A tool that searches for images, videos, and texts", "A text editor program", "Browser", "A communication application", "A"],
    ["الإنترنت", "What is the Internet?", "Local network", "Global network to connect devices", "Private network", "Browser program", "B"],
    ["الإنترنت", "What is HTML?", "HyperText Markup Language", "Hyper Transfer Markup Language", "HighText Markup Language", "HyperText Main Language", "A"],
    ["الإنترنت", "The language named ____ is used to describe the appearance of an image and web page text:", "Java", "HTML", "HTTP", "C++", "B"],
    ["الإنترنت", "What is one of the features of e-learning?", "Long time and difficulty of access", "Internet connection", "Costs with travel savings", "Ease and speed of learning", "D"],
    ["الإنترنت", "What is a hyperlink?", "Web page", "An element that takes you to another browser or website", "Adding text inside the web", "Downloading an image from the internet", "B"],
    ["الإنترنت", "What should you do if you enter a website that looks suspicious to you?", "Refresh the page to see if it changed", "Go back to the previous page and continue browsing", "Close the page and do not give any information", "None of above", "C"],
    ["الإنترنت", "Which of the following options is used to store and download files on the internet?", "Microsoft Edge", "Google Drive", "Microsoft Explorer", "Word", "B"],
    ["الإنترنت", "Which of the following applications supports cloud storage?", "Dropbox", "Microsoft Word", "Google Chrome", "Skype", "A"],
    ["الإنترنت", "Which of the following options is not considered a web browser?", "Microsoft Edge", "Microsoft Windows", "Microsoft Explorer", "None of above", "B"],

    
    ["Windows", "Where is the taskbar located?", "Start menu", "Bottom of the screen", "Top of the screen", "On desktop", "B"],
    ["Windows", "Where do files that you download go on your device?", "Upload", "Download", "Move", "Copy", "B"],
    ["Windows", "What is the name given to a document?", "Files", "Data", "Program", "System", "A"],

   
    ["مكونات الحاسوب", "What are the physical components of a computer?", "Hardware", "Software", "Operating system", "Program", "A"],
    ["مكونات الحاسوب", "Which of these devices is considered a resource-sharing device?", "Printer", "Personal computer", "Laptop", "Server", "D"],
    ["مكونات الحاسوب", "Device that contains the largest internal storage:", "Client", "Server", "Modem", "Tablets", "B"],

   
    ["الإيميل", "Which of the following options is a cloud-based email program?", "Gmail", "Yahoo", "Outlook", "All of above", "D"],
    ["الإيميل", "What are the email messages that you can schedule to send at a later time?", "Snooze", "Schedule", "Attachment", "None of above", "B"],
    ["الإيميل", "Which of the following applications sends messages via email?", "Word", "PowerPoint", "Excel", "Outlook", "D"],

    
    ["قواعد البيانات", "Which of the following options is not considered a database?", "Table", "Report", "Relationship", "Queries", "C"],
       
    ["مكونات الحاسوب", "Q1/ What is the wide network that covers large geographical areas such as countries or continents?", "LAN", "WAN", "MAN", "VPN", "B"],
    ["مكونات الحاسوب", "Q5/ The device used to convert analog signals into digital signals is", "Modulator", "Demodulator", "Modem", "Multiplexer", "C"],
    ["مكونات الحاسوب", "Q6/ Device that contains the greatest internal storage", "Client", "Server", "Modem", "Tablet", "B"],
    ["مكونات الحاسوب", "1 Gigabyte is equal to", "1024 bits", "1032 megabytes", "1024 kilobytes", "1024 megabytes", "D"],
    ["مكونات الحاسوب", "SSD is faster than HDD due to", "SSD with higher storage capacity", "SSD consume more power", "SSD has no moving mechanical parts", "None of the above", "C"],
    ["مكونات الحاسوب", "Which of the following are types of sound files?", "LOG files", "DAT files", "WAV files", "DRV files", "C"],
    ["مكونات الحاسوب", "The .mp3 extension is for which type of file?", "Sound file", "Image file", "Text file", "Word file", "A"],

    
    ["Excel", "Long text can be divided into multiple lines within a cell. You can do this through:", "Wrap Text in Format Cells", "Justify in Cell Editing", "Text Wrapping in Format Cells", "All of above", "A"],
    ["Excel", "You can automatically adjust column width by:", "Double-clicking on the column name in the column header", "Double-clicking on the cell pointer in the worksheet", "Double-clicking on the right border of the column in the column header", "Double-clicking on the left border of the column in the column header", "C"],
    ["Excel", "Which of the following methods is incorrect for editing cell content?", "Press the Alt key", "Press the F2 key", "Click on the formula bar", "Double-click on the cell", "A"],
    ["Excel", "Which of the following formats can you specify to apply or not apply in the AutoFormat dialog box?", "Numbers", "Borders", "Fonts", "All of above", "D"],
    ["Excel", "Where can you change the automatic or manual calculation mode in Excel?", "Double CAL indicator in the status bar", "Go to File > Options > Formulas > Calculation options", "All of above", "None of above", "B"],
    ["Excel", "An Excel worksheet consists of:", "Cells and rows only", "Columns and rows only", "Cells, columns, and rows", "Cells and columns only", "C"],
    ["Excel", "How to split a worksheet?", "From View, select Windows then Split", "From Edit, select Split", "From Format Cells, select Split", "None of the above", "A"],
    ["Excel", "What is the function used to find the standard deviation in Excel?", "AVERAGE", "SUM", "STDEV", "COUNT", "C"],
    ["Excel", "What is the function used to extract the minimum value in Excel?", "AVERAGE", "MAX", "MIN", "MEDIAN", "C"],
    ["Excel", "Where can you hide a row in Excel?", "From the Layout tab and select Hide", "From the Format tab and select Hide", "From the View tab and select Hide", "From the Home tab and select Hide", "D"],
    ["Excel", "What is the main purpose of using the Excel 2016 application?", "To design presentations", "To print and format texts", "To perform mathematical operations only", "To perform calculations and statistical analyses", "D"],
    ["Excel", "When you gather data from a database to include it in a project within Excel, this process is called:", "Data collection", "Data Refinement", "Data analysis", "Data formatting", "A"],
    ["Excel", "How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?", "We select the three cells first, then from the main page menu, we choose Instruct Merge and Center", "We select the three cells first, then from the View menu we choose Instruct Merge", "We double click with the left mouse button on the three cells", "We select the three cells first, then from the Page Layout menu we choose Instruct Merge", "A"],
    ["Excel", "Which function is used to find the median value in a range of numbers?", "Average", "Max", "Median", "Min", "C"],
    ["Excel", "How can numbers entered in separate cells be converted into a set of ranks in Excel?", "Time symbol", "Comma symbol", "Percentage symbol", "Click on the increase decimal place symbol", "B"],

   
    ["Word", "What kind of error does a blue underline that appears below the text represent in MS Word?", "Spelling error", "Capitalization error", "Hyperlink error", "Format consistency checker", "D"],
    ["Word", "What is the text replacement shortcut in Microsoft Word?", "Ctrl + F", "Ctrl + K", "Ctrl + H", "Ctrl + R", "C"],
    ["Word", "To change the page orientation from portrait to landscape in Word:", "From Insert tab then Layout", "From Layout tab then Page Orientation", "Choose View then Page Orientation", "From Design tab then Page Orientation", "B"],
    ["Word", "Which type of fonts are best suited for titles and headlines?", "Serif Fonts", "Sans serif Fonts", "Picture Fonts", "Text Fonts", "B"],
    ["Word", "Which tab is used to insert a table in Word 2016?", "Home", "Insert", "Design", "Layout", "B"],
    ["Word", "Where can you insert page numbers in a Microsoft Word document?", "From the Header and Footer group on the Insert tab", "From the Paragraph group on the Home tab", "From the Page Setup group on the Layout tab", "From the Views group on the View tab", "A"],
    ["Word", "Which menu in Microsoft Word is used to show document information, such as the file name and date of work?", "File menu", "Home menu", "Help menu", "View menu", "A"],
    ["Word", "Which of the following options is used to insert a text box?", "Text box from a group of cells", "Text box from a group of illustrations", "Text box from a group of text", "All the answers given are incorrect", "C"],
    ["Word", "Which of the following tabs in Microsoft Word is used to check for spelling and grammar errors?", "View", "Review", "Spelling & grammar", "Home", "B"],
    ["Word", "What is the shortcut used to undo an action in Word?", "Ctrl + Z", "Ctrl + Y", "Ctrl + C", "Shift + F2", "A"],

    
    ["PowerPoint", "Which option allows you to select line, curve, freeform, or scribble tools?", "Create effect", "Insert motion path", "Draw custom path", "All of the above", "C"],
    ["PowerPoint", "Which of the following options provides a way to print distinctive notes with a thumbnail slide on the printed page?", "Outline", "Notes Page", "Audience Handout", "Slide with animations", "C"],
    ["PowerPoint", "Which of the following can you use to add times to the slides in a presentation?", "Microsoft Graph", "Microsoft Table", "Microsoft Excel", "Microsoft Word", "A"],
    ["PowerPoint", "What is a slide-title master pair?", "The title area and text area of a specific slide", "A slide master and title master merged into a single slide", "A slide master and title master for a specific design template", "All of above", "C"],
    ["PowerPoint", "If you have a presentation you created and want to send it by email to another teacher, you can add the show to your email message as a/an:", "Star icon", "Paperclip icon", "Clip icon", "Forward", "B"],
    ["PowerPoint", "How can you insert a pie chart?", "From the file menu", "From the layout menu", "From the design menu", "None of above", "D"],

   
    ["الإنترنت", "Using the internet to download the latest version of a program is an example of:", "Software update", "System maintenance", "Backup", "Quality control", "A"],
    ["الإنترنت", "What does HTTPS represent?", "HyperText Transfer Protocol", "Secure version of HTTP", "Transfers browsers", "Transfers files and audio", "B"],
    ["الإنترنت", "What is the Internet?", "Local network", "Global network to connect devices", "Private network", "Browser program", "B"],
    ["الإنترنت", "When the internet disconnects, how can a web page be opened without a connection?", "POP", "DCL", "Cache", "Cookies", "C"],
    ["الإنترنت", "What is an internet search engine?", "A program that checks web pages for viruses", "A program that updates web pages", "A program that searches the internet for specific words, images, or videos", "A program that creates a network connection", "C"],
    ["الإنترنت", "What is one of the features of e-learning?", "Long time and difficulty of access", "Internet connection", "Costs with travel savings", "Ease and speed of learning", "D"],
    ["الإنترنت", "What is Wi-Fi?", "Wired connection technique", "Wireless connection of devices", "Local network", "None of the above", "B"],
    ["الإنترنت", "What cookie in web browsing?", "Text file information about user stored by website", "To copy the data and transfer it to the unauthorized user", "Type of malware", "None of the above", "A"],
    ["الإنترنت", "Which of the following options is used to store and download files on the internet?", "Microsoft Edge", "Google Drive", "Microsoft Explorer", "Word", "B"],
    ["الإنترنت", "What is the difference between the web and the Internet?", "The web is faster than the Internet", "The web is a global network connecting computers together", "The web is part of the Internet that uses the HTTP protocol to display content through browsers", "The Internet has no protocols, while the web only uses HTTP", "C"],

    
    ["Windows", "Which folder contains installed applications by default?", "Document", "Program files", "Windows", "Download", "B"],
    ["Windows", "What shortcut key is used to delete a file permanently in Windows?", "Delete", "Backspace", "Shift + Delete", "F2", "C"],
    ["Windows", "Desktop background is called:", "Graphics", "Layout", "Background image", "Wallpaper", "D"],
    ["Windows", "Which key is responsible for refreshing?", "F1", "F2", "F5", "F12", "C"],
    ["Windows", "Which of the following shortcuts is used to open Windows Task Manager directly?", "CTRL + SHIFT + ESC", "CTRL + ALT + Delete", "Windows + T", "Windows + M", "A"],
    ["Windows", "Which Windows tool is used to change or increase the display resolution?", "Device manager", "Display settings", "Task manager", "All of above", "B"],
    ["Windows", "Where can we see the file path?", "Desktop", "Address bar", "Taskbar", "File explorer", "B"],
    ["Windows", "What is the name given to the document?", "Files", "Data", "Program", "System", "A"],

    
    ["قواعد البيانات", "What is the process of gathering data from a database to include it in an Excel project called?", "Data collection", "Data Refinement", "Data analysis", "Data formatting", "A"],

    
    ["الإيميل", "Which of the following options is a cloud-based email program?", "Gmail", "Yahoo", "Outlook", "All of above", "D"],
    ["الإيميل", "What are the email messages that you can schedule to send at a later time?", "Snooze", "Schedule", "Attachment", "None of above", "B"],
       
    ["قواعد البيانات", "Which of the field has width 8 bytes?", "DataTime", "Memory", "Number", "Link", "A"],

    
    ["Excel", "The number of rows in an Excel 2016 worksheet is", "1000000", "16232", "1048576", "16384", "C"],
    ["Excel", "The number of columns in an Excel 2019 worksheet is", "1000000", "16232", "1048576", "16384", "D"],
    ["Excel", "How do you tilt the book at a 45 degree angle?", "From the Page Layout menu, we press the Direction button in the Degree box, we type 45.", "From the View menu, we press the Alignment button in the Degree box, we type 45.", "From the main menu, we press the Align button in the Degree box, we write 45.", "All the answers received are incorrect.", "D"],
    ["Excel", "Where are the control buttons located in Microsoft Excel?", "Formula bar", "Title bar", "Menu bar", "Toolbar", "B"],
    ["Excel", "What happens when you press Ctrl + X after selecting some cells in Excel?", "The selected cells are deleted and the cells move to the left.", "The selected cells are deleted and the cells move up.", "The selected cells are outlined for cutting.", "The contents of the selected cells disappear from the cell and are stored in the clipboard.", "C"],
    ["Excel", "Which function is used to calculate the standard deviation?", "AVERAGE", "COUNTIF", "STDEV", "MEDIAN", "C"],
    ["Excel", "The small black square in the lower right corner of an active cell or range represents", "Fill Handle", "Border", "Handle Appended", "Handle Copy", "A"],
    ["Excel", "The first cell in the worksheet in Excel is", "Aa", "AA", "A0", "A1", "D"],
    ["Excel", "Among the components of the main screen of Excel", "Drawing, functions", "Exit, data analysis", "View, reports", "Home, Inserts", "D"],
    ["Excel", "To close the current workbook in use, click on the option in the menu", "Close, Home Page", "Close, View", "Close, Office", "Close, Title Bar", "C"],
    ["Excel", "Which tool would you use to merge cells and center the content within the merged cell?", "From the Format Cells box, click Merge & Center.", "From the Format Cells box, choose Alignment Center.", "From the Format Cells dialog box, choose Merge & Center.", "Click the Merge & Center tool on the Formatting toolbar.", "D"],
    ["Excel", "If you have three default worksheets in Excel, how would you delete the third sheet?", "Select the sheet, right-click, and choose Delete", "From the menu, select the sheet and choose Delete from Edit", "Both of the above", "None of the above", "A"],
    ["Excel", "What does the shortcut Ctrl + D do in Microsoft Excel?", "Fill up", "Fill down", "Duplicate sheet", "Delete cell", "B"],

    
    ["Word", "What is the shortcut to make selected text left alignment?", "Alt + I", "Ctrl + L", "F10", "Shift + I", "B"],
    ["Word", "Which view is considered the best and most precise for editing text in Microsoft Word?", "Draft view", "Outline view", "Web layout", "Print view", "A"],
    ["Word", "The Save command is present under the", "Home tab", "Office tab", "View tab", "Review tab", "B"],
    ["Word", "Which tab is used to perform spelling and grammar check in Microsoft Word?", "View", "Design", "Layout", "Review", "D"],
    ["Word", "How can you print a specific number of pages in Word?", "From the File menu, choose Print, then enter the required page numbers in the Pages box.", "From Layout choose Print", "From Insert choose Select Pages", "From View choose Specific Print", "A"],
    ["Word", "Which of the following options allows you to select more than one slide in a presentation?", "Alt + click each slide", "Shift + drag each slide", "Shift + click each slide", "Ctrl + click each slide", "D"],

    
    ["PowerPoint", "Which option allows you to select line, curve, freeform, or scribble tools?", "Create effect", "Insert motion path", "Draw custom path", "All of the above", "C"],
    ["PowerPoint", "The Microsoft Clip Gallery allows you to", "Add WordArt images to a slide", "Spell check your presentation", "Add clip art images to a slide or slides", "Add slides to a presentation", "C"],
    ["PowerPoint", "Which of the following options provides a way to print distinguished notes with a thumbnail slide on the printed page?", "Outline", "Notes Page", "Handouts", "Slide with animation", "C"],
    ["PowerPoint", "What is a slide-title master pair?", "The title area and text area of a specific slide", "A slide master and title master merged into a single slide", "A slide master and title master for a specific design template", "All of above", "C"],
  
    ["الإنترنت", "What is the abbreviation for ISP?", "Internet System Provider", "Internet Service Provider", "Internal Security Protocol", "International Software Platform", "B"],
    ["الإنترنت", "Which tool enables a researcher to obtain references from the internet?", "Yahoo", "Netscape", "Outlook", "MS Explorer", "A"],
    ["الإنترنت", "What primary function does a web browser perform?", "To send and receive emails", "To display and navigate web pages", "To create website", "To store large amounts of data", "B"],
    ["الإنترنت", "If a website is not loading correctly, which action might help resolve the issue?", "Delete your browsing history", "Turn off your computer", "Disable WiFi", "Refresh the page or clear your browser cache", "D"],
    ["الإنترنت", "What does the Lock icon appearing at the page mean?", "The user cannot access the page", "The page is encrypted", "Prevents adults from accessing it", "The page is unavailable due to a server error", "B"],
    ["الإنترنت", "Which of these options allows users to store and access files over the Internet?", "USB", "Google Drive", "Hard drive", "Monitor", "B"],
    ["الإنترنت", "What is an internet search engine?", "A program that checks web pages for viruses", "A program that updates web pages", "A program that searches the internet for specific words, images, or videos", "A program that creates a network connection", "C"],

    
    ["Windows", "Before you can perform any action on a file or folder, what must you do?", "Select the file or folder", "Log in to the computer again", "Start File Explorer twice", "Create a shortcut for the file or folder", "A"],
    ["Windows", "Which of the following options is used to access a file from the computer store?", "Insert", "Retrieve", "File", "Print", "B"],
    ["Windows", "Which of the following options is a physical component of a computer?", "Software", "Hardware", "Programming Language", "Operating System", "B"],
    ["Windows", "Which component of the CPU register holds the address of the next instruction?", "Program Counter", "Accumulator", "Instruction Register", "Data Register", "A"],

    
    ["الإيميل", "Which protocol is commonly used for sending email?", "HTTPS", "FTP", "SMTP", "TCP", "C"],
    ["الإيميل", "If you receive a message from a friend sent to a number of people and you want to respond to everyone, do you use the command", "Forward", "Reply", "Signature", "Reply to all", "D"],

    
    ["مكونات الحاسوب", "TB means", "Tera Byte", "Tera bit", "Tilo Byte", "Tilo bit", "A"],
       
    ["Excel", "Can you set borders for a worksheet or page in Excel?", "Yes, from the Line Style tool in the drawing ribbon.", "Yes, from the Border tool in the formatting ribbon.", "Yes, from the Border tab in the Format Cells dialog box.", "No, you cannot set borders for a worksheet.", "D"],
    ["Excel", "How to hide 49th grade from being visible?", "Cells - hide and show hide rows", "Formatting - Hide and Show - Hide", "Rows Edit - Hide and Show - Hide", "All answers given are incorrect", "B"],
    ["Excel", "How can listed numbers in separated cells be converted to a set of ranks in Excel?", "In the Home tab, click the Time icon.", "In the Home tab, click the comma symbol.", "In the Home tab, click the Percentage symbol.", "In the Home tab, click the Increase Decimal symbol.", "B"],
    ["Excel", "How to convert the number listed in a divided cell into a group of ranks in Microsoft Excel?", "Home tab, then click on the time icon", "Home tab, then click on the comma symbol", "Home tab, then click on the percentage symbol", "Home tab, then click on the symbol to increase decimal places", "B"],
    ["Excel", "How can you always show row 1 when moving to pages?", "Press to freeze the upper parts", "Pressing the button Freeze Panes freeze the top row", "Click on Freeze Titles", "All answers given are incorrect", "B"],
    ["Excel", "Where are the control buttons located in Microsoft Excel?", "Formula bar", "Title bar", "Menu bar", "Toolbar", "B"],
    ["Excel", "Excel displays the current cell address in:", "Formula bar", "Name box", "Status bar", "Title bar", "B"],
    ["Excel", "The function considered a statistical function is:", "Average()", "sin()", "log()", "exp()", "A"],
    ["Excel", "The cell pointer that helps in moving or copying content to other cells is:", "Large plus sign (Doctor's symbol)", "Small plus sign icon", "Mouse pointer with a small mark at the edge", "None of the above", "C"],
    ["Excel", "On which part of the chart are the values entered in a data sheet displayed?", "The Title Area", "The Legend", "The Y-Axis", "The X-Axis", "C"],
    ["Excel", "A ______ consists of a set of rows and columns in Excel.", "Worksheet", "Workbook", "Cells", "Pages", "A"],
    ["Excel", "When you modify a data value in an Excel worksheet that was used to create a chart, what happens to the chart?", "The chart formatting and design are completely lost.", "The chart type automatically changes to a default column chart.", "The chart automatically updates to reflect the new value without changing its type or format.", "The chart becomes static and will no longer accept any future changes.", "C"],
    ["Excel", "To make the text in the cell fit the border, we click the button:", "Format Autofit column width", "Cells Autofit column width", "Edit Autofit column width", "All answers given are incorrect", "A"],
    ["Excel", "To set the row height, press the button:", "Cells row height", "Format row height", "Edit row height", "All answers given are incorrect", "B"],

    
    ["Word", "In MS Word, you can insert a footnote at the bottom of the page from:", "Design tab > Insert Footnote", "Layout tab > Insert Footnote", "References tab > Insert Footnote", "Insert tab > Insert Footnote", "C"],
    ["Word", "To go directly to a page in the document based on the page number, use:", "Ctrl + O", "Ctrl + H", "Ctrl + G", "Ctrl + A", "C"],
    ["Word", "Which view is considered the best and most precise for editing text in Microsoft Word?", "Draft view", "Outline view", "Web layout", "Print view", "A"],
    ["Word", "What types of numbers can be inserted in the Word application?", "English numbers only", "Arabic numbers only", "Both Arabic and English", "None of above", "C"],
    ["Word", "Which view shows a structure of headings at different levels in MS Word?", "Print layout", "Web layout", "Outline view", "Slide sorter view", "C"],

    
    ["PowerPoint", "Which of the following allows you to select more than one slide in a presentation?", "Alt + click each slide", "Shift + drag each slide", "Shift + click each slide", "Ctrl + click each slide", "D"],
    ["PowerPoint", "What is the best way to create another copy of a slide?", "Redo everything on a new slide that you had done on the previous slide", "Click the slide then press Ctrl+A and paste in new slide", "From Insert Menu choose Duplicate Slide", "None of above", "C"],
    ["PowerPoint", "What is the term used when a Clip Art image changes the direction of faces?", "Group", "Flip", "Rotate", "All of the above", "B"],
    ["PowerPoint", "The Microsoft Clip Gallery allows you to:", "Add WordArt images to a slide", "Spell check your presentation", "Add clip art images to a slide or slides", "Add slides to a presentation", "C"],
    ["PowerPoint", "Which of the following options provides a way to print distinguished notes with a thumbnail slide on the printed page?", "Outline", "Notes Page", "Handouts", "Slide with animation", "C"],

    
    ["الإنترنت", "What is the abbreviation for ISP?", "Internet System Provider", "Internet Service Provider", "Internal Security Protocol", "International Software Platform", "B"],
    ["الإنترنت", "Which protocol is commonly used for sending email?", "HTTPS", "FTP", "SMTP", "TCP", "C"],
    ["الإنترنت", "Which tool enables a researcher to obtain references from the internet?", "Yahoo", "Netscape", "Outlook", "MS Explorer", "A"],
    ["الإنترنت", "What is the primary function of a web browser?", "To send and receive emails", "To display and navigate web pages", "To create website", "To store large amounts of data", "B"],
    ["الإنترنت", "If a website is not loading correctly, which action might help resolve the issue?", "Delete your browsing history", "Turn off your computer", "Disable WiFi", "Refresh the page or clear your browser cache", "D"],
    ["الإنترنت", "What does the Lock icon appearing at the page mean?", "The user cannot access the page", "The page is encrypted", "Prevents adults from accessing it", "The page is unavailable due to a server error", "B"],
    ["الإنترنت", "What is the process of transferring programs from the internet to a computer called?", "Uploading", "Downloading", "Transferring", "Copying", "B"],
    ["الإنترنت", "When the internet disconnects, how can a web page be opened without a connection?", "POP", "DCL", "Cache", "Cookies", "C"],
    ["الإنترنت", "What is the primary protocol used to secure data transmission over the internet?", "FTP", "HTTPS", "HTTP", "IP", "B"],
    ["الإنترنت", "What should you do if you enter a website that seems suspicious?", "Refresh the page to see if it changes.", "Go back to the previous page and continue browsing.", "Close the page and do not provide any information.", "Search inside the page.", "C"],
    ["الإنترنت", "Which of these options allows users to store and access files over the Internet?", "USB", "Google Drive", "Hard drive", "Monitor", "B"],
    ["الإنترنت", "The fastest internet network is:", "WiFi", "Satellite", "Fiber optic", "None of above", "C"],

    
    ["Windows", "Which unit displays visual output?", "Printer", "Monitor", "Keyboard", "Mouse", "B"],
    ["Windows", "Where can you usually find a deleted file in Windows?", "Recycle Bin", "Desktop", "Task Manager", "File Explorer", "A"],
    ["Windows", "Before you can perform any action on a file or folder, what must you do?", "Select the file or folder", "Log in to the computer again", "Start File Explorer twice", "Create a shortcut for the file or folder", "A"],
    ["Windows", "Which of the following actions will create a new folder on a Windows desktop?", "Close or delete the new folder", "Right-clicking any place on the desktop and selecting New > Folder", "Press Alt + new folder", "All of above incorrect", "B"],
    ["Windows", "When an image is selected, it displays which of the following?", "Two Corner Handles", "Six Middle Handles", "Eight Sizing Handles", "Six Boxes", "C"],
    ["Windows", "Recently opened files are stored in:", "Recycle Bin", "Desktop", "Taskbar", "File Explorer", "D"],
    ["Windows", "To set the size of desktop icons:", "Left-click the desktop, select Unview, and then select Large icons, Medium icons, or Small icons.", "Right-click the desktop, select Unview, and then select Very Large icons, Large icons, Medium icons, Small icons.", "Right-click the desktop, select View, and then select Large icons, Medium icons, or Small icons.", "All the provided answers are correct", "C"],

    
    ["مكونات الحاسوب", "A computer consists of:", "A central processing unit", "A memory", "Input and output unit", "All of these", "D"],
    ["مكونات الحاسوب", "Which component is described as physical parts?", "Software", "Hardware", "Programming Language", "Operating System", "B"],
    ["مكونات الحاسوب", "Memory used to temporarily store data to improve access speed:", "ROM", "Hard disk drive", "Cache", "None of above", "C"],

    
    ["الإيميل", "How is an email set to be sent at a later time?", "Schedule", "Archive", "Direct send", "Snooze", "A"],
    ["الإيميل", "What is the primary definition of E-commerce?", "Marketing of goods and services.", "The buying and selling of goods and services over the internet.", "Internal communication within a single corporate local area network.", "None of above", "B"],
    ["الإيميل", "What does the shortcut Ctrl + D do in Microsoft Excel?", "Fill up", "Fill down", "Duplicate sheet", "Delete cell", "B"],

    ["مكونات الحاسوب", "CD-ROM means:", "Compact digital ROM", "Compact Driver ROM", "Compact Disk ROM", "Compactable disk ROM", "C"],
    ["مكونات الحاسوب", "Which unit displays visual output?", "Printer", "Monitor", "Keyboard", "Mouse", "B"],
    ["مكونات الحاسوب", "A computer consists of:", "A central processing unit", "A memory", "Input and output unit", "All of these", "D"],
    ["مكونات الحاسوب", "What is Fiber optic?", "A wireless network that uses radio waves to transmit data.", "A storage device used to save large system backup files.", "A technology that provides high speed internet using light signals.", "A type of software used to protect computers from viruses.", "C"],
    ["مكونات الحاسوب", "Which of the following ports is designed to connect a wide variety of peripheral devices to a computer?", "VGA", "Ethernet", "HDMI", "USB", "D"],
    ["مكونات الحاسوب", "Which term describes the ability of a computer to perform multiple tasks?", "Throughput", "Multitasking", "Multiprocessing", "Batch Processing", "B"],
    ["مكونات الحاسوب", "What is the meaning of Phishing?", "Updating system software safely.", "Information hacking", "Tricking users to download for stealing data.", "Sending promotional messages", "C"],
    ["مكونات الحاسوب", "Memory used to temporarily store data to improve access speed:", "ROM", "Hard disk drive", "Cache", "None of above", "C"],

    ["Excel", "Which tool will you use to join some cells and place the content at the middle of the joined cell?", "From Format Cells dialog box choose Merge and Center check box", "From Format Cells dialog box click on Merge Cells check box", "From Format Cells dialog box select the Centered alignment", "Click on Merge and Center tool on formatting toolbar", "D"],
    ["Excel", "Which option is used to unmerge cells?", "Merge & Center", "Cell style", "Formatting table", "None", "A"],
    ["Excel", "To calculate the number of failing students in a specific stage, which function is used?", "Count", "Count if", "Sum", "Sum if", "B"],
    ["Excel", "How to convert columns to row in Excel?", "Cut paste", "Paste special > Transpose", "Both", "None", "B"],
    ["Excel", "Which command combination is used to move the content of a cell to another cell in Excel?", "Cut and Copy", "Copy and Paste", "Cut and Paste", "None of the above", "C"],
    ["Excel", "If values (18, 5, 6) are used with MAX, what is the result?", "5", "6", "25", "18", "D"],
    ["Excel", "Which of the following action removes a sheet from workbook?", "Select sheet then choose Home > Cell > Format > Hide", "Select sheet then choose Home > Cell > Delete", "Both", "None of above", "B"],
    ["Excel", "How can listed numbers in separated cells be converted to a set of ranks in Excel?", "In the Home tab, click the Time icon.", "In the Home tab, click the comma symbol.", "In the Home tab, click the Percentage symbol.", "In the Home tab, click the Increase Decimal symbol.", "B"],

    
    ["Word", "Where do you insert Symbols in Word?", "Home tab > Editing", "Insert tab > Symbol", "Insert tab > Equation", "None of above", "B"],
    ["Word", "How can you create a bulleted list in Word?", "Home", "Layout", "Insert", "Review", "A"],
    ["Word", "Which of the following is not a font style in MS Word?", "Bold", "Italic", "Regular", "Superscript", "D"],
    ["Word", "To move the cursor page to page of document, which shortcut is used?", "Ctrl + PgUp", "Ctrl + PgDn", "Both of above", "None of above", "C"],

    
    ["PowerPoint", "Which of the following is not a part of Slide Design?", "Design Template", "Color Scheme", "Animation Scheme", "Slide Layout", "D"],
    ["PowerPoint", "Which of the following pane is NOT available in Task Pane?", "Slide Design", "Master Slide", "Slide Layout", "Slide Transition", "B"],
    ["PowerPoint", "To change font size of a selected slide title:", "Click the toolbar Increase Font Size button", "Click Title > New Font", "Click Format and choose a font from the Font tab", "Click the toolbar Font dropdown arrow and choose the font", "A"],

    
    ["Windows", "Which key is used to open the Start Menu in Windows?", "Shift", "Windows key", "Ctrl", "Alt", "B"],
    ["Windows", "Which folder contains user documents?", "Windows", "Program files", "Temp", "Documents", "D"],
    ["Windows", "Where do you usually find a deleted file in Windows?", "Recycle Bin", "Desktop", "Task Manager", "File Explorer", "A"],
    ["Windows", "Which tool checks disk errors?", "Disk Cleanup", "Defragment", "Check Disk (chkdsk)", "Backup", "C"],
    ["Windows", "Which of the following options is the most efficient way to back up your data using cloud storage?", "Upload individual files manually each time", "Set up automatic synchronization between your device and cloud storage", "Save files on an external hard drive and upload them manually", "Transfer files using email attachments to yourself", "B"],

    
    ["الإنترنت", "What is an IP address used for?", "Logging into a website", "Used for device addressing in internet", "Sending emails", "Storing files on the cloud", "B"],
    ["الإنترنت", "What is the process of transferring programs from the internet to a computer called?", "Uploading", "Downloading", "Transferring", "Copying", "B"],
    ["الإنترنت", "When the internet disconnects, how can a web page be opened without a connection?", "POP", "DCL", "Cache", "Cookies", "C"],
    ["الإنترنت", "What should you do if you enter a website that seems suspicious?", "Refresh the page to see if it changes.", "Go back to the previous page and continue browsing.", "Close the page and do not provide any information.", "Search inside the page.", "C"],
    ["الإنترنت", "What is the primary protocol used to secure data transmission over the internet?", "FTP", "HTTPS", "HTTP", "IP", "B"],
    ["الإنترنت", "What is the fastest internet network?", "WiFi", "Satellite", "Fiber optic", "None of above", "C"],
  
    ["الإيميل", "How is an email set to be sent at a later time?", "Schedule", "Archive", "Direct send", "Snooze", "A"],
    ["الإيميل", "What program is responsible for email?", "Access", "Outlook", "PowerPoint", "Google", "B"],
    
    ["مكونات الحاسوب", "CD-ROM means:", "Compact digital ROM", "Compact Driver ROM", "Compact Disk ROM", "Compactable disk ROM", "C"],
    ["مكونات الحاسوب", "Communication system that transfers data between the components of a computer is:", "ALU", "System bus", "CPU", "Register", "B"],
    ["مكونات الحاسوب", "Which port is the most common port used to connect input and output devices to a computer?", "USB", "Ethernet port", "VGA", "Audio port", "A"],
    ["مكونات الحاسوب", "Which device converts signal digital to printed output?", "Monitor", "Printer", "Scanner", "Speaker", "B"],
    ["مكونات الحاسوب", "Which memory is built directly into the CPU?", "RAM", "Cache", "Register", "HDD", "B"],
    ["مكونات الحاسوب", "Which of the following has the smallest memory capacity?", "RAM", "Register", "Cache", "Hard disk", "B"],
    ["مكونات الحاسوب", "Which device converts analog signals to digital signals and vice versa?", "Router", "Protocol", "Modem", "Server", "C"],
    ["مكونات الحاسوب", "Which type of software helps maintain a computer system?", "Utility Software", "Application Software", "Programming Software", "Firmware software", "A"],
    ["مكونات الحاسوب", "Which of the following options is a physical component of a computer?", "Software", "Hardware", "Programming Language", "Operating System", "B"],
    ["مكونات الحاسوب", "What is Fiber optic?", "A wireless network that uses radio waves to transmit data.", "A storage device used to save large system backup files.", "A technology that provides high speed internet using light signals.", "A type of software used to protect computers from viruses.", "C"],

   
    ["Excel", "For more options or change settings in Microsoft Excel (Advanced Options):", "Home / options", "File / options", "Insert / options", "View / settings", "B"],
    ["Excel", "Which option is used to unmerge cells?", "Merge & Center", "Cell style", "Formatting table", "None", "A"],
    ["Excel", "To calculate the number of failing students in a specific stage, which of the following functions is used?", "Count", "Count if", "Sum", "Sum if", "B"],
    ["Excel", "How many worksheets can a workbook have?", "3", "8", "255", "None of above", "D"],
    ["Excel", "How to convert columns to row in Excel?", "Cut paste", "Paste special > Transpose", "Both", "None", "B"],
    ["Excel", "Which command combination is used to move the content of a cell to another cell in Excel?", "Cut and Copy", "Copy and Paste", "Cut and Paste", "None of the above", "C"],
    ["Excel", "If values (18, 5, 6) are used with MAX, what is the result?", "5", "6", "25", "18", "D"],
    ["Excel", "Which of the following action removes a sheet from workbook?", "Select sheet then choose Home > Cell > Format > Hide", "Select sheet then choose Home > Cell > Delete", "Both", "None of above", "B"],
    ["Excel", "In Excel, the column header consists of:", "Arabic letter", "English letter", "English letter with number", "Number only", "B"],
    ["Excel", "If the values (18, 5, 2, 6) are used with the MIN function in Excel, what is the result?", "18", "6", "0", "2", "D"],
    ["Excel", "Which use magnetic disk to store data?", "SSD", "RAM", "Hard disk drive", "USB flash drive", "C"],
    ["Excel", "Which function key is used in Microsoft Excel to update data and formulas?", "F8", "F9", "F10", "F12", "B"],
    ["Excel", "The Legend in Excel charts is:", "Non-existent", "Existing and cannot be modified", "Existing and can be modified", "None of above", "C"],


    ["Word", "Where do you insert Symbols in Word?", "Home tab > Editing", "Insert tab > Symbol", "Insert tab > Equation", "None of above", "B"],
    ["Word", "Which of the following is used to insert a date and time in a Word document?", "Insert", "View", "Review", "Layout", "A"],
    ["Word", "What are the advantages of using styles in Word?", "Insert watermark", "Insert font", "Insert format", "Insert chart", "C"],
    ["Word", "Where is the Ruler enabled from?", "Home tab > Paragraph", "Insert tab > Shape", "File tab > Options", "View tab > Ruler", "D"],
    ["Word", "Which program is used to create a resume or CV?", "Excel", "PowerPoint", "Word", "None of above", "C"],
    ["Word", "In MS Word, which tool is used to copy text formatting?", "Copy", "Paste", "Cut", "Format painter", "D"],
    ["Word", "In Microsoft Word, what does Draft View do?", "It displays and allows editing of text with headers and footers.", "It displays and allows editing of text without headers and footers.", "It hides the text and only shows headers and footers.", "None of above", "B"],
    ["Word", "To change the Line Spacing of a text in MS Word:", "Right-click the selected text > from Font > Change the Spacing settings.", "Right-click the selected text > Select Paragraph > Adjust the Line spacing", "From font size select line spacing", "None of the above", "B"],
    ["Word", "To move the cursor page to page of document, which shortcut is used?", "Ctrl + PgUp", "Ctrl + PgDn", "Both of above", "None of above", "C"],
    ["Word", "What is the function of the shortcut Ctrl + E in Microsoft Word?", "Right alignment", "Left alignment", "Center alignment", "Justify", "C"],
    ["Word", "What is the default view option of MS Word document?", "Draft", "Outline", "Print layout", "Web layout", "C"],
    ["Word", "To apply a different Theme to your document, you go to:", "Design tab > Themes group", "Insert tab > Themes", "Home tab > Styles group", "Layout tab > Page Setup", "A"],
 
    ["PowerPoint", "Presentation: if you need to click a slide that is a few slides back, how do you get there?", "Press backspace until your desired slide", "Press ESC to return to normal view, click the slide thumbnail, then resume the slide show", "Right-click, point to Go to Slide, and click the slide you want", "All of above", "D"],
    ["PowerPoint", "The PowerPoint view that displays only text (titles and bullets) is:", "Slide show", "Slide sorter view", "Notes page view", "Outline view", "D"],
    ["PowerPoint", "In MS-PowerPoint, the effect applied to display when slides change in slide show view is:", "Custom transition", "Custom animation", "Slide transition", "Slide animation", "C"],
    ["PowerPoint", "What is the primary purpose of PowerPoint?", "To write emails", "To create presentations", "To browse the internet", "To edit spreadsheets", "B"],
    ["PowerPoint", "To change font size of a selected slide title:", "Click the toolbar Font dropdown arrow and choose the font you prefer", "Click Format, Title and choose a font from the font tab", "Click the toolbar Increase Font Size button", "Click Title, New Font, OK", "C"],
    ["PowerPoint", "Which of the following is not a part of Slide Design?", "Design Template", "Color Scheme", "Animation Scheme", "Slide Layout", "D"],
    ["PowerPoint", "Which of the following pane is NOT available in Task Pane?", "Slide Design", "Master Slide", "Slide Layout", "Slide Transition", "B"],


    ["الإنترنت", "Software used to access and navigate web pages is called a:", "Search engine", "Operating system", "Web server", "Web browser", "D"],
    ["الإنترنت", "What is an IP address used for?", "Logging into a website", "Used for device addressing in internet", "Sending emails", "Storing files on the cloud", "B"],
    ["الإنترنت", "What is the main purpose of responsive design?", "To make website faster", "To make website work on all screen sizes", "To reduce HTML size", "To remove CSS", "B"],
    ["الإنترنت", "Which protocol is responsible for transferring files over the network?", "TCP", "HTTP", "FTP", "DNS", "C"],
    ["الإنترنت", "What is the internet?", "Search engine", "Web browser", "Network of networks", "Email electrical", "C"],
    ["الإنترنت", "Which of the following options is the most efficient way to back up your data using cloud storage?", "Upload individual files manually each time", "Set up automatic synchronization between your device and cloud storage", "Save files on an external hard drive and upload them manually", "Transfer files using email attachments to yourself", "B"],

    ["Windows", "Which key is used to open the Start Menu in Windows?", "Shift", "Windows key", "Ctrl", "Alt", "B"],
    ["Windows", "The tool responsible for scheduling orders in Windows is:", "Scheduler tool", "Taskbar", "Task manager", "Application", "A"],
    ["Windows", "Which of the following shortcuts is used to open File Explorer in Windows?", "Win + F", "Alt + E", "Win + E", "Ctrl + F", "C"],
    ["Windows", "In Windows, Start button is used to:", "Run application", "Device settings", "Turn off the system", "All of above", "D"],
    ["Windows", "Which key is used to rename file in Windows?", "F1", "F2", "F5", "F12", "B"],
    ["Windows", "Which tool checks disk errors?", "Disk Cleanup", "Defragment", "Check Disk (chkdsk)", "Backup", "C"],
    ["Windows", "Which of the following tools helps restore your system to a previous working state?", "Task Manager", "File Explorer", "Disk Cleanup", "System Restore", "D"],
    ["Windows", "A full volume encryption feature included with Microsoft Windows versions is:", "Firewall", "Antivirus", "BitLocker", "None of above", "C"],

    ["الإيميل", "What is the purpose of the archive feature in email?", "To store old emails without deleting them", "To send emails to multiple recipients", "To delete junk emails", "To save a draft of an email", "A"],
    ["الإيميل", "Which program office is responsible for sending e-mail?", "Access", "Outlook", "PowerPoint", "Google", "B"],
    ["الإيميل", "How can you easily distinguish important emails for quick access?", "Add it to the Archive", "Mark as unread", "Add a star to it", "Send it to Trash", "C"],

    
    ["قواعد البيانات", "In an organizational structure that contains a president, vice presidents, managers, and supervisors, in which type of planning do the vice presidents come after the president?", "Circular", "Network", "Horizontal", "Hierarchical", "D"],
    ["الإنترنت", "What is internet speed measured in?", "Pixels", "Watts", "Liters", "Mbps", "D"],
  ["مكونات الحاسوب", "Which memory is volatile?", "ROM", "Hard Disk", "RAM", "Flash Memory", "C"],
  ["مكونات الحاسوب", "Which storage device has no moving mechanical parts?", "HDD", "Optical Disk", "SSD", "Magnetic Tape", "C"],
  ["PowerPoint", "Objects on the slide that hold text are called", "Placeholders", "Object holders", "Auto layout", "Text holders", "A"],
  ["مكونات الحاسوب", "Which term describes the ability of a computer to perform multiple tasks?", "Throughput", "Multitasking", "Multiprocessing", "Batch Processing", "B"],
  ["الإنترنت", "It is a network that can connect two or more devices to share resources (data, equipment) in different places with each other across a wide geographical area.", "(Wide Area Network) WAN", "(Local Area Network) LAN", "(Internet)", "(Intranet)", "A"],
  ["Word", "Which of the following is not a view option in Word 2016?", "Read Mode", "Print Layout", "Draft", "Presentation Mode", "D"],
  ["PowerPoint", "Which of the following allow you to select more than one slide in a presentation?", "Alt + Click each slide", "Shift + drag each slide", "Shift + Click each slide", "Ctrl + Click each slide", "D"],
  ["الإنترنت", "What is a VPN?", "Printer port", "Secure private network connection", "Cloud disk", "Programming library", "B"],
  ["Excel", "In Microsoft Excel, to fill a cell with a specific color or pattern, do the following", "From the home page, choose Format Cells, then Fill, then Pattern", "from the Format menu, Choose Pattern", "from the Format menu, Choose Font, then choose Pattern.", "All the answers given are incorrect.", "A"],
  ["PowerPoint", "You can embed a MS-Organization Chart in a slide by", "Clicking the object command on the edit menu", "Clicking the object command on the edit menu", "Clicking the insert new slide button the standard toolbar, then double click the organization chart button on the formatting to", "Clicking the MS-Organization Chart button on the standard toolbar", "C"],
  ["Windows", "Which partition type contains the operating system?", "Primary", "Extended", "Logical", "Virtual", "A"],
  ["مكونات الحاسوب", "RAM is--", "Secondary Storage", "Primary Storage", "Auxiliary Storage", "All of them", "B"],
  ["الإيميل", "What protocol retrieves email?", "POP3", "BGP", "ARP", "SSH", "A"],
  ["الإيميل", "What is the difference between the Inbox and the Spam folder?", "Inbox contains unread emails; Spam contains read emails", "Inbox is for all emails; Spam is for unwanted or potentially harmful emails", "Spam contains only deleted emails", "Inbox is for personal emails, and Spam is for work emails", "B"],
  ["Excel", "When a range is selected, how can you activate the previous cell?", "A. Press the Alt key", "B. Press Enter", "C. Press Tab", "D. None of above", "D"],
  ["الإنترنت", "What is the definition of browser?", "A program used to display html files on the Internet", "A program used to create HTML files on the Internet", "A program used to draw HTML files on the Internet", "A program used to protect the computer", "A"],
  ["PowerPoint", "Which of the following statement is false?", "If you choose to select from one of the pre-made slide layouts, you can change the positioning", "If you choose to select from the pre-made slide layouts, you cannot delete the objects in the layout", "Blank Slide is at the top of the 'Content Layouts' area in the Slide Layout panel", "All of above are false statements", "D"],
  ["Word", "What is the function of Ctrl+ G in MS Word?", "Open Paragraph Dialog box activating Goto Tab", "Open mail box", "Open, Find, and Replace Dialog box with activating Goto Tab", "Open Page Setup Dialog box activating Goto Tab", "C"],
  ["Excel", "The number of rows in an Excel 2016 worksheet is", "1000000", "16232", "1048576", "16384", "C"],
  ["مكونات الحاسوب", "Which CPU register holds the address of the next instruction?", "Data Register", "Instruction Register", "Program Counter", "Accumulator", "C"],
  ["Excel", "The small black square in the lower right corner of an active cell or range represents..", "Handle Copy", "Handle Appended", "Fill Handle", "Border", "C"],
  ["Word", "To insert specific text on each page, click the button", "All the answers given are incorrect.", "Header and footer from the Page Layout menu.", "Header and footer from the View menu.", "Header and footer from the Insert menu.", "D"],
  ["Excel", "How to merge three cells in a Microsoft Excel 2019 workbook and make them one cell?", "We select the three cells first, then from the View menu we choose Instruct Merge", "We select the three cells first, then from the main page menu, we choose Instruct Merge and Center.", "We double click (two clicks) with the left mouse button on the three cells that we want to", "We select the three cells first, then from the Page Layout menu we choose Instruct Merge.", "B"],
  ["الإنترنت", "What is a video call?", "Live video communication", "Stored video", "Offline message", "Audio recording", "A"],
  ["PowerPoint", "Which command brings you to first slide in your presentation?", "Next slide button", "Page up", "Ctrl + home", "Ctrl + end", "C"],
  ["Windows", "Left click in a suitable place in the desktop can be used to delete a file, folder or shortcut.", "True", "False", "All the provided answers are correct", "All the provided answers are incorrect", "B"],
  ["PowerPoint", "To insert a text box, click the button ...", "Text box from a group of cells", "Text box from a group of text", "Text box from a group of illustrations", "All the answers given are incorrect", "B"],
  ["Word", "... works with the standard Copy and Paste commands.", "View tab", "Paragraph dialog box", "Office Clipboard", "All of these", "C"],
  ["Word", "How can you change the orientation of a page in Word 2016 from portrait to landscape?", "Go to File Page Setup", "Go to Layout tab and choose Orientation", "Press Ctrl + Shift + L", "Go to Home Orientation", "B"],
  ["Excel", "How to change the width of column (B) to width (30) in a Microsoft Excel 2019 workbook?", "We select the column first, then from the Width menu we choose Instruct to change the column width.", "We select the column first, then from the home page menu we choose the Format instruction, then click on the Column Width...", "We double click inside any cell in column (B) with the left mouse button...", "We select the column first, then from the checklist we choose Instruct to change the column width.", "B"],
  ["Windows", "Before you can perform any action on a file or folder, what must you do?", "A. Select the file or folder.", "B. Log into the computer again.", "C. Start File Explorer twice.", "D. Create a shortcut for the file or folder.", "A"],
  ["Excel", "To delete a new row between column A and column B, press the button ...", "All the answers given are incorrect", "Delete ... Delete columns from the page group", "Delete ... Delete columns from the group Insert", "Delete ... Delete columns from the group Cells", "D"],
  ["Excel", "While Finding and Replacing some data in Excel, which of the following statement is valid?", "A. You can Find and Replace within the sheet or workbook", "B. Excel does not have option to match case for find", "C. Both are valid", "D. None are valid", "A"],
  ["الإنترنت", "What does HTTP stand for?", "Hyper Text Transfer Protocol", "Hyper Transfer Text Process", "High Transfer Text Platform", "HyperText Tag Protocol", "A"],
  ["Excel", "In Microsoft Excel, pie chart is used for", "To show the trend in values across two dimensions in a continuous curve", "To compare values across categories", "To show the trend of values over time or across categories", "To show the contribution of each value relative to the total", "D"],
  ["PowerPoint", "Animation schemes can be applied to ... in the presentation", "All slides", "Select slides", "Current slide", "All of the above", "D"],
  ["الإنترنت", "The primary purpose of protecting data online is:", "Privacy protection of personal data", "Establishing standards for how programs should be written", "Protecting companies from industrial espionage", "hacker preventing", "A"],
  ["Windows", "File of type bmp is:", "Text file", "Picture file", "Sound file", "All the provided answers are correct", "B"],
  ["الإيميل", "What does the Reply All function do?", "Replies to only the sender", "Replies to everyone on the email chain", "Sends a new email", "Forward the email", "B"],
  ["مكونات الحاسوب", "Which device converts digital signals to printed output?", "Monitor", "Printer", "Scanner", "Speaker", "B"],
  ["الإنترنت", "What is HTML?", "HyperText Markup Language", "HighText Machine Language", "HyperText Management Language", "HyperTransfer Markup Language", "A"],
  ["Windows", "The taskbar is located", "on the start menu", "at the bottom of the screen", "on the quick launch toolbar", "at the top of the screen", "B"],
  ["الإنترنت", "What does LAN stand for?", "Local Area Network", "Large Application Network", "Long Access Network", "Low Application Network", "A"],
  ["Windows", "Which folder contains installed applications by default?", "Documents", "Windows", "Program Files", "Temp", "C"],
  ["الإنترنت", "What is an online account?", "Hard disk", "Personal internet profile", "Network router", "Programming language", "B"],
  ["Word", "Microsoft Word is ... software", "Application", "Compiler", "System", "Programming", "A"],
  ["مكونات الحاسوب", "Which storage device uses magnetic technology?", "SSD", "RAM", "Hard Disk Drive", "ROM", "C"],
  ["الإيميل", "What is the purpose of the archive feature in email?", "To store old emails without deleting them", "To send emails to multiple recipients", "To delete junk emails", "To save a draft of an email", "A"],
    ["الإيميل", "Which of the following items you must have to send an email:", "Powerful computer", "The same Internet service as the recipient", "The recipient has the same data packets", "Recipient's email address", "D"],
  ["PowerPoint", "If you have a PowerPoint show you created and want to send using email to another teacher you can add the show to your email message as a (an):", "Inclusion", "Attachment", "Reply", "Forward", "B"],
    ["الإنترنت", "What does URL represent?", "Screen resolution", "File size", "Is a facility that houses a large number of computer servers", "address bar at the top of your web browser.", "D"],
  ["الإنترنت", "Small text file created by a website that is stored in the user's computer temporarily for that session is called ........", "bug", "cache", "cookie", "malware", "C"],
  ["الإنترنت", "Stored link to a Web page, in order to have a quick and easy access to it later, is called", "WP-Link", "Bookmark", "Field", "Length", "B"],
  ["الإنترنت", "In a web browser, which of the following is used to save frequently visited websites?", "History", "Task Manager", "Favorites", "Save as", "C"],
  ["الإنترنت", "What is Instant Messaging (IM)?", "Messages between two people on the Internet", "Messages between two people without Internet", "Voice messages only", "None of the above", "A"],
  ["الإنترنت", "Website is a collection of", "graphics", "programs", "algorithms", "web pages", "D"],
  ["الإيميل", "Which of the following options is generally used to view and manage emails received", "Inbox", "Sent items", "Compose", "Attachment", "A"],
  ["الإنترنت", "........ command in Web browser that helps to move to the previous page from the current page.", "Back", "Create", "Save", "Forward", "A"],
  ["الإنترنت", "The Internet is", "a large network of networks", "an internal communication system for a business", "a communication system for the Indian government", "All of the above", "A"],
  ["الإنترنت", "What is the definition of browser?", "A) A program used to display html files on the Internet", "B) A program used to create HTML files on the Internet", "C) A program used to draw HTML files on the Internet", "D) A program used to protect the computer", "A"],
  ["الإنترنت", "........ offers real time chat between individuals and groups of people.", "VIRUS", "BLOG", "Instant messenger", "EMAIL", "C"],
  ["الإيميل", "The ......... field of an e-mail indicates the receiver of that e-mail.", "From", "Signature", "Subjects", "To", "D"],
  ["Windows", "Which Windows feature allows users to organize files and folders?", "a) Disk Cleanup", "b) Control Panel", "c) Task Manager", "d) File Explorer", "D"],
  ["Windows", "Which utility in Windows is used to free up disk space?", "a) Task Manager", "b) Control Panel", "c) Disk Cleanup", "d) Device Manager", "C"],
  ["Windows", "small arrow or blinking symbol on desktop is called a___", "A. Mouse", "B. Logo", "C. Palm", "D. Cursor", "D"],
  ["PowerPoint", "Which of the following are actions you can assign to an action button or slide object?", "Run a macro", "Play a sound", "Hyper link", "All of above", "D"],
  ["Excel", "Excel contains", "Image's", "Texts", "Formulas", "All of above", "D"],
  ["الإنترنت", "Data and information are exchanged over the internet through:", "Server", "Information user", "Printer", "Monitor", "A"],
  ["Excel", "In order to edit a chart, you can", "Triple click the chart object", "Click and drag the chart object", "Double click the chart object", "Click the chart object", "C"],
  ["Windows", "The desktop background is also known as:", "wallpaper", "icon", "file", "menu", "A"],
  ["مكونات الحاسوب", "All of the following programs are considered applications except:", "Facebook", "Spreadsheets", "Word processor", "Operating system", "D"],
  ["PowerPoint", "Which of the following is/are true about rulers and guides?", "Rulers and guides can be turned on or off", "Rulers and guides print on the slide", "Rulers and guides help place objects on the slide", "A and C", "D"],
  ["Windows", "The screen background is known :", "Window", "Desktop", "Farmes", "None of the above", "B"],
  ["الإنترنت", "What is the purpose of encryption in information security?", "To make files larger", "To hide the existence of files", "To secure data by making it unreadable", "To speed up internet connections", "C"],
  ["الإنترنت", "What is the best way to recognize a phishing attempt?", "Call the number provided in the email.", "Click on all links in the email.", "Reply to the email with personal information.", "Ignore the suspicious email.", "D"],
  ["الإيميل", "What symbol is used to attach an image or file in email?", "Lock symbol", "Star symbol", "Paperclip symbol", "Pen symbol", "C"],
  ["Word", "Which of the following would move the cursor to the beginning of the current line?", "Home", "End", "CTRL + Home", "CTRL + End", "A"],
  ["PowerPoint", "What effect is added to slides during a slide show in PowerPoint?", "Transition", "Animation", "Text effects", "Background effect", "A"],
  ["Excel", "To insert a new worksheet, click on the button:", "Insert, Insert Sheet", "Home, Insert, Insert Sheet", "Page Layout, Insert, Insert Sheet", "All given answers are incorrect", "B"],
  ["الإيميل", "What does email scheduling mean?", "Marking an email as important", "Sending an email at a later time or date using the scheduling feature", "Moving the email to the drafts folder", "Forwarding the email to yourself", "B"],
  ["Excel", "What tool would you use to merge some cells and center the content in the merged cell?", "From the Format Cells dialog box, select Center alignment", "From the Format Cells dialog box, click Merge Cells", "From the Format Cells dialog box, choose Merge and Center", "Click the Merge & Center tool on the Formatting toolbar", "D"],
  ["Word", "What is the document Outline View?", "View with title hierarchy on different levels", "Full Screen Preview", "View with margins and header", "Preview with margins", "A"],
  ["الإنترنت", "Internet is the name given to:", "All saved documents connected to each other", "Computer systems connected to each other to form the global network", "Websites", "Cables and communications used by satellites to connect computers together", "B"],
  ["الإنترنت", "What is the application used to browse websites?", "Sender", "Messenger", "Browser", "Search engine", "C"],
  ["الإنترنت", "When working on a cloud-based document such as Google Docs, what feature allows multiple people to edit the document in real time?", "Real-time collaboration", "Share via link", "Commenting mode", "Offline mode", "A"],
  ["الإنترنت", "What is latency?", "Packet size", "Delay in data transfer", "CPU load", "File format", "B"],
  ["الإنترنت", "What is CAPTCHA used for?", "Verify human user", "Encrypt data", "Increase speed", "Compress files", "A"],
  ["الإنترنت", "The primary purpose of protecting data online is:", "Privacy protection of personal data", "Establishing standards for how programs should be written", "Protecting companies from industrial espionage", "Hacker preventing", "A"],
  ["PowerPoint", "Which option in PowerPoint allows to carry slides from one computer to another?", "Save As", "Save and Go", "Pack and Go", "Web and Go", "C"],
  ["PowerPoint", "Block arrows, stars and banners, and callouts are all examples of:", "Different types of children's building blocks", "Auto Shape categories", "Clip art categories located in the Microsoft Clip Gallery", "More technical terms that I don't understand", "B"],
  ["Windows", "to Open Help Window", "F1", "F2", "F3", "F5", "A"],
  ["مكونات الحاسوب", "Which of the following is considered an \"Output Device\"?", "Mouse", "Printer", "Keyboard", "Scanner", "B"],
  ["Word", "Which of the following can be used for quick access to common commands and tools?", "Status bar", "Toolbar", "Menu bar", "Title bar", "B"],
  ["PowerPoint", "The difference between Slide Design and Auto Content Wizard is", "Auto Content Wizard is just the wizard version of Slide Design", "Slide Design does not provide sample content but Auto Content Wizard provides sample content too!", "Slide Design asks your choice in steps but Auto Content Wizard does not let you make choices", "Both are same", "B"],
  ["مكونات الحاسوب", "Which uses magnetic disk to store data?", "Hard disk", "USB flash drive", "SSD", "غير متوفر", "A"],
  ["الإيميل", "Sending an item to the Trash means .....", "Draft email", "Spam email", "Delete email", "Send email", "C"],
  ["مكونات الحاسوب", "Which of the following describes a hardware component in computer system ?", "Windows 10", "Microsoft", "Keyboard", "System software", "C"],
  ["PowerPoint", "What happens if you select the first and second slides, then click on the \"New Slide\" button in the toolbar ?", "A new slide is inserted as the first slide in the presentation", "A new slide is inserted as the second slide in the presentation.", "new slide is inserted as the third slide in the presentation.", "None of the above.", "C"],
  ["Excel", "To insert a new column between Column A and Column B, click on the button", "Insert columns from the \"Editing\" group", "group.Insert columns from the \"Insert\" group", "Insert columns from the \"Cells\" group.", "All given answers are incorrect.", "C"],
  ["Windows", "Which of the following is designed to control the operations of a computer?", "Application Software", "System Software", "Utility Software", "User", "B"],
  ["PowerPoint", "What is the term used when you press and hold the left mouse key and move the mouse around the slide?", "Dragging", "Moving", "Highlighting", "Selecting", "A"],
  ["Excel", "How do we change the text size of a cell?", "From the Insert menu, in the Font group, click the Font Size text box", "From the main menu, group Styles, we press the Font Size button", "From the Home menu, Font group, we type the font size in the Change Size text box", "From the Page Layout menu, Tools group, we click on Font Size", "C"],
  ["مكونات الحاسوب", "Blu-ray Disc (BD) is:", "An optical disc", "ROM", "A magnetic disc", "All the provided answers are correct", "A"],
  ["PowerPoint", "Which of the following allow you to select more than one slide in a presentation", "Alt + Click each slide", "Shift + drag each slide", "Shift + Click each slide", "Ctrl + Click each slide", "D"],
  ["Word", "Each line represents how many letters in WordStar?", "20", "35", "65", "75", "C"],
  ["الإنترنت", "The fastest internet network is:", "Wi-Fi", "Fiber optic", "Satellites", "4G", "B"],
  ["الإنترنت", "What does URL represent?", "Screen resolution", "File size", "Address web", "Email", "C"],
  ["Excel", "In Microsoft Excel, to insert a new row, do the following:", "From the Data menu, choose Insert Row.", "From the Edit menu, choose Insert Row.", "From the Insert menu, choose Rows", "From the Format menu, choose Row, and then choose...", "C"],
  ["Excel", "To sort column A in ascending order, press the button:", "Sort and filter from group editing", "Sort and label from font collection", "Sort and label from editting", "All answers given are incorrect", "A"],
  ["Excel", "In Microsoft Excel, which function should you use if you want to count cells that contain numbers only within a specific range?", "COUNTBLANK", "COUNT", "COUNTIF", "COUNTA", "B"],
  ["Windows", "What do the letters (C, D, E) represent in the Windows operating system?", "Folder", "Drives", "Shortcut", "All of the above", "B"]

]
    
import json
import logging
import time
from datetime import datetime, timezone
import requests

logger = logging.getLogger(__name__)


questions = []
for i, q in enumerate(data, start=1):
        question_text = str(q[1]).strip()
        explanation = question_explanations.get(question_text, "") if 'question_explanations' in globals() else ""
        
        questions.append({
            "id": f"Q{i}",
            "category": str(q[0]),
            "question": question_text,
            "options": [str(x) for x in q[2:6]],
            "answer": str(q[6]).strip().upper(),
            "explanation": explanation
        })
        
    return questions


def show_delete_page(chat_id, page):
    questions = get_questions()

    if not questions:
        return send(chat_id, "لا توجد أسئلة صالحة للحذف.")

    page_size = 20
    total_pages = -(-len(questions) // page_size)  # Ceiling division

    try:
        page = max(0, min(int(page), total_pages - 1))
    except ValueError:
        page = 0

    start = page * page_size
    page_questions = questions[start:start + page_size]

    keyboard = [
        [{"text": f"{q['category']} — {q['question'][:45]}", "callback_data": f"deleteq:{q['id']}"}]
        for q in page_questions
    ]

    navigation = []
    if page > 0:
        navigation.append({"text": "⬅️ السابق", "callback_data": f"deletepage:{page - 1}"})

    if page < total_pages - 1:
        navigation.append({"text": "التالي ➡️", "callback_data": f"deletepage:{page + 1}"})

    if navigation:
        keyboard.append(navigation)

    return send(
        chat_id,
        f"🗑️ اختر السؤال الذي تريد حذفه.\nالصفحة: {page + 1} من {total_pages}\nعدد الأسئلة: {len(questions)}",
        {"inline_keyboard": keyboard}
    )


def test_question_explanation():
    question = "From which tab can WordArt be inserted in Microsoft Word?"
    explanation = question_explanations.get(question, "NOT FOUND") if 'question_explanations' in globals() else "NOT FOUND"
    logger.info(f"الشرح: {explanation}")


def check_expired_exams():
    now = int(time.time() * 1000)

    # فحص جميع الحالات المخزنة لقيم STATE_
    for key, value in list(PROPERTIES.items()):
        if not key.startswith("STATE_"):
            continue

        try:
            state = json.loads(value)
        except Exception:
            continue

        if (
            state.get("mode") == "exam"
            and state.get("deadline")
            and now >= state.get("deadline")
        ):
            chat_id = key[len("STATE_"):]
            finish_exam(chat_id, state, timed_out=True)


def show_edit_page(chat_id, page):
    questions = get_questions()

    if not questions:
        return send(chat_id, "لا توجد أسئلة صالحة للتعديل.")

    page_size = 20
    total_pages = -(-len(questions) // page_size)

    try:
        page = max(0, min(int(page), total_pages - 1))
    except ValueError:
        page = 0

    start = page * page_size
    page_questions = questions[start:start + page_size]

    keyboard = [
        [{"text": f"{q['category']} — {q['question'][:45]}", "callback_data": f"editq:{q['id']}"}]
        for q in page_questions
    ]

    navigation = []
    if page > 0:
        navigation.append({"text": "⬅️ السابق", "callback_data": f"editpage:{page - 1}"})

    if page < total_pages - 1:
        navigation.append({"text": "التالي ➡️", "callback_data": f"editpage:{page + 1}"})

    if navigation:
        keyboard.append(navigation)

    return send(
        chat_id,
        f"✏️ اختر السؤال الذي تريد تعديله.\nالصفحة: {page + 1} من {total_pages}\nعدد الأسئلة: {len(questions)}",
        {"inline_keyboard": keyboard}
    )


def save_question_edit(question_id, field, value):
    allowed_fields = ["category", "question", "options", "answer", "explanation"]

    if field not in allowed_fields:
        raise ValueError("حقل التعديل غير صالح.")

    saved = json.loads(PROPERTIES.get("QUESTION_EDITS", "{}"))

    if question_id not in saved:
        saved[question_id] = {}

    if field == "options":
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError("يجب إدخال أربعة خيارات.")
        saved[question_id]["options"] = [str(v) for v in value]
    else:
        saved[question_id][field] = str(value).strip()

    PROPERTIES["QUESTION_EDITS"] = json.dumps(saved)


def save_exam_result(result):
    results_list = json.loads(PROPERTIES.get("EXAM_RESULTS", "[]"))
    
    entry = {
        "completedAt": result.get("completedAt") or datetime.now(timezone.utc).isoformat(),
        "userId": str(result.get("userId", "")),
        "name": result.get("name", "غير معروف"),
        "username": f"@{result['username']}" if result.get("username") else "",
        "category": result.get("category", "غير محددة"),
        "score": int(result.get("score", 0)),
        "correct": int(result.get("correct", 0)),
        "total": int(result.get("total", 0)),
        "duration": result.get("duration", "")
    }
    
    results_list.append(entry)
    PROPERTIES["EXAM_RESULTS"] = json.dumps(results_list)


def show_exam_report(chat_id):
    if not is_admin(chat_id):
        return send(chat_id, "هذا التقرير مخصص للمشرفين فقط.")

    results_list = json.loads(PROPERTIES.get("EXAM_RESULTS", "[]"))

    if not results_list:
        return send(chat_id, "📊 لا توجد نتائج امتحانات محفوظة حتى الآن.")

    # ترتيب المحاولات حسب الأحدث
    results_list.sort(key=lambda x: x.get("completedAt", ""), reverse=True)

    unique_students = set(row["userId"] for row in results_list)

    message = (
        f"📊 تقرير الامتحانات\n"
        f"👥 عدد الطلاب: {len(unique_students)}\n"
        f"📝 عدد المحاولات: {len(results_list)}\n\n"
    )

    for i, r in enumerate(results_list, start=1):
        message += (
            "━━━━━━━━━━━━━━\n"
            f"🔢 المحاولة: {i}\n"
            f"👤 الطالب: {r.get('name') or 'غير معروف'}\n"
            f"🔗 اليوزرنيم: {r.get('username') or 'لا يوجد'}\n"
            f"🆔 ID: {r.get('userId')}\n"
            f"📚 المادة: {r.get('category')}\n"
            f"📊 الدرجة: {r.get('score')} من 100\n"
            f"✅ الصحيحة: {r.get('correct')} من {r.get('total')}\n"
            f"⏱️ المدة: {r.get('duration')}\n"
            f"📅 التاريخ: {r.get('completedAt')[:16].replace('T', ' ')}\n\n"
        )

    chunk_size = 2500
    for i in range(0, len(message), chunk_size):
        chunk = message[i:i + chunk_size]
        try:
            send(chat_id, chunk)
        except Exception as err:
            logger.error(f"خطأ إرسال التقرير: {err}")
            return send(
                chat_id,
                "تعذر إرسال جزء من التقرير. تم الاحتفاظ بجميع النتائج."
            )


def get_telegram_student_info(chat_id):
    token = PROPERTIES.get("BOT_TOKEN")

    try:
        url = f"https://api.telegram.org/bot{token}/getChat?chat_id={chat_id}"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get("ok"):
            user = data.get("result", {})
            names = [user.get("first_name"), user.get("last_name")]
            full_name = " ".join(filter(None, names))

            return {
                "username": user.get("username", ""),
                "name": full_name
            }
    except Exception as e:
        logger.error(f"خطأ في جلب معلومات الطالب: {e}")

    return {
        "username": "",
        "name": ""
    }


def test_telegram_token():
    token = PROPERTIES.get("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN غير موجود")

    response = requests.get(f"https://api.telegram.org/bot{token}/getMe")
    logger.info(f"رمز الاستجابة: {response.status_code}")
    logger.info(f"نتيجة تيليغرام: {response.text}")
