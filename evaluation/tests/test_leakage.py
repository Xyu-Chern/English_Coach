"""Prompt-task leakage: no phrase a task quotes may appear in the coach's prompts.

Every quoted English phrase ('...' or "...") and every quoted Korean phrase (the idioms and
meanings a learner asks about) in the question or intended text of the task file
(evaluation/data/tasks.jsonl) must be absent from the prompt modules in
translation_agent_demo/agents/prompts/*.py, case-insensitively. English phrases are matched as
whole words (so 'ping' does not hit "mapping"); Korean phrases as substrings (Korean attaches
endings to the phrase). A prompt that names a task's phrase could teach the answer to one
system, so a hit fails the test.
"""

import json
import re
import unittest
from pathlib import Path

from evaluation.tasks import TASKS

PROMPTS = Path(__file__).resolve().parents[2] / "translation_agent_demo" / "agents" / "prompts"
# A quoted span: ASCII single quotes not touching a letter (so "don't" is no quote), double quotes, curly quotes.
QUOTED = re.compile(r"(?<![A-Za-z])'([^'\n]{1,80}?)'(?![A-Za-z])|\"([^\"\n]{1,80})\"|‘([^’\n]{1,80})’|“([^”\n]{1,80})”")
HANGUL = re.compile(r"[가-힣]")
# Generic words only; never a phrase a task asks about.
ALLOWED = {"i", "it", "you", "we", "a", "the"}
FIELDS = ("question", "intended")


def quoted_phrases(path: Path) -> dict[str, set[str]]:
    """phrase -> ids of the tasks that quote it (question or intended)."""
    found: dict[str, set[str]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        for field in FIELDS:
            for match in QUOTED.finditer(task.get(field) or ""):
                phrase = next(g for g in match.groups() if g).strip(" .,?!…")
                if phrase and any(c.isalpha() for c in phrase):
                    found.setdefault(phrase, set()).add(task["id"])
    return found


def leaks(phrase: str, text: str) -> bool:
    if phrase.lower() in ALLOWED:
        return False
    if HANGUL.search(phrase):
        return phrase.lower() in text.lower()
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE) is not None


def prompt_text() -> str:
    return "\n".join(path.read_text() for path in sorted(PROMPTS.glob("*.py")))


class PromptLeakageTests(unittest.TestCase):
    def test_no_quoted_task_phrase_appears_in_the_prompts(self):
        text = prompt_text()
        hits = {p: sorted(ids) for p, ids in quoted_phrases(TASKS).items() if leaks(p, text)}
        self.assertEqual(hits, {}, f"task phrases found in {PROMPTS.name}/")

    def test_the_check_is_not_vacuous(self):
        """The prompt modules exist and hold text; the task file yields English and Korean phrases."""
        names = {path.name for path in PROMPTS.glob("*.py")}
        self.assertTrue({"agent.py", "baseline.py", "shared.py"} <= names, sorted(names))
        self.assertGreater(len(prompt_text()), 2000)
        phrases = quoted_phrases(TASKS)
        self.assertGreater(len(phrases), 30)
        self.assertTrue(any(HANGUL.search(p) for p in phrases))
        self.assertTrue({"산 넘어 산", "엎질러진 물", "말이 쉽지"} <= set(phrases))
        self.assertTrue({"keep up", "push back", "circle back", "on the same page"} <= set(phrases))

    def test_matching_rules(self):
        self.assertTrue(leaks("sync up", "Say SYNC UP when you mean meet."))
        self.assertFalse(leaks("ping", "a mapping of slots"))
        self.assertTrue(leaks("산 넘어 산", "예: 산 넘어 산이다"))
        self.assertFalse(leaks("I", "I am a prompt"))


if __name__ == "__main__":
    unittest.main()
