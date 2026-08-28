import base64
import json
import os
import re
import urllib.error
import urllib.request

from flask_babel import gettext as _

BEEM_SEND_URL = "https://apisms.beem.africa/v1/send"


class SmsError(Exception):
    """Raised for any reason an SMS could not be sent -- missing config, a bad
    phone number, or a Beem API/network failure. Message is translated (see
    flask_babel usage below), safe to flash directly to the user."""


def normalize_phone(raw):
    """Converts a Tanzanian number in any common local form (07XXXXXXXX,
    +255XXXXXXXXX, 255XXXXXXXXX, 7XXXXXXXX) to Beem's 255XXXXXXXXX format.
    Returns None if it doesn't match a recognizable shape."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    if len(digits) == 12 and digits.startswith("255"):
        return digits
    return None


def can_send(car):
    """(bool, reason) -- whether this car's driver is set up to receive SMS at
    all, independent of who's asking (permission is checked separately per view)."""
    driver = car.driver
    if driver is None:
        return False, _("Gari %(code)s halina dereva aliyewekwa.", code=car.code)
    if not driver.active:
        return False, _("Dereva wa %(code)s amezimwa.", code=car.code)
    if not driver.sms_enabled:
        return False, _("SMS zimezimwa kwa dereva wa %(code)s.", code=car.code)
    if not driver.phone:
        return False, _("Namba ya simu ya dereva wa %(code)s haijawekwa.", code=car.code)
    if not normalize_phone(driver.phone):
        return False, _(
            "Namba ya simu ya dereva wa %(code)s si sahihi (%(phone)s).", code=car.code, phone=driver.phone
        )
    return True, None


def send_sms(phone, message):
    """Sends one SMS via Beem Africa. Raises SmsError on any failure."""
    api_key = os.environ.get("API_KEY")
    secret_key = os.environ.get("BULK_SMS_SECRET_KEY")
    sender_id = os.environ.get("BEEM_SENDER_ID")
    if not api_key or not secret_key or not sender_id:
        raise SmsError(_("Mipangilio ya SMS (Beem) haijakamilika kwenye seva. Wasiliana na msimamizi."))

    dest = normalize_phone(phone)
    if not dest:
        raise SmsError(_("Namba ya simu si sahihi: %(phone)s", phone=phone))

    payload = {
        "source_addr": sender_id,
        "encoding": 0,
        "message": message,
        "recipients": [{"recipient_id": 1, "dest_addr": dest}],
    }
    token = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    req = urllib.request.Request(
        BEEM_SEND_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SmsError(
            _("Beem SMS imekataa ombi (%(code)s): %(detail)s", code=e.code, detail=e.read().decode()[:200])
        )
    except urllib.error.URLError as e:
        raise SmsError(_("Imeshindwa kuwasiliana na Beem SMS: %(reason)s", reason=e.reason))
    except (ValueError, TimeoutError) as e:
        raise SmsError(_("Jibu lisilotarajiwa kutoka Beem SMS: %(error)s", error=e))

    if not body.get("successful"):
        raise SmsError(
            _("Beem SMS imekataa ujumbe: %(detail)s", detail=body.get("message") or body)
        )


def send_debt_payment_sms(car, amount_paid, balance, user=None):
    """Notifies car's driver that a debt payment was just recorded -- how much
    was paid and how much remains, or that the debt is now fully cleared.
    Best-effort: silently returns (False, reason) if the driver isn't set up to
    receive SMS, same checks as a manual send (see can_send)."""
    ok, reason = can_send(car)
    if not ok:
        return False, reason
    if balance <= 0.01:
        message = _(
            "Habari %(name)s, malipo ya %(amount)s yamepokelewa. Hongera, deni lako limekwisha kabisa!",
            name=car.driver.name,
            amount=f"{amount_paid:,.0f}",
        )
    else:
        message = _(
            "Habari %(name)s, malipo ya %(amount)s yamepokelewa. Deni linalobaki: %(balance)s.",
            name=car.driver.name,
            amount=f"{amount_paid:,.0f}",
            balance=f"{balance:,.0f}",
        )
    return send_and_log(car, "debt_payment", message, user)


def send_and_log(car, scenario, message, user):
    """Sends the SMS for a car/scenario and always records the attempt (sent or
    failed) to SmsLog. Returns (ok, error_message). Caller is expected to have
    already checked can_send(car) so this only covers actual send attempts."""
    from .extensions import db
    from .models import SmsLog

    driver = car.driver
    log = SmsLog(
        car_id=car.id,
        driver_id=driver.id if driver else None,
        phone=driver.phone if driver else None,
        scenario=scenario,
        message=message,
        sent_by_id=user.id if user else None,
    )
    try:
        send_sms(driver.phone, message)
        log.status = "sent"
        db.session.add(log)
        db.session.commit()
        return True, None
    except SmsError as e:
        log.status = "failed"
        log.error = str(e)
        db.session.add(log)
        db.session.commit()
        return False, str(e)
