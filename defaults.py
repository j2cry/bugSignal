import typing

class LogRecord:
    __slots__ = ('_args',)
    EFFECTIVE_IS_NONE = '[%s] Effective %s is None'
    DATA_IS_NONE = '[%s] %s data is None'
    CALLBACK_IS_NONE = 'Callback has no query or query is invalid'

    UNSECURE_OPERATION = 'User %s is trying to perform an unsafe operation: %s'
    INSUFFICIENT_USERROLE = ''

    def __init__(self, *args: typing.Any):
        self._args = args

    def __getattribute__(self, name: str) -> typing.Any:
        value = super().__getattribute__(name)
        args = super().__getattribute__('_args')
        return value % args

# class Notification:
#     CHAT_INFO_UPDATED = '\u2714 Done.'
#     UNSECURE_OPERATION = '\u26D4 This operation is unsafe.'
