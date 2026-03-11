from agentdb.agents.definitions import AGENT_CONFIGS, AgentConfig


def test_agent_configs_defined():
    assert "mayor" in AGENT_CONFIGS
    assert "engineer" in AGENT_CONFIGS
    assert "monitor" in AGENT_CONFIGS
    assert "fixer" in AGENT_CONFIGS


def test_agent_config_structure():
    for name, config in AGENT_CONFIGS.items():
        assert isinstance(config, AgentConfig)
        assert config.name == name
        assert config.model in ("glm-5:cloud", "minimax-m2.5:cloud", "qwen3.5:cloud")
        assert len(config.system_prompt) > 0
        assert len(config.tool_names) > 0
        assert len(config.handoff_targets) > 0


def test_mayor_uses_glm5():
    assert AGENT_CONFIGS["mayor"].model == "glm-5:cloud"


def test_engineer_uses_coding_model():
    assert AGENT_CONFIGS["engineer"].model in ("minimax-m2.5:cloud", "qwen3.5:cloud")


def test_build_swarm_returns_graph(db):
    """build_swarm should return a compiled LangGraph."""
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.db.overlay import OverlayFS
    from agentdb.agents.swarm import build_swarm

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    graph = build_swarm(fs=fs, kv=kv, overlay=overlay)
    assert graph is not None
