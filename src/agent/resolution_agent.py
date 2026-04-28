"""
resolution_agent.py — Uses an RHOAI-hosted model via the OpenAI-compatible API
to analyse a detected JBoss/OpenShift issue and generate a structured resolution.

The agent uses function-calling so the response always arrives as a structured
JSON object, not free text, making it easy to map fields to the JIRA ticket body.
"""

import json
import logging
from typing import Any, Dict

from openai import OpenAI

from src.config import Config
from src.models import Issue, Resolution

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) and Red Hat JBoss/WildFly/EAP specialist.
You are embedded in an automated monitoring agent that runs inside OpenShift.

When given details of a JBoss issue (crash, OOM, health failure, alert, or log error),
you must respond ONLY by calling the `provide_resolution` function with a thorough, actionable analysis.

Guidelines:
- Root cause analysis: explain the most likely underlying cause(s) concisely.
- Resolution steps: numbered, operator-executable steps. Be specific (actual commands, config paths, JVM flags).
- Prevention tips: configuration or architectural changes to avoid recurrence.
- References: Red Hat docs, WFLY JIRA IDs, KBase articles, StackOverflow — only cite real, well-known sources.
- Confidence: rate high/medium/low based on how much diagnostic information you have.
- Stay focused on JBoss/WildFly/EAP on OpenShift — don't give generic advice.
"""

# ── Tool definition (OpenAI function-calling format) ──────────────────────────
RESOLUTION_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "provide_resolution",
        "description": (
            "Provide a structured root-cause analysis and resolution for the reported JBoss issue. "
            "Always call this function — never respond with plain text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "root_cause_analysis": {
                    "type": "string",
                    "description": (
                        "Concise analysis (3-6 sentences) of the most likely root cause(s), "
                        "referencing specific JBoss/WildFly/EAP behaviour where relevant."
                    ),
                },
                "resolution_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of concrete steps an operator should take to resolve the issue. "
                        "Include commands, file paths, or configuration snippets where appropriate."
                    ),
                },
                "prevention_tips": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Configuration, tuning, or architectural changes to prevent recurrence "
                        "(e.g. resource limits, JVM heap sizing, readiness probes, GC settings)."
                    ),
                },
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Relevant documentation links or knowledge-base article titles "
                        "(Red Hat docs, WFLY project docs, known JIRA issues, etc.)."
                    ),
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": (
                        "Confidence level: high = clear root cause from data provided; "
                        "medium = likely cause but more data would help; "
                        "low = insufficient information, multiple possible causes."
                    ),
                },
            },
            "required": [
                "root_cause_analysis",
                "resolution_steps",
                "prevention_tips",
                "references",
                "confidence",
            ],
        },
    },
}


class ResolutionAgent:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._client = OpenAI(
            base_url=config.rhoai_api_url,
            api_key=config.rhoai_api_key,
        )

    def analyse(self, issue: Issue) -> Resolution:
        """
        Send the issue context to the RHOAI model and return a structured Resolution.
        Falls back to a placeholder Resolution if the API call fails.
        """
        try:
            return self._call_model(issue)
        except Exception as exc:
            logger.error("ResolutionAgent: RHOAI API call failed: %s", exc)
            return Resolution(
                root_cause_analysis=(
                    "Automated analysis unavailable (RHOAI API error). "
                    "Please investigate manually using the issue details above."
                ),
                resolution_steps=["Review pod logs", "Check OpenShift events", "Consult Red Hat documentation"],
                prevention_tips=[],
                references=[],
                confidence="low",
            )

    def _call_model(self, issue: Issue) -> Resolution:
        issue_context = json.dumps(issue.to_context_dict(), indent=2, default=str)

        user_message = (
            f"The following JBoss/WildFly issue has been detected on OpenShift.\n\n"
            f"```json\n{issue_context}\n```\n\n"
            f"Please analyse this issue and call the `provide_resolution` function "
            f"with a thorough, actionable resolution."
        )

        logger.debug("ResolutionAgent: sending issue '%s' to RHOAI model", issue.title)

        response = self._client.chat.completions.create(
            model=self._cfg.rhoai_model_name,
            max_tokens=self._cfg.rhoai_max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            tools=[RESOLUTION_TOOL],
            tool_choice={"type": "function", "function": {"name": "provide_resolution"}},
        )

        # Extract the function call result
        message = response.choices[0].message
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function.name == "provide_resolution":
                    inp = json.loads(tool_call.function.arguments)
                    return Resolution(
                        root_cause_analysis=inp.get("root_cause_analysis", ""),
                        resolution_steps=inp.get("resolution_steps", []),
                        prevention_tips=inp.get("prevention_tips", []),
                        references=inp.get("references", []),
                        confidence=inp.get("confidence", "medium"),
                    )

        raise ValueError("RHOAI model response did not contain a provide_resolution function call")
