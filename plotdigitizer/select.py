"""Stage 2: selection of figures with quantitative data.

STUB for the LLM step P2. Without an LLM the user picks figures by number
(``--figures``) from the output of ``plotdigitizer list-figures``.
"""


def select_figures(figures: list[dict], numbers: list[str] | None = None) -> list[dict]:
    if not numbers:
        return figures
    want = {str(n) for n in numbers}
    return [f for f in figures if str(f["number"]) in want]
