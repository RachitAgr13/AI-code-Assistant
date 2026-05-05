# ⚡ NotepadAI

A real-time AI coding copilot that works **alongside Windows Notepad** — no heavy IDE required.
Write Python in Notepad, press **Ctrl+S**, and a floating overlay instantly shows:

| Tab | What it does |
|-----|--------------|
| 💡 **Next Step** | 2-3 sentences on what to implement next, with language & complexity badge |
| 🔧 **Improve** | One specific, actionable improvement for your existing code |
| ✨ **English→Code** | Detects plain-English sentences in your `.py` file and generates the matching Python code |

---

## Requirements

- **Python 3.9+**
- **Windows** (Notepad auto-launch; the overlay itself runs on any OS with Tk)
- An **Anthropic API key** in your environment

---

## Installation

```bash
# 1. Clone / download the project folder
cd notepadai

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Anthropic API key
set ANTHROPIC_API_KEY=sk-ant-...      # Windows CMD
$env:ANTHROPIC_API_KEY="sk-ant-..."   # PowerShell
export ANTHROPIC_API_KEY="sk-ant-..." # macOS/Linux
```

---

## Usage

```bash
# Option A – pick a file via dialog
python main.py

# Option B – pass the file directly
python main.py my_script.py
python main.py C:\Users\You\Desktop\project.py
```

Notepad opens automatically with your file.
Every time you press **Ctrl+S**, the overlay updates within ~2 seconds.

---

## English → Code feature

Write a plain English sentence anywhere in your `.py` file (not in a comment or string):

```python
def setup():
    Connect to a SQLite database called users.db
```

After saving, the **English→Code** tab shows the generated code.
Click **✅ Apply to File** to replace the sentence in-place — Notepad will ask you to reload; click **Yes**.

---

## Project structure

```
notepadai/
├── main.py           # Entry point — wires everything together
├── ai_engine.py      # Claude API calls (suggestions + English→Code)
├── file_watcher.py   # File change detection (watchdog or polling fallback)
├── ui_overlay.py     # Floating Tk overlay window
├── requirements.txt
└── README.md
```

---

## How it works

```
Notepad (Ctrl+S)
      │
      ▼
 FileWatcher ──────────────────────────────────────────────┐
      │ content changed                                     │
      ▼                                                     │
 AIEngine.debounced_analyze()  (1.8 s debounce)            │
      │                                                     │
      ├─► _fetch_suggestions()  ──► Claude API ──► JSON    │
      │         ▼                                           │
      │   OverlayUI._update_suggestions()                  │
      │   (Next Step tab + Improve tab updated)             │
      │                                                     │
      └─► _fetch_english_conversions()                      │
                ▼                                           │
          detect_english_lines()  (heuristic regex)        │
                ▼                                           │
          Claude API × N lines                             │
                ▼                                           │
          OverlayUI._update_english()                      │
          (English→Code tab updated)                        │
                │                                           │
                └── Apply button ── FileWatcher.write() ───┘
```

---

## Tips

- **Pin / Unpin** the overlay with the 📌 button so it stops floating on top when you don't need it.
- The overlay is **resizable** — drag the edges to make it taller.
- Works with any text file, not just `.py`; English→Code only generates Python regardless.
- API calls are **debounced** (1.8 s) so rapid saves don't spam the API.

---

## License

MIT — do whatever you want with it.
