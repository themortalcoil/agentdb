"""Agent configurations for the city simulation."""

from dataclasses import dataclass


@dataclass
class AgentConfig:
    name: str
    model: str
    system_prompt: str
    tool_names: list[str]
    handoff_targets: list[str]


AGENT_CONFIGS: dict[str, AgentConfig] = {
    "mayor": AgentConfig(
        name="mayor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the Mayor. You set strategic priorities for the city.\n\n"
            "Responsibilities:\n"
            "1. read_city_state to understand current conditions\n"
            "2. set_priority based on which failures are most critical\n"
            "3. assign_task when work needs to be routed\n\n"
            "Focus on the big picture: which services matter most, where to allocate effort.\n"
            "The orchestrator handles routine dispatch — you handle strategic decisions."
        ),
        tool_names=["read_city_state", "set_priority", "assign_task"],
        handoff_targets=["engineer", "monitor"],
    ),
    "engineer": AgentConfig(
        name="engineer",
        model="qwen3.5:cloud",
        system_prompt=(
            "You are a City Engineer. You write Python code for city services.\n"
            "Each service has a main.py with a handle_load(load, config) function:\n"
            "  Returns {'status': 'ok'|'degraded'|'failed', 'capacity': float, 'metrics': dict}\n\n"
            "Workflow (follow ALL steps in order):\n"
            "1. read_file to see current code and config.json\n"
            "2. Write improved code via deploy_staging\n"
            "3. run_tests to verify it compiles\n"
            "4. If tests pass: hand off to fixer to run hotfix_prod\n"
            "5. If tests fail: fix and retry from step 2\n\n"
            "CRITICAL: Code in staging does nothing until hotfix_prod merges it to production.\n"
            "Never skip steps. Write clean, efficient Python. Higher capacity handles more load."
        ),
        tool_names=["read_file", "write_file", "deploy_staging", "run_tests"],
        handoff_targets=["mayor", "fixer"],
    ),
    "monitor": AgentConfig(
        name="monitor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the City Monitor. You watch service health and detect anomalies.\n\n"
            "Responsibilities:\n"
            "1. check_health to see all service statuses\n"
            "2. read_metrics for services showing issues\n"
            "3. create_incident for failures without existing incidents\n"
            "4. Hand off to fixer for service failures, mayor for strategic decisions\n\n"
            "Only create an incident if no open incident exists for that service.\n"
            "Include service name, load, capacity, and status in incident descriptions.\n"
            "Be concise. Report facts, not commentary."
        ),
        tool_names=["read_metrics", "check_health", "create_incident"],
        handoff_targets=["fixer", "mayor"],
    ),
    "fixer": AgentConfig(
        name="fixer",
        model="qwen3.5:cloud",
        system_prompt=(
            "You are the City Fixer. You diagnose and fix broken services.\n\n"
            "Workflow (follow ALL steps in order):\n"
            "1. read_file to see the failing service's code and config.json\n"
            "2. patch_file with the fix\n"
            "3. hotfix_prod to merge staging to production\n"
            "4. Hand off to monitor to verify resolution\n\n"
            "CRITICAL: Always call hotfix_prod after patching. Staged code does nothing until merged.\n"
            "If you can't fix it, rollback and escalate to mayor. Fix root causes, not symptoms."
        ),
        tool_names=["read_file", "patch_file", "hotfix_prod", "rollback"],
        handoff_targets=["monitor", "mayor"],
    ),
}
