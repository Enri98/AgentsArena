"""Remote play helpers: wire typed agents into arena.sdk for arena.server connections.

This module provides the bridge so that an OllamaAgent (or any typed agent with a
select_action() method) can participate in a match hosted by arena.server over
WebSocket, without modifying the agent source code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from arena.adapters.in_process import ObservationRequestPayload


def make_typed_agent_choose(
    agent: Any,
    definition: Any,
) -> Callable[[ObservationRequestPayload], dict[str, Any]]:
    """Adapt a typed agent's select_action() to the SDK choose() callback form.

    Parameters
    ----------
    agent:
        Any object with ``select_action(observation)`` → typed action.
    definition:
        GameDefinition whose serializer converts payload dicts to typed observations
        and typed actions back to payload dicts.

    Returns
    -------
    A sync callable ``(ObservationRequestPayload) -> dict[str, Any]`` suitable for
    passing to ``arena.sdk.connect(url, seat, choose=...)``.
    """

    def choose(request: ObservationRequestPayload) -> dict[str, Any]:
        observation = definition.serializer.load_observation(request.observation)
        action = agent.select_action(observation)
        return definition.serializer.dump_action(action)

    return choose


async def _run_seat(url: str, seat: int, choose: Callable) -> tuple[Any, Any]:
    from arena.sdk import connect

    return await connect(url, seat, choose)


async def _gather_seats(
    seat_urls: Sequence[str],
    seat_chooses: Sequence[Callable],
) -> list[tuple[Any, Any]]:
    tasks = [
        _run_seat(url, seat, choose)
        for seat, (url, choose) in enumerate(zip(seat_urls, seat_chooses))
    ]
    return list(await asyncio.gather(*tasks))


def run_remote_seats_sync(
    seat_urls: Sequence[str],
    seat_chooses: Sequence[Callable],
) -> list[tuple[Any, Any]]:
    """Block until all seat connections to the server complete.

    Parameters
    ----------
    seat_urls:
        WebSocket URLs for each seat, in seat order. Typically taken from the
        ``seat_0_url`` / ``seat_1_url`` fields of the POST /matches response.
    seat_chooses:
        choose() callable for each seat, in the same order.

    Returns
    -------
    List of ``(result_dict, transcript)`` tuples in seat order.
    """
    return asyncio.run(_gather_seats(seat_urls, seat_chooses))


__all__: tuple[str, ...] = ("make_typed_agent_choose", "run_remote_seats_sync")
