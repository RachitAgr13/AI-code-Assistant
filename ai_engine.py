"""
ai_engine.py
Handles all Ollama API calls:
  1. get_suggestions()      – next step + code improvement
  2. convert_english_lines()– NL → code for detected English lines
  3. detect_english_lines() – heuristic + quick check
"""

import os
import re
import json
import threading
import requests
from typing import Callable, List, Tuple, Optional


# ─────────────────────────────────────────────────────────────────────────────
# English-line detection helpers
# ─────────────────────────────────────────────────────────────────────────────

_CODE_PATTERNS = re.compile(
    r"""
    (^\s*(def |class |import |from |if |else:|elif |for |while |try:|except|
          return |raise |with |yield |async |await |lambda |pass|break|continue|
          print\(|[a-zA-Z_]\w*\s*=|[a-zA-Z_]\w*\s*\()|  # keywords / assignments / calls
    [=\(\)\[\]{}<>!&|@%^~\\]|                            # operators & punctuation
    ^\s*#|                                                 # comments
    ^\s*(\"\"\"|\'\'\')                                    # docstrings
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_SENTENCE_RE = re.compile(r"^[A-Za-z][a-z]+([ ][A-Za-z][a-z]*){2,}[.!?]?\s*$")


def detect_english_lines(code: str) -> List[Tuple[int, str]]:
    """
    Return list of (line_index, stripped_line_text) for lines that look
    like natural-English sentences embedded in the code file.
    """
    results = []
    for i, raw_line in enumerate(code.splitlines()):
        line = raw_line.strip()
        if not line or len(line) < 6:
            continue
        if _CODE_PATTERNS.search(raw_line):
            continue
        if _SENTENCE_RE.match(line):
            results.append((i, line))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# AI Engine
# ─────────────────────────────────────────────────────────────────────────────

_SUGGEST_SYSTEM = """\
You are a concise senior Python developer acting as an AI copilot inside Notepad.
The user has just saved their code file. Respond ONLY with a JSON object (no markdown fences):
{
  "language": "<detected language or 'python'>",
  "next_step": "<2-3 sentences: what the developer should write/implement next>",
  "improvement": "<1 specific, actionable improvement for the existing code>",
  "complexity": "<'beginner' | 'intermediate' | 'advanced'>"
}
Be direct, specific, and helpful. Do not add preamble or explanation outside the JSON."""

_ENGLISH_SYSTEM = """\
You are a Python code generator. The user wrote a plain-English description inside their code file.
Your job: replace that English line with correct, idiomatic Python code that fits the surrounding codebase.
Return ONLY the Python code (no markdown fences, no explanation). Match the indentation level provided."""


class AIEngine:
    def __init__(self):
        self.ollama_url = "http://localhost:11434"
        self.model = "qwen2.5-coder:7b"
        self._lock = threading.Lock()
        self._debounce_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def debounced_analyze(
        self,
        code: str,
        on_suggestions: Callable,
        on_english: Callable,
        delay: float = 2.0,
    ):
        """
        Wait `delay` seconds after the last file change before calling the API.
        Cancels any in-flight debounce timer on each new call.
        """
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                delay,
                self._run_analysis,
                args=(code, on_suggestions, on_english),
            )
            self._debounce_timer.start()

    def cancel(self):
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _run_analysis(self, code: str, on_suggestions: Callable, on_english: Callable):
        if not code.strip():
            return

        # Run both analyses in parallel threads
        t1 = threading.Thread(
            target=self._fetch_suggestions, args=(code, on_suggestions), daemon=True
        )
        t2 = threading.Thread(
            target=self._fetch_english_conversions, args=(code, on_english), daemon=True
        )
        t1.start()
        t2.start()

    # ── Suggestions ────────────────────────────────────────────────────

    def _fetch_suggestions(self, code: str, callback: Callable):
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": _SUGGEST_SYSTEM,
                        },
                        {
                            "role": "user",
                            "content": f"Code file contents:\n\n{code[-4000:]}",
                        }
                    ],
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            raw = result["message"]["content"].strip()
            # Strip accidental markdown fences
            raw = re.sub(r"```[a-z]*\n?", "", raw).replace("```", "").strip()
            data = json.loads(raw)
            callback(data)
        except json.JSONDecodeError:
            callback(
                {
                    "language": "python",
                    "next_step": "Could not parse AI response. Try saving again.",
                    "improvement": "",
                    "complexity": "unknown",
                }
            )
        except requests.RequestException as exc:
            callback(
                {
                    "language": "python",
                    "next_step": f"Ollama error: Is it running on {self.ollama_url}? {exc}",
                    "improvement": "",
                    "complexity": "unknown",
                }
            )
        except Exception as exc:
            callback(
                {
                    "language": "python",
                    "next_step": f"Error: {exc}",
                    "improvement": "",
                    "complexity": "unknown",
                }
            )

    # ── English → Code ─────────────────────────────────────────────────

    def _fetch_english_conversions(self, code: str, callback: Callable):
        english_lines = detect_english_lines(code)
        if not english_lines:
            callback([])
            return

        results = []
        for line_idx, line_text in english_lines:
            # Detect indentation of the English line in original file
            original_line = code.splitlines()[line_idx]
            indent = len(original_line) - len(original_line.lstrip())
            indent_str = " " * indent

            try:
                response = requests.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": _ENGLISH_SYSTEM,
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Codebase context (surrounding code):\n\n{code[-3000:]}\n\n"
                                    f"English line to convert (indented {indent} spaces): '{line_text}'\n"
                                    f"Produce code with {indent} spaces of indentation."
                                ),
                            }
                        ],
                        "stream": False,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                result = response.json()
                generated = result["message"]["content"].strip()
                generated = re.sub(r"```[a-z]*\n?", "", generated).replace("```", "").strip()
                # Re-apply correct indentation to each generated line
                indented_code = "\n".join(
                    indent_str + l if l.strip() else l
                    for l in generated.splitlines()
                )
                results.append(
                    {
                        "line_idx": line_idx,
                        "english": line_text,
                        "code": indented_code,
                        "raw_code": generated,
                    }
                )
            except requests.RequestException as exc:
                results.append(
                    {
                        "line_idx": line_idx,
                        "english": line_text,
                        "code": f"# Error: Ollama unavailable - {exc}",
                        "raw_code": "",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "line_idx": line_idx,
                        "english": line_text,
                        "code": f"# Error: {exc}",
                        "raw_code": "",
                    }
                )

        callback(results)
