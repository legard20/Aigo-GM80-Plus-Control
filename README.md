# Aigo GM80 Plus Control Center

A lightweight, modern, glassmorphism desktop control center for the **Aigo GM80 Plus** tri-mode wireless gaming mouse (**YJX-CHIP** / **PAW3311** sensor), built with Python & PySide6. It communicates directly with the mouse's onboard flash memory over the real USB HID vendor protocol (`MI_02`, `UsagePage=0xFF01`, `Usage=0x0010`) as a fast, bloat-free replacement for the official `GamingMouse` driver.

---

## English

### Features
- **Real Onboard Memory Control (No Mock Settings):**
  - Direct 65-byte USB HID communication (`0x55` command header → `0xAA` hardware ACK + mandatory readback verification via `CMD 0x0E` & `CMD 0x08`).
  - Only genuine **PAW3311 / GM80 Plus** features are exposed.
- **6 DPI Stages & LED Indicator Colors:**
  - Clean stage selector for the 6 hardware DPI stages (`800 / 1200 / 1600 / 3200 / 5000 / 12000 DPI`) and bottom LED indicator color pickers with instant live switching (`CMD 0x22`) and one-click catalog defaults restore.
- **Polling Rate & Debounce Time:**
  - Switch between `125 Hz`, `250 Hz`, `500 Hz` (recommended default), and `1000 Hz` (`CMD 0x23` + `CMD 0x0F` flash commit), adjust Debounce Time (`1` – `20 ms`, default `8 ms`), plus a one-click **Restore Default (500Hz / 8ms)** button.
  - > **Hardware Note (2.4G Dongle vs. USB Wired):** Dynamic polling rate switching (`125 / 250 / 500 / 1000 Hz`) takes effect on the **2.4G Wireless Dongle** (`VID_A8A5 & PID_2255`). In **USB Wired** mode (`VID_A8A4 & PID_2255`), the mouse firmware operates at a fixed `1000 Hz` polling rate while charging.
- **Full 6-Button Remapping & Factory Reset:**
  - Remap all 6 buttons to mouse actions, DPI controls, media keys, or keyboard shortcuts saved directly to onboard flash (`CMD 0x09` Bank 0 & Bank 1), plus a working **Restore Default Buttons** button.
- **Live Tri-Mode Battery & Connection Monitoring:**
  - **2.4G Wireless:** Direct hardware battery telemetry (`CMD 0x30`) returning live percentage & estimated voltage (`3.3V` – `4.2V`) with zero cached values, plus low-battery (<20%) tray alerts.
  - **USB Wired & Hot-Plug Switching:** Automatic hot-plug transition and direct charging status.
  - **Bluetooth LE:** Automatic detection (`125 Hz`) and live Windows PnP battery reading when exposed by Windows.
- **Unified Settings Window (`⚙️ Settings`) persisted in `settings.json`:**
  - **App Language:** Instant switching between **Arabic (RTL, default)** and **English (LTR)**.
  - **Run in Background (`Minimize to Tray on X`):** `OFF` by default so closing the window (`X`) exits the app & tray icon cleanly; enable in Settings if you want closing `X` to minimize to tray.
  - **Auto Battery Check Interval:** Customize live polling interval (**Manual Only**, **Every 10s**, **Every 30s**, **1 / 3 / 5 / 10 min**).
  - **Wallpapers Folder:** Displays the exact path to the local `wallpapers/` folder with a **📂 Open Wallpapers Folder** button to easily drop in your own `.jpg` / `.png` / `.webp` images and reload immediately.
  - **Custom App & Shortcut Icon:** Pick any `.ico / .png / .jpg` image and automatically convert it via Pillow to `custom_icon.ico`, updating the window, tray icon, and Desktop shortcut icon immediately (with one-click restore to `app_icon.ico`).
- **Single-Instance Protection & Glassmorphism UI:**
  - Windows Named Mutex ensures only one instance runs; opening the app while minimized to tray automatically brings the existing window back to the foreground.
  - Smooth 20-frame crossfade wallpaper engine + **Eye Button (`👁️`)** to view unobstructed wallpapers.

### Requirements & Running from Source
1. Install Python 3.10+ on Windows.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. *(Optional)* Place `.jpg` / `.png` / `.webp` wallpaper images inside the `wallpapers/` folder.
4. Run the application:
   ```bash
   python GM80Plus_Control_Center.py
   ```
   > Tip: Close the official `GamingMouse` (`DeviceDriver.exe`) app if running to avoid USB HID port conflicts.

### Building a Standalone Windows `.exe`
```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --icon=app_icon.ico --add-data="app_icon.ico;." --name "GM80Plus_Control_Center" GM80Plus_Control_Center.py
```

---

## العربية

مركز تحكم احترافي وخفيف بواجهة زجاجية حديثة (Glassmorphism) لماوس **Aigo GM80 Plus** ثلاثي الأوضاع (**شريحة YJX-CHIP** / **سنسور PAW3311**)، مبني بلغة Python ومكتبة PySide6، ويتصل مباشرة بذاكرة الماوس الداخلية (Onboard Memory) عبر بروتوكول USB HID الحقيقي (`MI_02`, `UsagePage=0xFF01`, `Usage=0x0010`) كبديل أسرع وأنظف للبرنامج الأصلي.

### المميزات
- **اتصال هاردوير حقيقي 100% بالذاكرة الداخلية للماوس:**
  - إرسال حزم 65 بايت الأصلية والتحقق الإجباري من استجابة الهاردوير (`ACK 0xAA`) وإعادة قراءة الذاكرة (`CMD 0x0E` و `CMD 0x08`).
- **درجات الـ DPI الستة وتخصيص الألوان:**
  - كروت منظمة للدرجات الستة (`800 / 1200 / 1600 / 3200 / 5000 / 12000 DPI`) مع اختيار الدرجة النشطة وتخصيص لون اللمبة السفلية لكل درجة مع تبديل فوري (`CMD 0x22`) وزر استعادة إعدادات الكتالوج.
- **معدل الاستجابة (Polling Rate) وزمن منع الدبل كليك (Debounce Time):**
  - تغيير فوري بين `125 Hz / 250 Hz / 500 Hz / 1000 Hz` (`CMD 0x23` + `CMD 0x0F`) وضبط `Debounce Time` (`1` – `20 ms`) مع زر **«استعادة الإعداد الافتراضي (500Hz / 8ms)»**.
  - > **ملاحظة تقنية هامة (الدونجل 2.4G مقابل السلك USB):** تغيير معدل الاستجابة الفعلي بين `125 / 250 / 500 / 1000 Hz` يعمل بكفاءة على **دونجل الوايرلس 2.4G** (`VID_A8A5 & PID_2255`)، بينما يعمل الماوس في **وضع السلك USB** (`VID_A8A4 & PID_2255`) بتردد ثابت `1000 Hz` مع الشحن المباشر.
- **برمجة الأزرار الستة واستعادة أزرار المصنع:**
  - تخصيص جميع الأزرار الستة وحفظها في ذاكرة الماوس (`CMD 0x09` Bank 0 & Bank 1) مع زر فعلي لـ **«استعادة الأزرار الافتراضية»**.
- **قراءة البطارية الحقيقية 100% ودعم الأوضاع الثلاثة:**
  - **وايرلس 2.4G:** استعلام مباشر وفوري من الهاردوير (`CMD 0x30`) بدون أي قيم مخزنة أو وهمية، مع عرض الوقت الفعلي والنسبة والفولت وتنبيه انخفاض الشحن (<20%).
  - **سلك USB والبلوتوث (Bluetooth LE):** انتقال تلقائي فوري عند توصيل أو فصل الكابل، واكتشاف وضع البلوتوث (`125 Hz`) وقراءة بطاريته من ويندوز.
- **نافذة الإعدادات المتكاملة (`⚙️ الإعدادات`) مع حفظ في `settings.json`:**
  - **لغة التطبيق:** التبديل الفوري بين **العربية (الافتراضية)** و **English**.
  - **التشغيل في الخلفية:** مغلق افتراضياً ليتم إغلاق البرنامج وأيقونة الـ Tray نهائياً عند الضغط على `X`، مع إمكانية تفعيله لينزل بجانب الساعة.
  - **مؤقت فحص صحة البطارية التلقائي:** يدوي فقط، أو **كل 10 ثواني / 30 ثانية / 1 / 3 / 5 / 10 دقائق**.
  - **مجلد الخلفيات:** عرض مسار مجلد `wallpapers/` مع زر **«📂 فتح مجلد الخلفيات»** لإضافة صورك مباشرة وإعادة تحميلها.
  - **تغيير أيقونة البرنامج:** اختيار أي صورة (`.ico / .png / .jpg`) وتحويلها تلقائياً عبر Pillow إلى `custom_icon.ico` وتحديث أيقونة النافذة وشريط المهام واختصار سطح المهام فوراً (مع زر استعادة الأيقونة الافتراضية `app_icon.ico`).
- **حماية النسخة الواحدة (Single Instance) والواجهة الزجاجية:**
  - منع تكرار فتح البرنامج وإظهار النافذة المفتوحة تلقائياً عند إعادة التشغيل، مع خلفيات متبدلة بنعومة (`Smooth Crossfade`) وزر العين `👁️`.

### التشغيل من الكود المصدري
1. ثبّت Python 3.10 أو أحدث على ويندوز.
2. ثبّت المكتبات المطلوبة:
   ```bash
   pip install -r requirements.txt
   ```
3. *(اختياري)* أضف صور الخلفيات داخل مجلد `wallpapers/`.
4. شغّل التطبيق:
   ```bash
   python GM80Plus_Control_Center.py
   ```

### بناء ملف تشغيل مستقل (`EXE`)
```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --icon=app_icon.ico --add-data="app_icon.ico;." --name "GM80Plus_Control_Center" GM80Plus_Control_Center.py
```
