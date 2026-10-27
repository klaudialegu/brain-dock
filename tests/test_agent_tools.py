"""The agent tool policy (ADR 0008): no tool sends data out or deletes anything without an
Accepted ADR exception, and names can't hide what a tool does."""

import pytest
from pydantic import BaseModel

from brain_dock.core.agents.tools import AgentTool, Effect, tool_policy_problems


class NoInput(BaseModel):
    pass


def tool(name, effect=Effect.read):
    return AgentTool(name, "A fake tool", NoInput, effect, lambda _: {})


def adr(folder, name, status):
    (folder / name).write_text(f"# A fake ADR\n**Status:** {status}\n**Date:** 2026-10-26\n")
    return name


def test_safe_tools_pass():
    tools = [
        tool("list_saved_jobs"),
        tool("draft_suggestion", Effect.draft),
        tool("mark_interested", Effect.write),
    ]

    assert tool_policy_problems("inbox", tools) == []


@pytest.mark.parametrize("effect", [Effect.outbound, Effect.delete])
def test_forbidden_effects_need_an_exception(effect):
    problems = tool_policy_problems("inbox", [tool("forward_digest", effect)])

    assert problems == [f"inbox.forward_digest: {effect} tools need an ADR exception"]


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(None, False), ("Proposed", False), ("Accepted", True)],
    ids=["missing-adr", "proposed-adr", "accepted-adr"],
)
def test_an_exception_needs_an_accepted_adr(tmp_path, status, allowed):
    name = "0099-fake-exception.md"
    if status is not None:
        adr(tmp_path, name, status)
    exceptions = {("inbox", "forward_digest"): name}

    problems = tool_policy_problems(
        "inbox", [tool("forward_digest", Effect.outbound)], exceptions, tmp_path
    )

    expected = (
        [] if allowed else [f"inbox.forward_digest: exception {name} must be an Accepted ADR"]
    )
    assert problems == expected


@pytest.mark.parametrize(
    ("name", "says"),
    [
        ("send_email", "sends data out"),
        ("fetch_url", "sends data out"),
        ("post_webhook", "sends data out"),
        ("delete_job", "deletes"),
    ],
    ids=["send_email", "fetch_url", "post_webhook", "delete_job"],
)
def test_names_that_hide_their_effect_are_refused(name, says):
    problems = tool_policy_problems("inbox", [tool(name, Effect.read)])

    assert problems == [f"inbox.{name}: the name says it {says}, but effect is read"]


@pytest.mark.parametrize("name", ["sendEmail", "Send_email", "send-email", "_send", "send__email"])
def test_tool_names_must_be_snake_case(name):
    problems = tool_policy_problems("inbox", [tool(name)])

    assert problems == [f"inbox.{name}: tool names must be snake_case"]


def test_tool_names_are_unique_within_a_module():
    problems = tool_policy_problems("inbox", [tool("list_jobs"), tool("list_jobs", Effect.draft)])

    assert problems == ["inbox.list_jobs: declared 2 times"]
