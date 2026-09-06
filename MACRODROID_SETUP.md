# Auto-send WhatsApp via MacroDroid (no root, no ADB, no WiFi required)

## Why this exists
Android blocks any app — Jarvis included — from tapping WhatsApp's Send
button on its own (anti-spam protection). MacroDroid can do it because it
uses Android's Accessibility permission, which is allowed to interact with
the screen on your behalf. This runs entirely on-device — no network needed.

## One-time setup

### 1. Let Termux write to shared storage
```
termux-setup-storage
```
Approve the permission popup. This creates `~/storage/shared` linking to
your phone's normal storage, which is where the trigger file will live.

### 2. Install MacroDroid
From the Play Store, install **MacroDroid - Device Automation**. The free
tier (up to 5 macros) is enough for this.

Open it once and grant it the **Accessibility** permission when prompted
(Settings → Accessibility → MacroDroid → enable). This is required for it
to perform taps.

### 3. Create the macro
In MacroDroid, tap **+ Add Macro**, then set it up like this:

**Trigger:**
- Category: **Connectivity / Files**
- Choose **"File/Folder Modified"** (or "File Modified" depending on version)
- Path: `/storage/emulated/0/jarvis_triggers/send_whatsapp.trigger`
  (this is the same as `~/storage/shared/jarvis_triggers/...` in Termux —
  just the real Android path)

**Actions** (in this order):
1. **Wait** — 2 seconds (gives WhatsApp time to fully open and render)
2. **UI Interaction → Click Button/Text** (or "Find and Click" depending on
   version) — set the text to match: `Send` (WhatsApp's send button is
   usually an icon with no visible text — if MacroDroid can't find it by
   text, use **"Tap Coordinates"** instead and record the Send button's
   screen position once by tapping "Record" and manually tapping Send
   during setup)
3. **Wait** — 1 second
4. **Launch Application** — choose your browser (Chrome), which will bring
   Jarvis back to the foreground

**Constraints:** none needed — leave default.

Save the macro and make sure it's **enabled** (toggle on).

### 4. Enable auto-send in Jarvis
In Termux:
```
export JARVIS_AUTO_SEND=1
```
Add that line to `~/.bashrc` to make it permanent, same as your API keys.

## Testing it
```
whatsapp 9876543210 saying testing auto send
```
Jarvis should say "auto-sending via MacroDroid..." and — if the macro is
set up correctly — WhatsApp should open, the message should send itself,
and your browser should reappear a couple seconds later.

## If the tap misses
Screen coordinates for the Send button can shift depending on keyboard
state or WhatsApp UI updates. If MacroDroid's tap misses:
- Re-record the tap position (Send button location can vary slightly)
- Try the "Click Button/Text" method instead of fixed coordinates if you
  haven't already — it's more reliable across screen states
