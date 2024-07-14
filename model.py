from __future__ import annotations
import datetime as dt
import enum
import sqlalchemy as sa
import sqlalchemy.dialects.mssql as mssql
import sqlalchemy.dialects.postgresql as psql
import typing

from collections import namedtuple
from telegram import Chat, User, Message
from telegram.ext import CallbackContext, ContextTypes, ExtBot


# Telegram emoji
class Emoji(enum.StrEnum):
    ENABLED = '\u2714'
    DISABLED = '\u2716'
    DECLINED = '\u26D4'

# --------------------------------------------------------------------------------
# callback data typing
class MenuPattern(enum.StrEnum):
    EMPTY = ''
    MAIN = enum.auto()
    GRANT = enum.auto()

class Action(enum.IntEnum):
    CLOSE = enum.auto()
    MENU = enum.auto()
    BACK = enum.auto()
    NEXTPAGE = enum.auto()
    PREVPAGE = enum.auto()
    SWITCH = enum.auto()
    CHATS = enum.auto()
    LISTENERS = enum.auto()
    SUBSCRIPTIONS = enum.auto()
    ROLES = enum.auto()

class CallbackKey(enum.StrEnum):
    ACTION = enum.auto()
    CHAT_ID = enum.auto()
    LISTENER_ID = enum.auto()
    ROLE = enum.auto()
    ACTIVE = enum.auto()

class CallbackContent(typing.TypedDict):
    action: Action | None
    chat_id: typing.NotRequired[int]
    listener_id: typing.NotRequired[int]
    active: typing.NotRequired[bool]

CallbackProtocol = typing.MutableMapping[str | None, CallbackContent]

# --------------------------------------------------------------------------------
# bot context typing
class RowLike(typing.Protocol):
    @property
    def _fields(self) -> tuple[str, ...]: ...
    def _asdict(self) -> dict[str, typing.Any]: ...
    def __getattr__(self, name: str) -> typing.Any: ...

BT = ExtBot[None]
UD = typing.TypedDict('UD', {})
CD = typing.TypedDict('CD', {
    'back_action': Action | None,           # action for BACK button
    'menupattern': MenuPattern,
    'menulist': typing.Sequence[RowLike],    # NOTE todo type hints?
    'menutext': str,
    'marker': bool,                         # marker for printing ckecks before button text
    'page': int,                            # current menu page
    'callback': CallbackProtocol,
    'default_button_action': typing.NotRequired[Action | None],
})
BD = typing.TypedDict('BD', {})
CCT = CallbackContext[BT, UD, CD, BD]
CT = ContextTypes(CallbackContext, UD, CD, BD)

class ValidatedContext(typing.TypedDict):
    user: User
    chat: Chat
    message: Message
    user_data: UD
    chat_data: CD
    bot_data: BD

# --------------------------------------------------------------------------------
# SQL typing
class ChatValues(typing.TypedDict):
    title: typing.NotRequired[str]
    type: typing.NotRequired[str]
    role: typing.NotRequired[int]
    active: typing.NotRequired[bool]

class ListenerValues(typing.TypedDict):
    title: typing.NotRequired[str]
    classname: typing.NotRequired[str]
    parameters: typing.NotRequired[str]
    active: typing.NotRequired[bool]

class SubscriptionValues(typing.TypedDict):
    active: typing.NotRequired[bool]

class UserRole(enum.IntFlag):
    """ User roles """
    BLOCKED = 0
    USER = enum.auto()
    MODERATOR = enum.auto()
    DEVELOPER = enum.auto()
    MASTER = enum.auto()
    ADMINS = MODERATOR | MASTER
    ACTIVE = USER | MODERATOR | DEVELOPER | MASTER
    ANY = BLOCKED | ACTIVE


# --------------------------------------------------------------------------------
# SQL definitions
class CustomTableRow:
    def __new__(cls, **kwargs) -> RowLike:
        _class = namedtuple('_CustomTableRow', kwargs.keys())
        instance = _class(**kwargs)
        # setattr(instance, '__getattr__', cls.__getattr__)
        # instance.__getattr__ = cls.__getattr__
        return instance     # type: ignore

    def __getattr__(self, name: str) -> typing.Any:
        return self.__getattribute__(name)

class _ListenerTable(typing.Protocol):
    """ Specific source for receiving messages """
    __tablename__: str
    listener_id: sa.Column[int]
    title: sa.Column[str]
    classname: sa.Column[str]
    parameters: sa.Column[str]
    active: sa.Column[bool]
    created: sa.Column[dt.datetime]
    updated: sa.Column[dt.datetime]
class ListenerTableRow(RowLike, typing.Protocol):
    """ Listener table row protocol """
    listener_id: int
    title: str
    classname: str
    parameters: str
    active: bool
    created: dt.datetime
    updated: dt.datetime

class _ChatTable(typing.Protocol):
    """ Telegram chat (group or private) """
    __tablename__: str
    chat_id: sa.Column[int]
    title: sa.Column[str]
    role: sa.Column[int]
    type: sa.Column[str]
    active: sa.Column[bool]
    created: sa.Column[dt.datetime]
    updated: sa.Column[dt.datetime]
class ChatTableRow(RowLike, typing.Protocol):
    """ Chat table row protocol """
    chat_id: int
    title: str
    role: int
    type: str
    active: bool
    created: dt.datetime
    updated: dt.datetime


class _SubscriptionTable(typing.Protocol):
    """ Chat subscriptions to listeners """
    __tablename__: str
    subscription_id: sa.Column[int]
    chat_id: sa.Column[int]
    listener_id: sa.Column[int]
    active: sa.Column[bool]
    created: sa.Column[dt.datetime]
    updated: sa.Column[dt.datetime]
class SubscriptionTableRow(RowLike, typing.Protocol):
    """ Chat subscriptions table row protocol """
    subscription_id: int
    chat_id: int
    listener_id: int
    active: bool
    created: dt.datetime
    updated: dt.datetime

ListenerTable: typing.TypeAlias = type[_ListenerTable]
ChatTable: typing.TypeAlias = type[_ChatTable]
SubscriptionTable: typing.TypeAlias = type[_SubscriptionTable]
AnyTable = ListenerTable | ChatTable | SubscriptionTable
AnyTableRow = ListenerTableRow | ChatTableRow | SubscriptionTableRow


def definitions_loader(dialect: str) -> tuple[ListenerTable,
                                              ChatTable,
                                              SubscriptionTable]:
    """ Load SQL table definitions for specified dialect """
    class ImplementedDialect(enum.StrEnum):
        MSSQL = enum.auto()
        POSTGRESQL = enum.auto()

    match dialect:
        # MSSQL definitions
        case ImplementedDialect.MSSQL:
            class _MSSQL_Listener:
                __tablename__ = 'listener'
                listener_id = sa.Column(mssql.INTEGER, primary_key=True, autoincrement="auto")
                title = sa.Column(mssql.VARCHAR(500), nullable=False)
                classname = sa.Column(mssql.VARCHAR(50), nullable=False)
                parameters = sa.Column(mssql.VARCHAR, nullable=False, server_default=sa.literal(r'{}'))
                # polling = sa.Column(mssql., nullable=False)     # TODO
                active = sa.Column(mssql.BIT, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
            class _MSSQL_Chat:
                __tablename__ = 'chat'
                chat_id = sa.Column(mssql.BIGINT, primary_key=True)
                title = sa.Column(mssql.VARCHAR(500))
                role = sa.Column(mssql.SMALLINT, nullable=False, server_default=sa.literal(UserRole.USER.value))
                type = sa.Column(mssql.VARCHAR(10), nullable=False)
                active = sa.Column(mssql.BIT, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
            class _MSSQL_Subscription:
                __tablename__ = 'subscription'
                subscription_id = sa.Column(mssql.BIGINT, primary_key=True)
                chat_id = sa.Column(mssql.BIGINT, sa.ForeignKey(_MSSQL_Chat.chat_id), nullable=False)
                listener_id = sa.Column(mssql.INTEGER, sa.ForeignKey(_MSSQL_Listener.listener_id), nullable=False)
                active = sa.Column(mssql.BIT, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())

            return (_MSSQL_Listener, _MSSQL_Chat, _MSSQL_Subscription)

        # PostgreSQL definitions
        case ImplementedDialect.POSTGRESQL:
            class _PostgreSQL_Listener:
                __tablename__ = 'listener'
                listener_id = sa.Column(psql.INTEGER, primary_key=True, autoincrement="auto")
                title = sa.Column(psql.VARCHAR(500), nullable=False)
                classname = sa.Column(psql.VARCHAR(50), nullable=False)
                parameters = sa.Column(psql.VARCHAR, nullable=False, server_default=sa.literal(r'{}'))
                # polling = sa.Column(psql., nullable=False)  # TODO
                active = sa.Column(psql.BOOLEAN, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
            class _PostgreSQL_Chat:
                __tablename__ = 'chat'
                chat_id = sa.Column(psql.BIGINT, primary_key=True)
                title = sa.Column(psql.VARCHAR(500))
                role = sa.Column(psql.SMALLINT, nullable=False, server_default=sa.literal(UserRole.USER.value))
                type = sa.Column(psql.VARCHAR(10), nullable=False)
                active = sa.Column(psql.BOOLEAN, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
            class _PostgreSQL_Subscription:
                __tablename__ = 'subscription'
                subscription_id = sa.Column(psql.BIGINT, primary_key=True)
                chat_id = sa.Column(psql.BIGINT, sa.ForeignKey(_PostgreSQL_Chat.chat_id), nullable=False)
                listener_id = sa.Column(psql.INTEGER, sa.ForeignKey(_PostgreSQL_Listener.listener_id), nullable=False)
                active = sa.Column(psql.BOOLEAN, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())

            return (_PostgreSQL_Listener, _PostgreSQL_Chat, _PostgreSQL_Subscription)

        case _:
            raise NotImplementedError(f'No SQL definitions implemented for specified dialect `{dialect}`')
