"""
Calendar adapter factory.

Looks at client config's "calendar_type" field and returns
the appropriate adapter. Falls back to demo mode if
the type is unknown or credentials are missing.
"""

import logging
from .base import CalendarAdapter
from .demo_cal import DemoAdapter
from .google_cal import GoogleAdapter
from .calendly_cal import CalendlyAdapter
from .outlook_cal import OutlookAdapter

logger = logging.getLogger(__name__)

# Registry — add new providers here
ADAPTERS = {
    "demo": DemoAdapter,
    "google": GoogleAdapter,
    "calendly": CalendlyAdapter,
    "outlook": OutlookAdapter,
}


def get_calendar(client_config: dict) -> CalendarAdapter:
    """
    Factory function — returns the right calendar adapter
    for a client based on their config.

    Falls back to DemoAdapter if type is unrecognized
    or required credentials are missing.
    """
    cal_type = client_config.get("calendar_type", "demo").lower()

    adapter_class = ADAPTERS.get(cal_type)
    if not adapter_class:
        logger.warning(f"Unknown calendar_type '{cal_type}' — falling back to demo")
        adapter_class = DemoAdapter

    try:
        adapter = adapter_class(client_config)
        logger.info(f"Calendar adapter: {adapter.provider_name} for {client_config.get('business_name', '?')}")
        return adapter
    except Exception as e:
        logger.error(f"Failed to init {cal_type} adapter: {e} — falling back to demo")
        return DemoAdapter(client_config)
