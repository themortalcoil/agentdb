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
            "You are the Mayor of a simulated city. Your job is to:\n"
            "1. Monitor overall city health by reading city state\n"
            "2. Set priorities based on current conditions\n"
            "3. Assign tasks to Engineers when infrastructure needs work\n"
            "4. Escalate to Monitor when you notice service issues\n"
            "5. Make strategic decisions during cascade failures\n\n"
            "You have a limited budget. Prioritize wisely. When multiple\n"
            "services are degraded, consider the dependency graph: fixing\n"
            "upstream services first prevents cascades."
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
            "Workflow:\n"
            "1. Read the current service code and config\n"
            "2. Write improved code to staging using deploy_staging\n"
            "3. Run tests to verify the code compiles\n"
            "4. Hand off to Mayor for review, or to Fixer if tests fail\n\n"
            "Write clean, efficient Python. Higher capacity handles more citizens."
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
            "1. Regularly check health of all services\n"
            "2. Read detailed metrics for services showing issues\n"
            "3. Create incidents when services are degraded or failed\n"
            "4. Hand off to Fixer for service failures\n"
            "5. Escalate to Mayor for strategic decisions\n\n"
            "Be vigilant. Catch problems early. Include detail in incidents."
        ),
        tool_names=["read_metrics", "check_health", "create_incident"],
        handoff_targets=["fixer", "mayor"],
    ),
    "fixer": AgentConfig(
        name="fixer",
        model="qwen3.5:cloud",
        system_prompt=(
            "You are the City Fixer. You diagnose and fix broken services.\n\n"
            "Workflow:\n"
            "1. Read the failing service's code and error details\n"
            "2. Write a fix to staging using patch_file\n"
            "3. If the fix works, apply with hotfix_prod\n"
            "4. If you can't fix it, rollback and escalate to Mayor\n"
            "5. Hand off to Monitor to confirm resolution\n\n"
            "Fix the root cause, not symptoms."
        ),
        tool_names=["read_file", "patch_file", "hotfix_prod", "rollback"],
        handoff_targets=["monitor", "mayor"],
    ),
}
