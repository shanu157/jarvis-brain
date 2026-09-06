# Jarvis — private assistant with chunked memory

## Setup (Termux)

```
pkg install python
pip install --upgrade pip
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
python jarvis.py
```

No extra pip packages needed — uses only Python's standard library
(`sqlite3`, `urllib`) so there's nothing heavy to install.

## How the memory works

- Every message you send (and every reply) is saved instantly to a small
  SQLite file at `~/.jarvis/memory.db`.
- Only your **last ~20 turns** ("active chunk") are sent to the model each
  time — like the chunk you're currently standing in.
- If your message sounds like it's referencing the past ("remember...",
  "what did I say about...", "earlier..."), Jarvis runs a keyword search
  (FTS5) across *all* history and pulls in just the matching lines — like
  walking toward an unloaded chunk and having it pop back in. It never
  resends your entire history to the API.
- Check `memory.db_size_kb()` any time — for normal daily use this stays
  in the KB-to-low-MB range for a very long time.

## Keeping storage flat long-term (optional, for later)

`memory.py` has `save_digest(day, summary)` and `prune_day(day)`. Once a
day is old, you can ask the model to summarize it in a sentence or two,
save that as the digest, then prune the raw messages — collapsing a whole
day's chatter down to one line, permanently.

## Next steps you might want

- Swap `urllib` calls for the `anthropic` pip package (nicer API, streaming).
- Add voice input/output (Termux has `termux-speech-to-text` / `termux-tts-speak`).
- Add a background "recall trigger" tuner if the keyword list misses things.
- Wrap it as a PWA later, same as your other Termux-built apps.
