from __future__ import annotations
import enum
import typing
from copy import deepcopy


# Telegram emoji
class Emoji(enum.StrEnum):
    ENABLED = '\u2714'
    DISABLED = '\u2716'
    REJECTED = '\u26D4'
    FOX = '🦊'
    ZOMBIE = '🧟'


# --------------------------------------------------------------------------------
class Environ(enum.StrEnum):
    """ Environment variables' names """
    TELEGRAM_TOKEN = 'BUGSIGNAL_TELEGRAM_TOKEN'
    SQL_CONNECTION_STRING = 'BUGSIGNAL_SQL_CONNECTION_STRING'
    SQL_CONNECTION_SCHEMA = 'BUGSIGNAL_SQL_CONNECTION_SCHEMA'

# --------------------------------------------------------------------------------
class LoggerConfig(typing.TypedDict):
    """ Logger configuration """
    filename: str
    mode: str
    maxBytes: int
    backupCount: int
    encoding: str | None
    delay: bool
    errors: str | None
    level: typing.Literal['CRITICAL', 'FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG']

class TimeoutConfig(typing.TypedDict):
    """ Timeout configuration """
    common: int | float
    start: int | float
    close: int | float
    actualizeInterval: int | float
    retryInterval: int | float
    lifetime: int | float

class Configuration(typing.TypedDict):
    """ Service configuration """
    logger: LoggerConfig
    timeout: TimeoutConfig
    timezone: str
    sqlSchema: str | None

ANY_CONFIG_TYPE: typing.TypeAlias = Configuration | LoggerConfig | TimeoutConfig

# --------------------------------------------------------------------------------
DEFAULT = Configuration(
    logger=LoggerConfig(
        filename='logs/bugsignal.log',
        mode='a',
        maxBytes=1024 * 1024 * 5,
        backupCount=3,
        encoding='utf-8',
        delay=False,
        errors=None,
        level='DEBUG',
    ),
    timezone='UTC',
    timeout=TimeoutConfig(
        common=300,
        start=2.5,
        close=5,
        actualizeInterval=86400,
        retryInterval=15,
        lifetime=30,
    ),
    sqlSchema='bugsignal',
)

def build_configuration(cf: typing.Mapping[typing.Any, typing.Any]) -> Configuration:
    """ Update default configuration """
    def __update_configuration[T: ANY_CONFIG_TYPE](df: T, cf: typing.Mapping) -> T:
        _config = deepcopy(df)
        for k, v in _config.items():
            if k not in cf:
                continue
            elif isinstance(v, typing.Mapping):
                _config[k] = __update_configuration(_config[k], cf[k])
            else:
                _config[k] = cf[k]
        return _config
    return __update_configuration(DEFAULT, cf)


# --------------------------------------------------------------------------------
class Notification:
    MESSAGE_QUERY_ANSWER = '👻'
    MESSAGE_COMMAND_REJECTED = f'{Emoji.REJECTED} Command rejected for %s.'
    MESSAGE_CHAT_INFORMATION_SAVED = f'{Emoji.ENABLED} Current chat information saved.'
    MESSAGE_MENU_CLOSED = 'Menu closed.'
    MESSAGE_MENU_OPENED = 'Menu is already opened.'
    MESSAGE_CHECK_LISTENERS = 'Forcing listeners...'
    MESSAGE_DONE = '✔ done.'
    MESSAGE_LISTENER_ERROR = '❗❗❗ UFO has stolen your listener [{name}] 👽💀👻😱'
    MESSAGE_SOMETHING_WRONG = "I think i'm gonna throw up 🤢. Check my log please."
    MESSAGE_SHUTDOWN = 'Shutdown job was scheduled. See ya! 👋'

    LOG_NO_UPDATES = 'Listener %s [%s] has no updates'
    LOG_JOB_SCHEDULED = 'Job %s scheduled @ %s'
    LOG_JOB_UPDATED = 'Job %s updated. Next run @ %s'
    LOG_COMMAND_REJECTED = 'User %s [%s] is trying to perform an unsafe operation'
    LOG_SENT_FROM_TO = '%s sent a fox to %s'
    LOG_SHUTDOWN = 'The user %s [%s] initiated the shutdown of the service'
    LOG_MESSAGE_SENT = 'Message sent to %s successfully'

    ERROR_MENU_PAGE = 'Menu page context is broken'
    ERROR_MENU_CALLBACK = 'Menu callback content error'
    ERROR_LISTENER = 'Listener %s [%s] caused an exception [%s]: %s\n%s'
    ERROR_TRACEBACK = '[%s]: %s\n%s'
    ERROR_NOT_SENT_TRACEBACK = 'Message not sent [%s]: %s\n%s'
