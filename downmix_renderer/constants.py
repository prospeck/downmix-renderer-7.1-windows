SAMPLE_RATE = 48000
BLOCK_SIZE = 256
MAX_INPUT_CHANNELS = 16
OUTPUT_CHANNELS = 2
DEFAULT_PREAMP_DB = -14
APP_DISPLAY_NAME = "Taran's 7.1 Renderer Suite"
DEFAULT_CHANNEL_CONFIG = "windows_7_1"

SHARUR_916_CHANNEL_NAMES = (
    "FL",
    "FR",
    "FC",
    "LFE",
    "BL",
    "BR",
    "BLC",
    "BRC",
    "SL",
    "SR",
    "TFL",
    "TFR",
    "TSL",
    "TSR",
    "TBL",
    "TBR",
)

WINDOWS_71_CHANNEL_NAMES = (
    "FL",
    "FR",
    "FC",
    "LFE",
    "BL",
    "BR",
    "SL",
    "SR",
)

CHANNEL_LAYOUTS = {
    "windows_7_1": {
        "label": "7.1",
        "names": WINDOWS_71_CHANNEL_NAMES,
        "indices": tuple(range(8)),
    },
    "sharur_9_1_6": {
        "label": "9.1.6 Monitor",
        "names": SHARUR_916_CHANNEL_NAMES,
        "indices": tuple(range(16)),
    },
}

# Backwards-compatible name for older imports.
CHANNEL_NAMES = SHARUR_916_CHANNEL_NAMES
