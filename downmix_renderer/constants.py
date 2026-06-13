SAMPLE_RATE = 48000
BLOCK_SIZE = 256
MAX_INPUT_CHANNELS = 16
OUTPUT_CHANNELS = 2
DEFAULT_PREAMP_DB = -14
APP_DISPLAY_NAME = "Downmix Renderer"
DEFAULT_CHANNEL_CONFIG = "windows_7_1"
TRIM_MIN_DB = -24.0
TRIM_MAX_DB = 0.0

from .layouts import SHARUR_9_1_6_LAYOUT, WINDOWS_7_1_LAYOUT

SHARUR_916_CHANNEL_NAMES = SHARUR_9_1_6_LAYOUT.names
WINDOWS_71_CHANNEL_NAMES = WINDOWS_7_1_LAYOUT.names

CHANNEL_LAYOUTS = {
    "windows_7_1": {
        "label": WINDOWS_7_1_LAYOUT.label,
        "names": WINDOWS_71_CHANNEL_NAMES,
        "indices": tuple(range(8)),
    },
    "sharur_9_1_6": {
        "label": SHARUR_9_1_6_LAYOUT.label,
        "names": SHARUR_916_CHANNEL_NAMES,
        "indices": tuple(range(16)),
    },
}

# Backwards-compatible name for older imports.
CHANNEL_NAMES = SHARUR_916_CHANNEL_NAMES
