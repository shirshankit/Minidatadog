import json
import logging
import os
from datetime import datetime, timezone
from threading import Lock
from urllib.error import URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
_last_notifications: dict[int, datetime] = {}
_notification_lock = Lock()


def notify_triggered_alerts(
    alerts: list[dict[str, str | float | int | bool]],
) -> int:
    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url or not alerts:
        return 0

    cooldown_seconds = int(
        os.getenv("ALERT_COOLDOWN_SECONDS", "900")
    )
    if cooldown_seconds < 0:
        raise ValueError("ALERT_COOLDOWN_SECONDS must not be negative")

    now = datetime.now(timezone.utc)
    sent_count = 0

    for alert in alerts:
        alert_id = int(alert["id"])
        with _notification_lock:
            last_sent = _last_notifications.get(alert_id)
            if (
                last_sent is not None
                and (now - last_sent).total_seconds() < cooldown_seconds
            ):
                continue

        payload = json.dumps(
            {
                "text": (
                    f"MiniDatadog alert: {alert['service_name']} "
                    f"{alert['metric']} {alert['operator']} "
                    f"{alert['threshold']} "
                    f"(current: {alert['current_value']})"
                ),
                "alert": alert,
            }
        ).encode("utf-8")
        request = Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=5) as response:
                if response.status < 200 or response.status >= 300:
                    raise URLError(
                        f"webhook returned HTTP {response.status}"
                    )
        except (OSError, ValueError) as error:
            logger.warning(
                "Unable to send alert webhook notification: %s",
                error,
            )
            continue

        with _notification_lock:
            _last_notifications[alert_id] = now
        sent_count += 1

    return sent_count


def clear_notification_state() -> None:
    with _notification_lock:
        _last_notifications.clear()
