"""Boundary serializers for Liar's Dice, including the per-seat and public views.

Three views of the state exist (Phase 38):

* ``dump_state`` — authoritative, with both hands. Never sent to a client; it is
  what the server's full transcript and replay use.
* ``dump_state_for_seat`` — the public view plus that seat's own hand.
* ``dump_public_state`` — no hands at all, only counts, bids and past showdowns.

A roll (the chance outcome) is split the same way: a seat is told its own hand,
the public only the dice counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.core.types import Seat
from arena.games.liarsdice.actions import Bid, Call, LiarsDiceAction, Roll
from arena.games.liarsdice.config import LiarsDiceConfig
from arena.games.liarsdice.observation import LiarsDiceObservation, LiarsDicePublicView
from arena.games.liarsdice.state import LiarsDiceState, Showdown

_T = TypeVar("_T")

_STRICT = ConfigDict(extra="forbid", strict=True)


class LiarsDiceConfigPayload(BaseModel):
    model_config = _STRICT

    dice_per_seat: int = Field(default=3, ge=1, le=6)
    faces: int = Field(default=6, ge=2, le=9)


class BidPayload(BaseModel):
    model_config = _STRICT

    type: Literal["bid"] = "bid"
    quantity: int = Field(ge=1)
    face: int = Field(ge=1)


class CallPayload(BaseModel):
    model_config = _STRICT

    type: Literal["call"] = "call"


ActionPayload = Annotated[BidPayload | CallPayload, Field(discriminator="type")]
_ACTION_ADAPTER: TypeAdapter[BidPayload | CallPayload] = TypeAdapter(ActionPayload)


class _BidBody(BaseModel):
    model_config = _STRICT

    quantity: int = Field(ge=1)
    face: int = Field(ge=1)


class ShowdownPayload(BaseModel):
    model_config = _STRICT

    caller: int = Field(ge=0, le=1)
    bid: _BidBody
    dice: list[list[int]] = Field(min_length=2, max_length=2)
    count: int = Field(ge=0)
    loser: int = Field(ge=0, le=1)


class _PublicFields(BaseModel):
    model_config = _STRICT

    dice_counts: list[Annotated[int, Field(ge=0)]] = Field(min_length=2, max_length=2)
    bids: list[_BidBody]
    current_seat: int = Field(ge=0, le=1)
    round_number: int = Field(ge=0)
    faces: int = Field(ge=2, le=9)
    last_showdown: ShowdownPayload | None = None


class LiarsDiceStatePayload(_PublicFields):
    """Authoritative state: both hands. Server-side only."""

    dice: list[list[int]] | None


class LiarsDicePublicStatePayload(_PublicFields):
    roll_pending: bool


class LiarsDiceSeatStatePayload(LiarsDicePublicStatePayload):
    seat: int = Field(ge=0, le=1)
    my_dice: list[int]


class LiarsDiceObservationPayload(_PublicFields):
    seat: int = Field(ge=0, le=1)
    my_dice: list[int]
    legal_actions: list[ActionPayload]


class RollPayload(BaseModel):
    model_config = _STRICT

    dice: list[list[int]] = Field(min_length=2, max_length=2)


class LiarsDiceSerializer:
    """Concrete boundary serializer for Liar's Dice domain models."""

    # -- config ------------------------------------------------------------------

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        cfg = _expect(config, LiarsDiceConfig)
        return LiarsDiceConfigPayload.model_validate(cfg.model_dump()).model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return LiarsDiceConfig(**LiarsDiceConfigPayload.model_validate(payload).model_dump())

    # -- state -------------------------------------------------------------------

    def dump_state(self, state: object) -> JSONMapping:
        s = _expect(state, LiarsDiceState)
        return LiarsDiceStatePayload(
            **_public_fields(s),
            dice=[list(hand) for hand in s.dice] if s.dice is not None else None,
        ).model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        p = LiarsDiceStatePayload.model_validate(payload)
        return LiarsDiceState(
            dice=(tuple(p.dice[0]), tuple(p.dice[1])) if p.dice is not None else None,
            dice_counts=(p.dice_counts[0], p.dice_counts[1]),
            bids=tuple(Bid(quantity=b.quantity, face=b.face) for b in p.bids),
            current_seat=p.current_seat,
            round_number=p.round_number,
            faces=p.faces,
            last_showdown=_load_showdown(p.last_showdown),
        )

    def dump_public_state(self, state: object) -> JSONMapping:
        s = _expect(state, LiarsDiceState)
        return LiarsDicePublicStatePayload(
            **_public_fields(s), roll_pending=_roll_pending(s)
        ).model_dump(mode="json")

    def load_public_state(self, payload: JSONMapping) -> object:
        p = LiarsDicePublicStatePayload.model_validate(payload)
        return LiarsDicePublicView(
            dice_counts=(p.dice_counts[0], p.dice_counts[1]),
            bids=tuple(Bid(quantity=b.quantity, face=b.face) for b in p.bids),
            current_seat=p.current_seat,
            round_number=p.round_number,
            faces=p.faces,
            last_showdown=_load_showdown(p.last_showdown),
            roll_pending=p.roll_pending,
        )

    def dump_state_for_seat(self, state: object, seat: Seat) -> JSONMapping:
        s = _expect(state, LiarsDiceState)
        return LiarsDiceSeatStatePayload(
            **_public_fields(s),
            roll_pending=_roll_pending(s),
            seat=seat,
            my_dice=list(s.dice[seat]) if s.dice is not None else [],
        ).model_dump(mode="json")

    # -- actions -----------------------------------------------------------------

    def dump_action(self, action: object) -> JSONMapping:
        return _dump_action(_expect(action, LiarsDiceAction))

    def load_action(self, payload: JSONMapping) -> object:
        return _load_action(_ACTION_ADAPTER.validate_python(payload))

    # -- observations ------------------------------------------------------------

    def dump_observation(self, observation: object) -> JSONMapping:
        o = _expect(observation, LiarsDiceObservation)
        return LiarsDiceObservationPayload(
            dice_counts=list(o.dice_counts),
            bids=[_BidBody(quantity=b.quantity, face=b.face) for b in o.bids],
            current_seat=o.current_seat,
            round_number=o.round_number,
            faces=o.faces,
            last_showdown=_dump_showdown(o.last_showdown),
            seat=o.seat,
            my_dice=list(o.my_dice),
            legal_actions=[
                _ACTION_ADAPTER.validate_python(_dump_action(a)) for a in o.legal_actions
            ],
        ).model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        p = LiarsDiceObservationPayload.model_validate(payload)
        return LiarsDiceObservation(
            seat=p.seat,
            my_dice=tuple(p.my_dice),
            dice_counts=(p.dice_counts[0], p.dice_counts[1]),
            bids=tuple(Bid(quantity=b.quantity, face=b.face) for b in p.bids),
            current_seat=p.current_seat,
            round_number=p.round_number,
            faces=p.faces,
            last_showdown=_load_showdown(p.last_showdown),
            legal_actions=tuple(_load_action(a) for a in p.legal_actions),
        )

    # -- chance outcomes -----------------------------------------------------------

    def dump_chance_outcome(self, outcome: object) -> JSONMapping:
        roll = _expect(outcome, Roll)
        return RollPayload(dice=[list(hand) for hand in roll.dice]).model_dump(mode="json")

    def load_chance_outcome(self, payload: JSONMapping) -> object:
        p = RollPayload.model_validate(payload)
        return Roll(dice=(tuple(p.dice[0]), tuple(p.dice[1])))

    def dump_chance_outcome_for_seat(self, outcome: object, seat: Seat) -> JSONMapping:
        if type(seat) is not int or seat not in (0, 1):
            raise ValueError(f"A roll is split for seat 0 or 1, not {seat!r}.")
        roll = _expect(outcome, Roll)
        return {"my_dice": list(roll.dice[seat])}

    def dump_public_chance_outcome(self, outcome: object) -> JSONMapping:
        roll = _expect(outcome, Roll)
        return {"dice_counts": [len(hand) for hand in roll.dice]}


def _roll_pending(s: LiarsDiceState) -> bool:
    # Not just "no dice": a finished match has none either, and no roll coming.
    return s.dice is None and min(s.dice_counts) > 0


def _public_fields(s: LiarsDiceState) -> dict:
    return {
        "dice_counts": list(s.dice_counts),
        "bids": [_BidBody(quantity=b.quantity, face=b.face) for b in s.bids],
        "current_seat": s.current_seat,
        "round_number": s.round_number,
        "faces": s.faces,
        "last_showdown": _dump_showdown(s.last_showdown),
    }


def _dump_showdown(showdown: Showdown | None) -> ShowdownPayload | None:
    if showdown is None:
        return None
    return ShowdownPayload(
        caller=showdown.caller,
        bid=_BidBody(quantity=showdown.bid.quantity, face=showdown.bid.face),
        dice=[list(hand) for hand in showdown.dice],
        count=showdown.count,
        loser=showdown.loser,
    )


def _load_showdown(payload: ShowdownPayload | None) -> Showdown | None:
    if payload is None:
        return None
    return Showdown(
        caller=payload.caller,
        bid=Bid(quantity=payload.bid.quantity, face=payload.bid.face),
        dice=(tuple(payload.dice[0]), tuple(payload.dice[1])),
        count=payload.count,
        loser=payload.loser,
    )


def _dump_action(action: LiarsDiceAction) -> JSONMapping:
    if isinstance(action, Bid):
        return BidPayload(quantity=action.quantity, face=action.face).model_dump(mode="json")
    if isinstance(action, Call):
        return CallPayload().model_dump(mode="json")
    raise TypeError(f"Unknown Liar's Dice action {type(action).__name__}.")


def _load_action(payload: BidPayload | CallPayload) -> LiarsDiceAction:
    if isinstance(payload, BidPayload):
        return Bid(quantity=payload.quantity, face=payload.face)
    return Call()


def _expect(value: object, expected: type[_T]) -> _T:
    if not isinstance(value, expected):
        raise TypeError(f"Expected {expected.__name__}, got {type(value).__name__}.")
    return value


__all__: Sequence[str] = [
    "BidPayload",
    "CallPayload",
    "LiarsDiceConfigPayload",
    "LiarsDiceObservationPayload",
    "LiarsDicePublicStatePayload",
    "LiarsDiceSeatStatePayload",
    "LiarsDiceSerializer",
    "LiarsDiceStatePayload",
    "RollPayload",
    "ShowdownPayload",
]
