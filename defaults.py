import enum


# Telegram emoji
class Emoji(enum.StrEnum):
    ENABLED = '\u2714'
    DISABLED = '\u2716'
    REJECTED = '\u26D4'
    FOX = '🦊'
    ZOMBIE = '🧟'


class Notification:
    COMMAND_REJECTED = f'{Emoji.REJECTED} Command rejected for %s.'
    CHAT_INFORMATION_SAVED = f'{Emoji.ENABLED} Current chat information saved.'
    MENU_CLOSED = 'Menu closed.'
    MENU_OPENED = 'Menu is already opened.'

    LOG_COMMAND_REJECTED = 'User %s [%s] is trying to perform an unsafe operation.'
    LOG_SENT_FROM_TO = '%s sent a fox to %s'

    ERROR_MENU_PAGE = 'Menu page context is broken'
    ERROR_MENU_CALLBACK = 'Menu callback content error'
