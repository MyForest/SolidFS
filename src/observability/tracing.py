import functools
import logging

can_use_open_telemetry = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    trace.set_tracer_provider(TracerProvider())
    can_use_open_telemetry = False
except:
    logging.warning("Unable to import opentelemetry to trace functions", exc_info=True)


class Tracing:
    @staticmethod
    def traced(func):
        if can_use_open_telemetry:

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                with trace.get_tracer("SolidFS").start_as_current_span(func.__name__):
                    return func(*args, **kwargs)

            return wrapper
        return func

    @staticmethod
    def get_trace_headers() -> dict[str, str]:
        if not can_use_open_telemetry:
            return {}

        # The X prefix is deprecated: https://datatracker.ietf.org/doc/html/rfc6648
        trace_headers = {}

        current_span = trace.get_current_span().get_span_context()

        span_id = current_span.span_id
        if span_id:
            trace_headers["X-Request-ID"] = trace.format_span_id(span_id)
            trace_headers["Request-ID"] = trace.format_span_id(span_id)

        trace_id = current_span.trace_id
        if trace_id:
            trace_headers["X-Correlation-ID"] = trace.format_trace_id(trace_id)
            trace_headers["Correlation-ID"] = trace.format_trace_id(trace_id)

        return trace_headers
