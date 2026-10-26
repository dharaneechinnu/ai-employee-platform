"""The permission policy engine.

Resolution order, most specific first:

    1. catastrophic blocklist   platform-wide, nobody can override
    2. your own rule for a tool
    3. your own rule for a pack + side effect
    4. platform default for a tool
    5. platform default for a pack + side effect
    6. safe fallback by side effect

Rule 6 is what makes a newly added tool safe before anyone configures
it: a new destructive tool is blocked until someone deliberately
enables it, rather than running automatically because no rule mentions
it yet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import SideEffect, Tool
from app.agent.tools.registry import BLOCKED_ACTIONS, registry
from app.core.errors import ValidationError
from app.db.models.policy import Policy, PolicyDefault, PolicyScope, PolicySetting

# What an action does if nothing is configured for it.
SAFE_FALLBACK: dict[SideEffect, PolicySetting] = {
    SideEffect.READ: PolicySetting.AUTO,
    SideEffect.WRITE: PolicySetting.ASK,
    SideEffect.DESTRUCTIVE: PolicySetting.BLOCKED,
}


@dataclass(frozen=True, slots=True)
class Decision:
    setting: PolicySetting
    reason: str

    @property
    def is_auto(self) -> bool:
        return self.setting is PolicySetting.AUTO

    @property
    def needs_approval(self) -> bool:
        return self.setting is PolicySetting.ASK

    @property
    def is_blocked(self) -> bool:
        return self.setting is PolicySetting.BLOCKED


@dataclass(slots=True)
class PolicyRow:
    scope: PolicyScope
    scope_value: str
    side_effect: str | None
    setting: PolicySetting
    is_default: bool  # False means the person changed it


class PolicyResolver:
    """A snapshot of one person's effective policy.

    Loaded once per run rather than queried per tool call: a run makes
    ten to fifteen calls, and the policy cannot change mid-run in any
    way we would want to honour halfway through.
    """

    def __init__(
        self,
        *,
        own_rules: dict[tuple[PolicyScope, str, str | None], PolicySetting],
        defaults: dict[tuple[PolicyScope, str, str | None], PolicySetting],
    ) -> None:
        self._own = own_rules
        self._defaults = defaults

    def tool(self, tool_name: str) -> type[Tool] | None:
        return registry.get(tool_name)

    def evaluate(self, tool_name: str) -> Decision:
        if tool_name in BLOCKED_ACTIONS:
            return Decision(
                PolicySetting.BLOCKED, f"blocked platform-wide: {BLOCKED_ACTIONS[tool_name]}"
            )

        tool = self.tool(tool_name)
        if tool is None:
            # Unknown tools cannot be gated, so they are refused. The
            # loop reports this to the model, which picks a real one.
            return Decision(PolicySetting.BLOCKED, "unknown tool")

        pack, effect = tool.pack, tool.side_effect.value

        if (s := self._own.get((PolicyScope.TOOL, tool_name, None))) is not None:
            return Decision(s, "set by you for this tool")
        if (s := self._own.get((PolicyScope.PACK, pack, effect))) is not None:
            return Decision(s, f"set by you for {pack} {effect} actions")
        if (s := self._defaults.get((PolicyScope.TOOL, tool_name, None))) is not None:
            return Decision(s, "platform default for this tool")
        if (s := self._defaults.get((PolicyScope.PACK, pack, effect))) is not None:
            return Decision(s, f"platform default for {pack} {effect} actions")

        return Decision(SAFE_FALLBACK[tool.side_effect], f"safe default for {effect} actions")


class PolicyService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def resolver(self) -> PolicyResolver:
        defaults = {
            (d.scope, d.scope_value, d.side_effect): d.setting
            for d in (await self.session.scalars(select(PolicyDefault))).all()
        }
        own_rules = {
            (p.scope, p.scope_value, p.side_effect): p.setting
            for p in (
                await self.session.scalars(select(Policy).where(Policy.owner_id == self.owner_id))
            ).all()
        }
        return PolicyResolver(own_rules=own_rules, defaults=defaults)

    async def effective(self) -> list[PolicyRow]:
        """Every rule in force, marked default or changed, so the UI can
        show which ones this person has touched."""
        defaults = (await self.session.scalars(select(PolicyDefault))).all()
        overrides = {
            (p.scope, p.scope_value, p.side_effect): p
            for p in (
                await self.session.scalars(select(Policy).where(Policy.owner_id == self.owner_id))
            ).all()
        }

        rows: list[PolicyRow] = []
        seen: set[tuple[PolicyScope, str, str | None]] = set()

        for d in defaults:
            key = (d.scope, d.scope_value, d.side_effect)
            seen.add(key)
            override = overrides.get(key)
            rows.append(
                PolicyRow(
                    scope=d.scope,
                    scope_value=d.scope_value,
                    side_effect=d.side_effect,
                    setting=override.setting if override else d.setting,
                    is_default=override is None,
                )
            )

        for key, p in overrides.items():
            if key not in seen:
                rows.append(
                    PolicyRow(
                        scope=p.scope,
                        scope_value=p.scope_value,
                        side_effect=p.side_effect,
                        setting=p.setting,
                        is_default=False,
                    )
                )

        return sorted(rows, key=lambda r: (r.scope_value, r.side_effect or ""))

    async def set_rule(
        self,
        *,
        scope: PolicyScope,
        scope_value: str,
        side_effect: str | None,
        setting: PolicySetting,
        user_id: uuid.UUID,
    ) -> Policy:
        if scope is PolicyScope.TOOL and scope_value in BLOCKED_ACTIONS:
            # The one thing nobody can turn on. Refused in the backend,
            # not merely greyed out on the screen.
            raise ValidationError(
                f"'{scope_value}' is blocked platform-wide and cannot be enabled: "
                f"{BLOCKED_ACTIONS[scope_value]}"
            )

        existing = await self.session.scalar(
            select(Policy).where(
                Policy.owner_id == self.owner_id,
                Policy.scope == scope,
                Policy.scope_value == scope_value,
                Policy.side_effect == side_effect,
            )
        )
        if existing is not None:
            existing.setting = setting
            existing.updated_by = user_id
            return existing

        policy = Policy(
            owner_id=self.owner_id,
            scope=scope,
            scope_value=scope_value,
            side_effect=side_effect,
            setting=setting,
            updated_by=user_id,
        )
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def reset(self) -> None:
        """Drop every override, returning the person to the defaults."""
        for policy in (
            await self.session.scalars(select(Policy).where(Policy.owner_id == self.owner_id))
        ).all():
            await self.session.delete(policy)
