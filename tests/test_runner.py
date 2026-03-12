import pytest
from unittest.mock import AsyncMock, MagicMock
from agentdb.agents.runner import AgentRunner


@pytest.fixture
def mock_broadcaster():
    b = MagicMock()
    b.broadcast = AsyncMock()
    return b


@pytest.fixture
def mock_engine():
    e = MagicMock()
    e.tick = 5
    return e


async def test_runner_no_swarm(mock_broadcaster, mock_engine):
    runner = AgentRunner(
        swarm=None,
        broadcaster=mock_broadcaster,
        engine=mock_engine,
        event_buffer=[],
        agent_names=["mayor", "engineer", "monitor", "fixer"],
    )
    await runner.run_cycle()
    # With no swarm, should broadcast "working" then "idle" for all agents
    assert mock_broadcaster.broadcast.called
    # Check that idle was broadcast for all 4 agents
    idle_calls = [
        c for c in mock_broadcaster.broadcast.call_args_list
        if c[0][0] == "agent_update" and c[0][1].get("status") == "idle"
    ]
    assert len(idle_calls) == 4


async def test_runner_cycle_counter_starts_at_zero(mock_broadcaster, mock_engine):
    runner = AgentRunner(
        swarm=None,
        broadcaster=mock_broadcaster,
        engine=mock_engine,
        event_buffer=[],
        agent_names=["monitor"],
    )
    assert runner._cycle_counter == 0
