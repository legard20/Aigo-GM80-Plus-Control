# Aigo GM80 Plus Control Center (v2)

A lightweight, modern, bilingual (**Arabic RTL / English LTR**) desktop control center for the **Aigo GM80 Plus** tri-mode wireless gaming mouse (**YJX-CHIP** / **PAW3311** sensor), built with Python & PySide6. It communicates directly with the mouse's onboard flash memory over the real USB HID vendor protocol (`MI_02`, `UsagePage=0xFF01`, `Usage=0x0010`) as a fast, clean replacement for the official `GamingMouse` driver.

---

## English

### Features
- **Real Onboard Memory Control (No Mock Settings):**
  - Direct 65-byte USB HID communication (`0x55` command header → `0xAA` hardware ACK + mandatory readback verification via `CMD 0x0E` & `CMD 0x08`).
  - Only genuine **PAW3311 / Aigo GM80 Plus** features are exposed.
- **6 DPI Stages & Independent Hardware LED Colors:**
  - Clean stage selector for the 6 hardware DPI stages (`800 / 1200 / 1600 / 3200 / 5000 / 12000 DPI`) and independent bottom LED indicator color pickers with instant live switching (`CMD 0x22`) and one-click catalog defaults restore.
- **Polling Rate & Debounce Time:**
  - Switch between `125 Hz`, `250 Hz`, `500 Hz` (recommended default), and `1000 Hz` (`CMD 0x23` + `CMD 0x0F` flash commit), adjust Debounce Time (`1` – `20 ms`, default `8 ms`), plus a one-click **Restore Default (500 Hz / 8 ms)** button.
  - > **Hardware Note (2.4G Dongle vs. USB Wired):** Dynamic polling rate switching (`125 / 250 / 500 / 1000 Hz`) takes effect on the **2.4G Wireless Dongle** (`VID_A8A5 & PID_2255`). In **USB Wired** mode (`VID_A8A4 & PID_2255`), the mouse firmware operates at a fixed `1000 Hz` polling rate while charging.
- **7-Button Remapping + Interactive Animated Aigo GM80 Plus Preview:**
  - Exposes all **7 genuine firmware-remappable inputs** (`Left-Click`, `Right-Click`, `Middle-Click`, `Forward`, `Backward`, `Scroll Up`, `Scroll Down`) matching the official `DeviceDriver.exe` `CMD 0x09` Bank 0/1 layout (preserving the non-remappable hardware slot 5 safely) with **Left-Click Lock** protection and verified official action codes (mouse actions, real `DPI +/-/Loop`, `Report Rate +/-/Loop`, multimedia, Windows shortcuts, and `Disabled`).
  - **Live Interactive Mouse Silhouette:** Custom vector Aigo GM80 Plus diagram with live active DPI LED color that animates in real time when you click mouse buttons or scroll the wheel.
- **Automatic Game Profiles:**
  - Lightweight Win32 foreground monitor (`GetForegroundWindow` + `QueryFullProcessImageNameW`, zero redundant HID traffic) that switches DPI Stage & Polling Rate on the mouse (`CMD 0x0F` + `CMD 0x22` + `CMD 0x23` + `CMD 0x0E` readback) with Windows Toast notifications.
  - Add games by picking an `.exe` or capturing a running window in 1 click, with automatic high-res `128×128` icon extraction (`game_icons/`), custom artwork, pause/resume toggles, and configurable exit return delay (`0` – `300 s`).
- **Live Tri-Mode Battery Telemetry & 5 Animated Battery Styles:**
  - **2.4G Wireless:** 100% live hardware battery polling (`CMD 0x30`, zero cached values) + USB-C charging detection + Bluetooth LE Windows PnP battery reading.
  - Choose from **5 animated battery indicator styles** (`Classic`, `Pill`, `Ring`, `Vertical`, `Segmented`) with interactive preview, semantic green/amber/red fill, charging pulse, `< 15%` low-battery blink, and optional matching System Tray icon.
- **Modern Settings Dialog & Smooth 60fps Wallpaper Engine:**
  - **Themes & Accents:** Dark, Light, or System theme + custom accent color + bundled `IBM Plex Sans Arabic` UI font.
  - **Smart Fill & Focus Point:** Automatically preserves portrait/square/small images over a blurred, darkened backdrop (never stretches or crops faces) with `Top / Center / Bottom` focus control.
  - **60fps Background-Rendered Wallpapers:** Off-UI PIL rendering with LRU `QPixmap` cache, smooth crossfade transitions, debounced resize, cached GIF/WebP playback (auto-paused when hidden/minimized), and an Animation on/off toggle.
  - **Custom App & Shortcut Icon**, **Single-Instance Protection**, and collapsible **Developer Log** (`gm80_app.log`).

### Requirements & Running from Source
1. Install Python 3.10+ on Windows.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. *(Optional)* Add `.jpg` / `.png` / `.webp` / `.gif` wallpaper images inside the `wallpapers/` folder (or via **Settings → Wallpaper → Add Images**).
4. Run the application:
   ```bash
   python GM80Plus_Control_Center.py
   ```
   > Tip: Close the official `GamingMouse` (`DeviceDriver.exe`) app if running to avoid USB HID port conflicts.

### Building a Standalone Windows `.exe` (`--onedir`)
Run the included build script (uses the size-optimized `GM80Plus_Control_Center.spec`):
```bat
build_exe.bat
```
Or manually:
```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean GM80Plus_Control_Center.spec
```
Writable user data (`settings.json`, `wallpapers/`, `game_icons/`, `gm80_app.log`) is stored next to the executable when writable, or automatically in `%APPDATA%\GM80PlusControl` when installed in a read-only directory.

---

## العربية

مركز تحكم عصري وخفيف ثنائي اللغة (**العربية RTL / الإنجليزية LTR**) لماوس **Aigo GM80 Plus** ثلاثي الأوضاع (**شريحة YJX-CHIP** / **سنسور PAW3311**)، مبني بلغة Python ومكتبة PySide6، ويتصل مباشرة بذاكرة الماوس الداخلية (Onboard Memory) عبر بروتوكول USB HID الحقيقي (`MI_02`, `UsagePage=0xFF01`, `Usage=0x0010`) كبديل أسرع وأنظف للبرنامج الأصلي.

### المميزات
- **اتصال هاردوير حقيقي 100% بالذاكرة الداخلية للماوس:**
  - إرسال حزم 65 بايت الأصلية والتحقق الإجباري من استجابة الهاردوير (`ACK 0xAA`) وإعادة قراءة الذاكرة (`CMD 0x0E` و `CMD 0x08`).
- **درجات الـ DPI الستة وألوان اللمبة السفلية المستقلة:**
  - اختيار الدرجة النشطة (`800 / 1200 / 1600 / 3200 / 5000 / 12000 DPI`) وتخصيص لون اللمبة السفلية لكل درجة بشكل مستقل عن لون الواجهة مع تبديل فوري (`CMD 0x22`) وزر استعادة إعدادات الكتالوج.
- **معدل الاستجابة (Polling Rate) وزمن منع الدبل كليك (Debounce Time):**
  - تغيير فوري بين `125 / 250 / 500 / 1000 Hz` (`CMD 0x23` + `CMD 0x0F`) وضبط `Debounce Time` (`1` – `20 ms`) مع زر **«استعادة الإعداد الافتراضي (500Hz / 8ms)»**.
  - > **ملاحظة تقنية هامة (الدونجل 2.4G مقابل السلك USB):** تغيير معدل الاستجابة الفعلي يعمل على **دونجل الوايرلس 2.4G** (`VID_A8A5 & PID_2255`)، بينما يعمل الماوس في **وضع السلك USB** (`VID_A8A4 & PID_2255`) بتردد ثابت `1000 Hz` مع الشحن المباشر.
- **تخصيص الأزرار السبعة الحقيقية + معاينة تفاعلية متحركة للماوس:**
  - يدعم جميع الـ **7 مدخلات الفعلية** في الفيرموير (`الزر الأيسر`، `الزر الأيمن`، `زر البكرة`، `الجانبي الأمامي`، `الجانبي الخلفي`، `تمرير البكرة لأعلى`، `تمرير البكرة لأسفل`) مع **قفل الزر الأيسر** للحماية، وأوامر رسمية حقيقية 100% فقط (`CMD 0x09` Bank 0 & Bank 1).
  - **مجسم تفاعلي لماوس Aigo GM80 Plus:** يتفاعل بحركة وإضاءة فورية عند الضغط على أي زر أو تحريك البكرة، ويعرض لون لمبة الـ DPI النشطة حالياً.
- **أوضاع الألعاب التلقائية (Game Profiles):**
  - اكتشاف تلقائي وخفيف للعبة المفتوحة وتطبيق درجة الـ DPI ومعدل الاستجابة المخصصين لها مباشرة على الماوس مع استخراج أيقونات عالية الدقة (`game_icons/`) ومهلة عودة قابلة للتخصيص (`0` – `300` ثانية).
- **قراءة البطارية الحقيقية 100% + 5 أنماط متحركة لمؤشر البطارية:**
  - استعلام مباشر وفوري من الهاردوير (`CMD 0x30`) بدون أي قيم مخزنة أو وهمية، مع دعم السلك والبلوتوث و**5 أشكال متحركة للبطارية** (`كلاسيكي`، `كبسولة`، `دائري`، `رأسي`، `مقسّم`) مع معاينة حية وخيار تطبيق نفس النمط على أيقونة شريط النظام.
- **واجهة عصرية ومحرك خلفيات سلس (60fps):**
  - دعم الوضع الداكن والفاتح وتلقائي النظام + تخصيص لون التمييز + خط `IBM Plex Sans Arabic` مدمج.
  - **ملء ذكي (`Smart Fill`) ونقطة التركيز (`أعلى / وسط / أسفل`):** يحافظ على الصور الطولية والمربعة بدون قص أو مط فوق خلفية مموّهة أنيقة، مع انتقالات ناعمة ومعالجة في الخلفية بدون تقطيع ودعم صور `GIF / WebP` المتحركة.

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
شغّل ملف البناء المرفق مباشرة:
```bat
build_exe.bat
```
أو يدوياً عبر PyInstaller:
```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean GM80Plus_Control_Center.spec
```
