class MyWeChatError(Exception):
    """An actionable error, safe to report without credentials."""


class CalibrationError(MyWeChatError):
    pass


class SafetyError(MyWeChatError):
    pass


class DeliveryUncertain(MyWeChatError):
    """An action may have happened; never automatically retry it."""
