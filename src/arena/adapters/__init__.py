"""Pure adapter-boundary contracts."""

from arena.adapters.in_process import (
    ADAPTER_PAYLOAD_SCHEMA_VERSION,
    ActionResponsePayload,
    DomainErrorPayload,
    InProcessAgent,
    ObservationRequestPayload,
    PayloadPolicy,
    TypedPayloadPolicyAdapter,
    apply_payload_policy_turn,
    build_observation_request,
    dump_domain_error,
    load_action_response,
)

__all__ = [
    "ADAPTER_PAYLOAD_SCHEMA_VERSION",
    "ActionResponsePayload",
    "DomainErrorPayload",
    "InProcessAgent",
    "ObservationRequestPayload",
    "PayloadPolicy",
    "TypedPayloadPolicyAdapter",
    "apply_payload_policy_turn",
    "build_observation_request",
    "dump_domain_error",
    "load_action_response",
]
