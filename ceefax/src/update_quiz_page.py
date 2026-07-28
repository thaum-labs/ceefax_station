"""
Update page 602 with daily quiz question from API.
"""
import html
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_quiz_question() -> Dict:
    """
    Fetch a random quiz question from Open Trivia Database.
    """
    url = "https://opentdb.com/api.php?amount=1&type=multiple"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, dict) or data.get("response_code") != 0 or not data.get("results"):
        raise ValueError("API returned invalid response code or no results")
    question_data = data["results"][0]
    question = html.unescape(question_data.get("question", ""))
    correct_answer = html.unescape(question_data.get("correct_answer", ""))
    incorrect_answers = [
        html.unescape(answer) for answer in question_data.get("incorrect_answers", [])
    ]
    if not question or not correct_answer or len(incorrect_answers) != 3:
        raise ValueError("API returned an incomplete multiple-choice question")

    all_answers = [correct_answer] + incorrect_answers
    random.shuffle(all_answers)
    answer_map = {chr(65 + index): answer for index, answer in enumerate(all_answers)}
    correct_letter = next(letter for letter, answer in answer_map.items() if answer == correct_answer)
    return {
        "question": question,
        "answers": answer_map,
        "correct": correct_letter,
        "explanation": f"The answer is {correct_letter}) {correct_answer}",
    }


def resolve_quiz_question() -> ProviderResult[Dict]:
    """Resolve and cache a normalized Open Trivia DB question."""
    return resolve_provider(
        "quiz-602",
        [("Open Trivia Database", fetch_quiz_question)],
        is_valid=lambda quiz: isinstance(quiz, dict)
        and bool(quiz.get("question"))
        and isinstance(quiz.get("answers"), dict)
        and len(quiz["answers"]) == 4
        and quiz.get("correct") in quiz["answers"],
    )


def build_quiz_page(result: ProviderResult[Dict] | None = None) -> List[str]:
    """Build daily quiz page."""
    lines: List[str] = []
    lines.append(_pad("DAILY QUIZ"))
    lines.append(_pad(""))
    lines.append(_pad("QUESTION OF THE DAY"))
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)
    result = result or resolve_quiz_question()
    lines.append(_pad(f"Source: {result.source}"))
    stale = " | STALE" if result.stale else ""
    lines.append(_pad(f"As-of: {result.fetched_at}{stale}"))
    lines.append(_pad(""))
    quiz = result.data

    question = quiz.get("question", "")
    words = question.split()
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 <= PAGE_WIDTH:
            current_line = f"{current_line} {word}".strip()
        else:
            if current_line:
                lines.append(_pad(current_line))
            current_line = word
    if current_line:
        lines.append(_pad(current_line))

    lines.append(_pad(""))
    answers = quiz.get("answers", {})
    for letter in sorted(answers.keys()):
        lines.append(_pad(f"{letter}) {answers[letter]}"))

    lines.append(_pad(""))
    lines.append(_pad("ANSWER"))
    lines.append(sep)
    explanation = quiz.get("explanation", "")
    current_line = ""
    for word in explanation.split():
        if len(current_line) + len(word) + 1 <= PAGE_WIDTH:
            current_line = f"{current_line} {word}".strip()
        else:
            if current_line:
                lines.append(_pad(current_line))
            current_line = word
    if current_line:
        lines.append(_pad(current_line))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 602 with daily quiz."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "602.json"
    
    result = resolve_quiz_question()
    content = build_quiz_page(result)
    
    page = {
        "page": "602",
        "title": "Daily Quiz",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with daily quiz")


if __name__ == "__main__":
    main()

