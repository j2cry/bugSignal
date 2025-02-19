from __future__ import annotations
import enum
import typing
from copy import deepcopy


# Telegram emoji
class Emoji(enum.StrEnum):
    ENABLED = '🟢'
    DISABLED = '❌'
    REJECTED = '⛔'
    FOX = '🦊'
    ZOMBIE = '🧟'


# --------------------------------------------------------------------------------
class Environ(enum.StrEnum):
    """ Environment variables' names """
    TELEGRAM_TOKEN = 'BUGSIGNAL_TELEGRAM_TOKEN'
    SQL_CONNECTION_STRING = 'BUGSIGNAL_SQL_CONNECTION_STRING'

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
    close: int | float
    actualizerCron: str
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
    timeout=TimeoutConfig(
        common=300,
        close=5,
        actualizerCron='5 0 * * *',
        retryInterval=15,
        lifetime=30,
    ),
    timezone='UTC',
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
    MESSAGE_COMMAND_REJECTED = f'⛔ Command rejected for %s.'
    MESSAGE_CHAT_INFORMATION_SAVED = f'✅ Current chat information saved.'
    MESSAGE_MENU_CLOSED = 'Menu closed.'
    MESSAGE_MENU_OPENED = 'Menu is already opened.'
    MESSAGE_CHECK_LISTENERS = 'Forcing listeners...'
    MESSAGE_DONE = '✅ done.'
    # MESSAGE_LISTENER_ERROR = '❗❗❗ UFO has stolen your listener [{name}] 👽💀👻😱'
    MESSAGE_SOMETHING_WRONG = "I think i'm gonna throw up 🤢. Check my log please."
    MESSAGE_CHECK_FAILED = "❌ Check failed for listener %s - %s"
    MESSAGE_SHUTDOWN = 'Shutdown job was scheduled. See ya! 👋'
    MESSAGE_SHUTDOWN_CONFIRM = ('Are you sure you want to shutdown the tracker? '
                                '<b>It is impossible to turn it back on without access to the server.</b>')
    MESSAGE_JOB_STATE = '📌 %s @ %s'
    MESSAGE_SELF_STATE = '[%s] Self state (%s):\n%s\nActive listeners: %s'
    MESSAGE_INCORRECT_ARGS = '🚧 Incorrect command arguments.'

    LOG_CHECK_LISTENER = 'Checking for updates in listener %s [%s] from timestamp %s'
    LOG_NO_UPDATES = 'Listener %s [%s] has no updates'
    LOG_JOB_SCHEDULED = 'Job %s for %s [%s] scheduled @ %s'
    LOG_LISTENER_INHERITED = 'Listener %s [%s] inherited'
    LOG_COMMAND_REJECTED = 'User %s [%s] is trying to perform an unsafe operation'
    LOG_SENT_FROM_TO = '%s sent a fox to %s'
    LOG_SHUTDOWN = 'The user %s [%s] initiated the shutdown of the service'
    LOG_MESSAGE_SENT = 'Message sent to %s successfully'
    LOG_INCORRECT_TIMEZONE = 'Incorrect timezone `%s`. Timezone set to UTC'

    ERROR_MENU_PAGE = 'Menu page context is broken'
    ERROR_MENU_CALLBACK = 'Menu callback content error'
    ERROR_LISTENER = 'Listener %s [%s] caused an exception [%s]: %s\n%s'
    ERROR_TRACEBACK = '[%s]: %s\n%s'
    ERROR_NOT_SENT_TRACEBACK = 'Message not sent [%s]: %s\n%s'
