from pathlib import Path
import re

root=Path(__file__).resolve().parent/"android"
app=root/"app"/"src"/"main"
res=app/"res"

# App name
strings=res/"values"/"strings.xml"
if strings.exists():
    s=strings.read_text(encoding="utf-8")
    s=re.sub(r'(<string name="app_name">).*?(</string>)', r'\1Китайский\2', s)
    s=re.sub(r'(<string name="title_activity_main">).*?(</string>)', r'\1Китайский\2', s)
    strings.write_text(s,encoding="utf-8")

# Brand colors
colors=res/"values"/"colors.xml"
base=colors.read_text(encoding="utf-8") if colors.exists() else '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n'
for name,val in [("chinese_red","#A43B32"),("chinese_cream","#F6F0E6"),("chinese_ink","#26211D")]:
    if f'name="{name}"' not in base:
        base=base.replace("</resources>",f'    <color name="{name}">{val}</color>\n</resources>')
colors.parent.mkdir(parents=True,exist_ok=True)
colors.write_text(base,encoding="utf-8")

# Foreground mark: geometric 中, safe as a vector drawable.
drawable=res/"drawable"
drawable.mkdir(parents=True,exist_ok=True)
mark='''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFF8EE"
        android:pathData="M24,25H84V31H24Z M24,77H84V83H24Z M24,25H30V83H24Z M78,25H84V83H78Z M51,15H57V93H51Z M30,51H78V57H30Z"/>
</vector>
'''
(drawable/"chinese_mark.xml").write_text(mark,encoding="utf-8")
splash='''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#A43B32"
        android:pathData="M24,25H84V31H24Z M24,77H84V83H24Z M24,25H30V83H24Z M78,25H84V83H78Z M51,15H57V93H51Z M30,51H78V57H30Z"/>
</vector>
'''
(drawable/"chinese_splash_icon.xml").write_text(splash,encoding="utf-8")

legacy='''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#A43B32" android:pathData="M0,0H108V108H0Z"/>
    <path android:fillColor="#FFF8EE"
        android:pathData="M24,25H84V31H24Z M24,77H84V83H24Z M24,25H30V83H24Z M78,25H84V83H78Z M51,15H57V93H51Z M30,51H78V57H30Z"/>
</vector>
'''
mipmap_any=res/"mipmap-anydpi"
mipmap_any.mkdir(parents=True,exist_ok=True)
(mipmap_any/"ic_launcher.xml").write_text(legacy,encoding="utf-8")
(mipmap_any/"ic_launcher_round.xml").write_text(legacy,encoding="utf-8")

adaptive='''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/chinese_red"/>
    <foreground android:drawable="@drawable/chinese_mark"/>
</adaptive-icon>
'''
mipmap26=res/"mipmap-anydpi-v26"
mipmap26.mkdir(parents=True,exist_ok=True)
(mipmap26/"ic_launcher.xml").write_text(adaptive,encoding="utf-8")
(mipmap26/"ic_launcher_round.xml").write_text(adaptive,encoding="utf-8")

# Android 12+ splash screen.
styles=res/"values"/"styles.xml"
if styles.exists():
    s=styles.read_text(encoding="utf-8")
    launch='''<style name="AppTheme.NoActionBarLaunch" parent="Theme.SplashScreen">
        <item name="windowSplashScreenBackground">@color/chinese_cream</item>
        <item name="windowSplashScreenAnimatedIcon">@drawable/chinese_splash_icon</item>
        <item name="postSplashScreenTheme">@style/AppTheme.NoActionBar</item>
    </style>'''
    if re.search(r'<style name="AppTheme\.NoActionBarLaunch"[^>]*>.*?</style>',s,flags=re.S):
        s=re.sub(r'<style name="AppTheme\.NoActionBarLaunch"[^>]*>.*?</style>',launch,s,flags=re.S)
    else:
        s=s.replace("</resources>",launch+"\n</resources>")
    styles.write_text(s,encoding="utf-8")

# Native Chinese speech plus hardware/system back navigation.
activities=list((app/"java").rglob("MainActivity.java"))
if not activities:
    raise SystemExit("MainActivity.java not found")
main=activities[0]
s=main.read_text(encoding="utf-8")
package=re.search(r'^package\s+([^;]+);',s,flags=re.M)
if not package:
    raise SystemExit("MainActivity package not found")
s=f'''package {package.group(1)};

import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.webkit.JavascriptInterface;
import com.getcapacitor.BridgeActivity;
import java.util.Locale;

public class MainActivity extends BridgeActivity {{
  private TextToSpeech speech;
  private volatile boolean speechReady = false;

  @Override
  public void onCreate(Bundle savedInstanceState) {{
    super.onCreate(savedInstanceState);
    speech = new TextToSpeech(this, status -> {{
      if (status == TextToSpeech.SUCCESS) {{
        int result = speech.setLanguage(Locale.SIMPLIFIED_CHINESE);
        speechReady = result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED;
      }}
    }});
    getBridge().getWebView().addJavascriptInterface(new NativeSpeechBridge(), "NativeSpeech");
  }}

  private final class NativeSpeechBridge {{
    @JavascriptInterface
    public boolean speak(String text, float rate) {{
      if (!speechReady || speech == null || text == null || text.trim().isEmpty()) return false;
      runOnUiThread(() -> {{
        speech.setSpeechRate(Math.max(0.35f, Math.min(rate, 1.25f)));
        speech.speak(text, TextToSpeech.QUEUE_FLUSH, null, "chinese-study");
      }});
      return true;
    }}
  }}

  @Override
  public void onBackPressed() {{
    if (getBridge() != null && getBridge().getWebView() != null && getBridge().getWebView().canGoBack()) {{
      getBridge().getWebView().goBack();
    }} else {{
      super.onBackPressed();
    }}
  }}

  @Override
  protected void onDestroy() {{
    if (speech != null) {{ speech.stop(); speech.shutdown(); }}
    super.onDestroy();
  }}
}}
'''
main.write_text(s,encoding="utf-8")

print("Android branding, native speech, splash and back navigation applied")
