# Heartbeat — Audit & Risk Sentinel

- Cadence: every 5 minutes
- Inputs: Hermes events on `snowgloves.events.v1`, Paperclip inbox
- Outputs: routed task, interpreted context, or escalation
- Failure mode: escalate to chief-of-staff, never silent-drop
