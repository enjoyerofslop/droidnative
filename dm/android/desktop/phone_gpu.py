# A phone's GPU, for the desktop app's Phones page and its choice of Vulkan driver (droidplay's plans/turnip-driver-windows-app.md, "Device matching"): which drivers
# can run on a phone is a matter of its GPU's maker and, for Turnip, its Adreno generation. The one adb call that reads each phone's properties
# (nxnative_android.py refresh_devices) takes PROPS too: Vulkan's hardware module, the SoC and the API level. The renderer from SurfaceFlinger's GLES line (GLES_CMD,
# about a second) is the one name every maker fills in, so it is asked once per phone and kept (QSettings gpu/<serial>); Copy report uses the same.
import re

PROPS = 'getprop ro.hardware.vulkan; getprop ro.soc.model; getprop ro.build.version.sdk'
GLES_CMD = 'dumpsys SurfaceFlinger | grep -m1 GLES:'
QUALCOMM_SOC = re.compile(r'(SM|SDM|MSM|QCS|QCM)\d')   # ro.soc.model on Qualcomm's chips (SM8750, SDM845); not Unisoc's SC9863A


def gles_renderer(out):
    """dumpsys SurfaceFlinger's GLES line ("GLES: Qualcomm, Adreno (TM) 830, OpenGL ES 3.2 …") → its renderer ("Adreno (TM) 830"), or ''"""
    m = re.search(r'GLES:\s*[^,]*,\s*([^,]+)', out or '')
    return m[1].strip() if m else ''


def classify(renderer='', vulkan='', soc=''):
    """→ {'kind': 'adreno' | 'mali' | 'xclipse' | 'powervr' | 'other' | 'unknown', 'adreno': its number or None, 'label': the Phones page's text}. The renderer
    decides; without one, Vulkan's hardware module (ro.hardware.vulkan: adreno, mali, samsung for Xclipse) or a Qualcomm SoC says which, with no number"""
    r = (renderer or '').strip()
    m = re.search(r'Adreno\D{0,8}?(\d{3})', r)
    if m: return {'kind': 'adreno', 'adreno': int(m[1]), 'label': f'Adreno {m[1]}'}
    for kind, pat in (('mali', r'Mali[-\w]*'), ('xclipse', r'Xclipse\s*\d*'), ('powervr', r'PowerVR[\w\s-]*?(?=,|$)')):
        m = re.search(pat, r, re.I)
        if m: return {'kind': kind, 'adreno': None, 'label': m[0].strip()}
    v = (vulkan or '').strip().lower()
    if v == 'adreno' or QUALCOMM_SOC.match((soc or '').strip()): return {'kind': 'adreno', 'adreno': None, 'label': 'Adreno'}
    if v == 'mali': return {'kind': 'mali', 'adreno': None, 'label': 'Mali'}
    if v == 'samsung': return {'kind': 'xclipse', 'adreno': None, 'label': 'Xclipse'}   # Samsung's own Vulkan driver: a Galaxy Z Flip 7's SurfaceFlinger prints no GLES line
    if r: return {'kind': 'other', 'adreno': None, 'label': r}
    return {'kind': 'unknown', 'adreno': None, 'label': ''}
