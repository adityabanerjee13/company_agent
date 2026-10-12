PROMPT_TEMPLATE = """You are working in a git repository checked out at the current directory.
Resolve the task described below.

- Make the minimal correct change and follow the existing conventions of the codebase.
- Run the code you changed, and the repository's relevant tests if any exist.
- If the task asks for results (metrics, comparisons, outputs), run it and include the actual numbers.
- You have network access. Install the project's dependencies as needed; downloads can be slow, so retry before giving up.
- Do NOT commit, push or open pull requests; that is done for you afterwards.
- Finish with a short plain-text summary of what you changed and why. 
- You have atmost 15 minutes to finish the task.

Task:
{task}
"""


def build_prompt(task):
    return PROMPT_TEMPLATE.format(task=task)
