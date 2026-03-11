"""LangGraph Swarm assembly."""

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_handoff_tool, create_swarm

from agentdb.agents.definitions import AGENT_CONFIGS
from agentdb.agents.tools import CityTools
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS


def _make_langchain_tools(city_tools: CityTools, tool_names: list[str]) -> list:
    """Wrap CityTools methods as LangChain tools."""
    tool_map = {
        "read_city_state": city_tools.read_city_state,
        "set_priority": city_tools.set_priority,
        "assign_task": city_tools.assign_task,
        "write_file": city_tools.write_file,
        "read_file": city_tools.read_file,
        "deploy_staging": city_tools.deploy_staging,
        "run_tests": city_tools.run_tests,
        "read_metrics": city_tools.read_metrics,
        "check_health": city_tools.check_health,
        "create_incident": city_tools.create_incident,
        "patch_file": city_tools.patch_file,
        "hotfix_prod": city_tools.hotfix_prod,
        "rollback": city_tools.rollback,
    }
    tools = []
    for name in tool_names:
        fn = tool_map[name]
        tools.append(tool(fn))
    return tools


def build_swarm(fs: VirtualFS, kv: KVStore, overlay: OverlayFS):
    """Build and compile the LangGraph Swarm with all city agents."""
    city_tools = CityTools(fs=fs, kv=kv, overlay=overlay)
    agents = []

    for config in AGENT_CONFIGS.values():
        llm = ChatOllama(model=config.model)
        handoff_tools = [
            create_handoff_tool(agent_name=target)
            for target in config.handoff_targets
        ]
        lc_tools = _make_langchain_tools(city_tools, config.tool_names)

        agent = create_agent(
            llm,
            tools=lc_tools + handoff_tools,
            system_prompt=config.system_prompt,
            name=config.name,
        )
        agents.append(agent)

    workflow = create_swarm(agents, default_active_agent="monitor")
    checkpointer = InMemorySaver()
    return workflow.compile(checkpointer=checkpointer)
