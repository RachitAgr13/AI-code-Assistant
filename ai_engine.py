"""
ai_engine.py
Handles all Ollama API calls:
  1. get_suggestions()      - next step + code improvement
  2. convert_english_lines() - NL -> code for detected English lines
  3. detect_english_lines()  - heuristic + quick check
"""

import json
import os
import re
import threading
from typing import Callable, List, Optional, Tuple

import requests


# --------------------------------------------------------------------------- #
# English-line detection helpers
# --------------------------------------------------------------------------- #

_CODE_PATTERNS = re.compile(
    r"""
    (^\s*(def |class |import |from |if |else:|elif |for |while |try:|except|
          return |raise |with |yield |async |await |lambda |pass|break|continue|
          print\(|[a-zA-Z_]\w*\s*=|[a-zA-Z_]\w*\s*\()|  # keywords / assignments / calls
    [=\(\)\[\]{}<>!&|@%^~\\]|                            # operators & punctuation
    ^\s*#|                                               # comments
    ^\s*(\"\"\"|\'\'\')                                  # docstrings
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_SENTENCE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9'\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'\-]*){2,}\s*[.!?]?\s*$"
)


def _looks_like_english_line(raw_line: str) -> bool:
    line = raw_line.strip()
    if not line or len(line) < 6:
        return False
    if _CODE_PATTERNS.search(raw_line):
        return False
    if line.startswith(("#", "\"\"\"", "'''")):
        return False
    if any(ch in line for ch in "{}[]()=<>;|"):
        return False

    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+", line)
    alpha_words = [word for word in words if any(ch.isalpha() for ch in word)]

    if len(words) < 4 or len(alpha_words) < 3:
        return False

    return bool(_SENTENCE_RE.match(line))


def detect_english_lines(code: str) -> List[Tuple[int, str]]:
    """
    Return list of (line_index, stripped_line_text) for lines that look
    like natural-English sentences embedded in the code file.
    """
    results = []
    for i, raw_line in enumerate(code.splitlines()):
        if _looks_like_english_line(raw_line):
            results.append((i, raw_line.strip()))
    return results


# --------------------------------------------------------------------------- #
# AI Engine
# --------------------------------------------------------------------------- #

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


def _clean_ollama_url(url: str) -> str:
    return url.rstrip("/")


def _ollama_advice(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()

    if "failed to establish a new connection" in lowered or "connection refused" in lowered:
        return (
            "Ollama is not reachable on port 11434. Start it first with `ollama serve`, "
            "and make sure nothing else is using that port."
        )

    if "requires more system memory" in lowered:
        return (
            "Ollama could not load the model because this machine does not have enough memory. "
            "Use a smaller model, or pull a lighter one such as qwen2.5-coder:1.5b."
        )

    if "model not found" in lowered or "not found" in lowered:
        return (
            "Ollama cannot find the selected model. Pull it first, or set "
            "NOTEPADAI_OLLAMA_MODEL to a model that is already installed."
        )

    return message


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```[a-z]*\n?", "", text).replace("```", "").strip()


class AIEngine:
    def __init__(self):
        self.ollama_url = _clean_ollama_url(
            os.getenv("NOTEPADAI_OLLAMA_URL", "http://127.0.0.1:11434")
        )
        self.model = os.getenv("NOTEPADAI_OLLAMA_MODEL", "qwen2.5-coder:1.5b")
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

    def generate_english_conversion(
        self,
        code: str,
        line_idx: int,
        line_text: str,
        callback: Callable,
        variant: bool = False,
    ):
        thread = threading.Thread(
            target=self._fetch_single_english_conversion,
            args=(code, line_idx, line_text, callback, variant),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _run_analysis(self, code: str, on_suggestions: Callable, on_english: Callable):
        if not code.strip():
            return

        t1 = threading.Thread(
            target=self._fetch_suggestions, args=(code, on_suggestions), daemon=True
        )
        t2 = threading.Thread(
            target=self._fetch_english_conversions, args=(code, on_english), daemon=True
        )
        t1.start()
        t2.start()

    # ------------------------------------------------------------------ #
    # Suggestions
    # ------------------------------------------------------------------ #

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
                        },
                    ],
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            raw = _strip_code_fences(result["message"]["content"])
            callback(json.loads(raw))
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
                    "next_step": f"Ollama error: {_ollama_advice(exc)}",
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

    # ------------------------------------------------------------------ #
    # English -> Code
    # ------------------------------------------------------------------ #

    def _fetch_english_conversions(self, code: str, callback: Callable):
        english_lines = detect_english_lines(code)
        if not english_lines:
            callback([])
            return

        results = []

        for line_idx, line_text in english_lines:
            results.append(self._build_english_conversion_result(code, line_idx, line_text))

        callback(results)

    def _fetch_single_english_conversion(
        self,
        code: str,
        line_idx: int,
        line_text: str,
        callback: Callable,
        variant: bool = False,
    ):
        callback(self._build_english_conversion_result(code, line_idx, line_text, variant))

    def _build_english_conversion_result(
        self,
        code: str,
        line_idx: int,
        line_text: str,
        variant: bool = False,
    ) -> dict:
        code_lines = code.splitlines()
        if line_idx >= len(code_lines):
            return {
                "line_idx": line_idx,
                "english": line_text,
                "code": "# Error: English line no longer exists in the file. Save again.",
                "raw_code": "",
            }

        original_line = code_lines[line_idx]
        indent = len(original_line) - len(original_line.lstrip())
        indent_str = " " * indent

        try:
            prompt_suffix = ""
            if variant:
                prompt_suffix = (
                    "\nGenerate a fresh alternative implementation that is still correct and idiomatic."
                )

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
                                f"Produce code with {indent} spaces of indentation.{prompt_suffix}"
                            ),
                        },
                    ],
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
            generated = _strip_code_fences(result["message"]["content"])
            indented_code = "\n".join(
                indent_str + line if line.strip() else line
                for line in generated.splitlines()
            )
            return {
                "line_idx": line_idx,
                "english": line_text,
                "code": indented_code,
                "raw_code": generated,
            }
        except requests.RequestException as exc:
            return {
                "line_idx": line_idx,
                "english": line_text,
                "code": f"# Error: Ollama unavailable - {_ollama_advice(exc)}",
                "raw_code": "",
            }
        except Exception as exc:
            return {
                "line_idx": line_idx,
                "english": line_text,
                "code": f"# Error: {exc}",
                "raw_code": "",
            }
