Two things still needed before you can use it:

Add to config.py:

pythonOPENROUTER_FREE_MODEL = os.getenv("OPENROUTER_FREE_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

Install the openai package:

bashpip install openai
Then anywhere in the codebase you can route a task to a free model with:
pythonrouter.chat(messages, task_type=TaskType.SIMPLE, force_provider=LLMProvider.OPENROUTER_FREE)