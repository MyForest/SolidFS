import logging

import structlog

can_use_open_telemetry = False
try:
    import opentelemetry

    can_use_open_telemetry = False
except:
    logging.warning("Unable to import opentelemetry to extend logs", exc_info=True)


class AppLogging:

    @staticmethod
    def _add_open_telemetry_spans(_, __, event_dict):
        # See https://www.structlog.org/en/stable/frameworks.html#opentelemetry

        span = opentelemetry.trace.get_current_span()
        if not span.is_recording():
            # event_dict[0][0]["span"] = None
            return event_dict

        ctx = span.get_span_context()
        parent = getattr(span, "parent", None)

        dictionary_to_update = event_dict[0][0]

        dictionary_to_update["span_id"] = opentelemetry.trace.format_span_id(ctx.span_id)
        dictionary_to_update["trace_id"] = opentelemetry.trace.format_trace_id(ctx.trace_id)
        if parent:
            dictionary_to_update["parent_span_id"] = opentelemetry.trace.format_span_id(parent.span_id)

        return event_dict

    @staticmethod
    def configure_logging():
        timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")
        shared_processors = [
            structlog.stdlib.add_log_level,
            timestamper,
        ]

        processors = shared_processors + [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        if can_use_open_telemetry:
            processors.append(AppLogging._add_open_telemetry_spans)

        structlog.configure(
            processors=processors,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        formatter = structlog.stdlib.ProcessorFormatter(
            # These run ONLY on `logging` entries that do NOT originate within
            # structlog.
            foreign_pre_chain=shared_processors,
            # These run on ALL entries after the pre_chain is done.
            processors=[
                # Remove _record & _from_structlog.
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(),
            ],
        )

        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
