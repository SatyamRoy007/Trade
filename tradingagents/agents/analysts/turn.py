"""One turn of a tool-using analyst, and its last turn once its tool rounds are spent."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

WRAP_UP = (
    "You have used every tool round this report allows. Write your final report "
    "now from the tool results above, and say which data you could not retrieve."
)


def take_turn(prompt, llm, tools, messages):
    """The analyst's reply and its report, which stays empty while it calls tools.

    Told to wrap up, it answers without tools: a model offered tools may call one
    whatever it is told. Its earlier calls and their results reach it as text,
    since a provider may refuse a history holding tool calls when none are bound.
    """
    if messages and isinstance(messages[-1], HumanMessage) and messages[-1].content == WRAP_UP:
        # The prompt lists the tools it offers; a model told of tools it cannot
        # call may still try, and some providers then answer with nothing.
        prompt = prompt.partial(tool_names="none; your tool rounds are spent")
        result = (prompt | llm).invoke(_as_text(messages))
        return result, _with_evidence_ledger(result.content, messages)
    result = (prompt | llm.bind_tools(tools)).invoke(messages)
    return result, "" if result.tool_calls else _with_evidence_ledger(result.content, messages)


def _with_evidence_ledger(report: str, messages) -> str:
    """Append provenance the model cannot fabricate to a completed report.

    An analyst's prose is produced by an LLM, but the list of tools that
    actually returned data is observed by the graph.  Carrying that list into
    the report makes missing evidence visible to readers and lets the final
    safety gate reject a directional decision that has no retrieved inputs.
    """
    sources: dict[str, str] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and message.name:
            content = str(message.content).lower()
            bad_result = any(marker in content for marker in (
                "no_data_available", "unavailable", "fetch failed", "error:",
            ))
            # A retry cannot turn a prior failure into a source of evidence, but
            # a later successful response from the same tool can replace it.
            if message.name not in sources or not bad_result:
                sources[message.name] = "unavailable" if bad_result else "retrieved"
    if not sources:
        ledger = "No tool result was retrieved; this report must not support a trade decision."
    else:
        ledger = "\n".join(f"- `{source}`: {status}" for source, status in sources.items())
    return f"{report.rstrip()}\n\n## Evidence Ledger\n{ledger}"


def _as_text(messages):
    """The history with its tool calls and tool results written out as plain messages."""
    written = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            said = message.content if isinstance(message.content, str) else ""
            calls = "; ".join(f"{c['name']}({json.dumps(c['args'], default=str)})" for c in message.tool_calls)
            written.append(AIMessage(content=f"{said}\n[Called {calls}]".strip()))
        elif isinstance(message, ToolMessage):
            written.append(HumanMessage(content=f"[{message.name or 'Tool'} returned]\n{message.content}"))
        else:
            written.append(message)
    return written
