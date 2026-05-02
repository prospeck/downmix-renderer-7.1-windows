Taran's 7.1 Downmix Renderer Suite

A premium Windows WASAPI downmix renderer designed for seamless routing of multichannel audio (via VB-CABLE capture endpoints) into high-quality stereo DAC output. Built for precision, performance, and a polished, professional experience.

Highlights
OLED-black interface with a fully custom window frame
WASAPI-only device handling for clean, low-latency routing
High-precision downmix processing with consistent channel mapping
Native Windows volume-key integration via CoreAudio
Independent Suite Volume and Preamp controls
Advanced preset system (create, update, delete, instant switching)
Intelligent preset switching based on active output device
Optional auto-start on system boot

Real-time 7.1 channel visualization:

FL FR FC LFE BL BR SL SR
Prerequisites & Initial Setup

Before using the renderer, complete the following setup:

1. Install VB-Audio Virtual Cable

Install VB-CABLE for Windows — this acts as the virtual audio bridge.

2. Configure VB-CABLE Format
Go to Sound Settings → Playback Devices
Open CABLE Output (VB-Audio Virtual Cable)
Navigate to Properties → Advanced
Set:
16 channel, 24-bit, 48000 Hz
3. Enable 7.1 Speaker Configuration
Open Control Panel → Sound
Right-click CABLE Output
Select Configure Speakers
Set to 7.1 Surround
4. Configure Renderer Devices

Inside the app (WASAPI category only):

Input:
CABLE Output (VB-Audio Virtual Cable) (48 kHz)
Output:
Your DAC / speakers / Bluetooth device
5. Start Playback
Click Start
Play audio from your source
⚠️ Important Notes
Only use WASAPI devices inside the app
Ensure VB-CABLE is configured correctly before launch
Incorrect setup may result in:
Missing channels
No audio
Incorrect downmix
Quick Start
Run from source:
cd "C:\Users\taran\Documents\Playground\downmix-renderer-research"
python renderer_app.py
Run packaged app:
cd "C:\Users\taran\Documents\Playground\downmix-renderer-research"
.\dist\TaransDownmixRendererSuite.exe
Presets System

The app starts with zero presets by design.

Usage:
Select WASAPI input/output
Adjust Preamp, Suite Volume, channel config
Enter name → click New
Switch instantly via preset buttons
Use Update to overwrite
Use Delete to remove
Each preset stores:
Device identities
Preamp
Suite Volume
Channel layout
Output matching behavior

All saves are atomic (no partial or corrupted states).

Smart Device Switching
Automatically detects active Windows output device
Matches and applies corresponding preset
Seamless switching during runtime

Manual selection always overrides auto behavior.

Auto Start

Enable Auto Start Renderer on System Boot:

Launches with Windows
Restores last state
Starts processing automatically

No admin rights required.

Channel Layouts
Default 7.1:
FL FR FC LFE BL BR SL SR
Extended Diagnostic Mode:

16-channel monitoring view for advanced routing analysis.

Route Probe (Diagnostics)
Scan devices:
python -m downmix_renderer.route_probe --duration 0 --output route_probe_inventory.json
Monitor live activity:
python -m downmix_renderer.route_probe --duration 20 --output route_probe_apple_music.json
Results:
channels_above_8_detected → full multichannel path
eight_or_fewer_channels → system limitation
no_signal → routing issue
Development
Run tests:
python -m unittest discover -s tests
Build executable:
python scripts\make_icon.py
pyinstaller --noconfirm renderer_app.spec
Summary

If configured correctly:

Windows (7.1 output)
        ↓
VB-CABLE
        ↓
Renderer (downmix)
        ↓
DAC / Speakers
