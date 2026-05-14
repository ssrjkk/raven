Web search and information retrieval using DuckDuckGo or fallback search engines. Used to answer questions that require up-to-date information beyond the model's training data.

When the user asks a question that requires current or factual information:
1. Automatically invoke the `web_search` tool to find relevant results.
2. Synthesize the top results into a concise answer with citations.
3. If the user asks for detailed information on a specific topic, fetch the full page content using `web_fetch` and summarize it.
4. Always cite sources with the URL.

This skill is automatically triggered by the LLM router when it detects queries about current events, recent data, or specific factual lookup needs.