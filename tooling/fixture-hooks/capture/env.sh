# Telemetry for the #295 capture sessions. Source it in the terminal that
# launches `claude`, after starting otlp_sink.py:  source env.sh
#
# Per-signal endpoints, because the docs never say whether the generic
# OTEL_EXPORTER_OTLP_ENDPOINT gets /v1/<signal> appended. Claude Code has no
# default protocol, so it is set explicitly. Tool details and prompt logging
# stay off: the sink would drop their values anyway, but they should never be
# produced in the first place.

export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_LOGS_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://127.0.0.1:4318/v1/metrics
export OTEL_LOGS_EXPORT_INTERVAL=1000
export OTEL_METRIC_EXPORT_INTERVAL=5000
unset OTEL_LOG_TOOL_DETAILS OTEL_LOG_USER_PROMPTS

# Hold the Claude Code version for the whole series. The first run drifted from
# v2.1.299 to v2.1.301 between S1 and S1b.
export DISABLE_AUTOUPDATER=1
