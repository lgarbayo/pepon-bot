"""Maps a parsed Intent to Action(s), using WorldState for context.

Small and rule-based on purpose, mirroring intent.py: swap the intent
parser for an LLM later and this still works unchanged, since it only
ever depends on the {"intent": ..., ...} shape coming out of parse().
"""
from typing import Optional

import actions
from intent import (
    INTENT_FIND_OBJECT,
    INTENT_LOOK_AT_ME,
    INTENT_WHAT_DO_YOU_SEE,
    INTENT_WHERE_IS,
)
from world_state import ObjectMemory, WorldState


class Agent:
    def __init__(self, world_state: WorldState, action_executor: actions.ActionExecutor):
        self.world_state = world_state
        self.action_executor = action_executor

    async def handle(self, intent: dict) -> None:
        kind = intent.get("intent")
        if kind == INTENT_WHAT_DO_YOU_SEE:
            await self._what_do_you_see()
        elif kind == INTENT_FIND_OBJECT:
            await self._find_object(intent["object"])
        elif kind == INTENT_WHERE_IS:
            await self._where_is(intent["object"])
        elif kind == INTENT_LOOK_AT_ME:
            await self._look_at_me()
        else:
            await self._unknown()

    async def check_active_target(self) -> None:
        """Called once per detection cycle (from the perception loop): if
        we're actively searching for something and it just became
        visible, announce it. Lets FIND_OBJECT resolve asynchronously
        instead of blocking the voice command on "is it visible yet"."""
        target = self.world_state.active_target
        if target is None:
            return
        memory = self.world_state.get_object(target)
        if memory and memory.visible:
            await self._announce_found(target, memory)

    # ---- intent handlers ----

    async def _what_do_you_see(self) -> None:
        visible = [cls for cls, m in self.world_state.objects.items() if m.visible]
        text = f"I see {', '.join(visible)}." if visible else "I don't see anything right now."
        await self.action_executor.execute(actions.speak(text))

    async def _find_object(self, obj: str) -> None:
        memory = self.world_state.get_object(obj)
        if memory and memory.visible:
            await self._announce_found(obj, memory)
            return
        self.world_state.set_active_target(obj)
        self.world_state.set_pepon_state("SEARCHING")  # bookkeeping only —
        # actions.search_object() below already renders the SEARCHING
        # expression on the phone, so don't also go through
        # _set_expression() or the phone gets the same state twice.
        await self.action_executor.execute(actions.search_object(obj))
        await self.action_executor.execute(actions.speak(f"Looking for the {obj}."))

    async def _where_is(self, obj: str) -> None:
        await self.action_executor.execute(actions.speak(self.world_state.describe(obj)))

    async def _look_at_me(self) -> None:
        person = self.world_state.get_object("person")
        if person and person.visible:
            await self.action_executor.execute(actions.look_at(person.x, person.y, target="person"))
        else:
            await self.action_executor.execute(actions.speak("I can't see you right now."))

    async def _unknown(self) -> None:
        await self._set_expression("CONFUSED")
        await self.action_executor.execute(actions.speak("Sorry, I didn't understand that."))

    # ---- shared helpers ----

    async def _announce_found(self, obj: str, memory: ObjectMemory) -> None:
        await self.action_executor.execute(actions.look_at(memory.x, memory.y, target=obj))
        await self._set_expression("FOUND")
        await self.action_executor.execute(
            actions.speak(f"Found the {obj}, on my {memory.position.lower()}.")
        )
        self.world_state.set_active_target(None)

    async def _set_expression(self, state: str) -> None:
        """Renders SET_EXPRESSION *and* keeps world_state.pepon_state in
        sync — mirrors main.py's _set_pepon_state, kept local here to
        avoid an agent.py <-> main.py import cycle."""
        self.world_state.set_pepon_state(state)
        await self.action_executor.execute(actions.set_expression(state))
