from __future__ import annotations

import logging
import os


def configure_error_monitoring() -> dict[str, object]:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return {"configured": False, "provider": "structured_logs"}
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("APP_ENV", "development"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            send_default_pii=False,
        )
        return {"configured": True, "provider": "sentry", "pii": False}
    except Exception:
        logging.getLogger("eagleeyes.operations").exception("error_monitoring_configuration_failed")
        return {"configured": False, "provider": "structured_logs", "warning": "Sentry initialization failed"}
