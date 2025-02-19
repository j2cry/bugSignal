from __future__ import annotations
import datetime as dt
import enum
import sqlalchemy as sa
import sqlalchemy.dialects.mssql as mssql
import sqlalchemy.dialects.postgresql as psql
import typing

from collections import namedtuple
from dataclasses import dataclass
from telegram import Chat, User, Message
from telegram.ext import CallbackContext, ContextTypes, ExtBot, JobQueue

if typing.TYPE_CHECKING:
    from menupage import InlineMenuPage


class UserRole(enum.IntFlag):
    """ User roles """
    BLOCKED = 0
    USER = enum.auto()
    MODERATOR = enum.auto()
    MASTER = enum.auto()
    DEVELOPER = enum.auto()
    WIZARD = enum.auto()
    PALLADIN = enum.auto()
    NECROMANCER = enum.auto()
    ADMINS = MODERATOR | MASTER
    ACTIVE = USER | MODERATOR | MASTER


# --------------------------------------------------------------------------------
# JobQueue data
@dataclass(frozen=True, slots=True)
class JobData:
    listener_id: int

# JobQueue naming
class JobName(enum.StrEnum):
    ACTUALIZER = enum.auto()
    LISTENER = enum.auto()
    CHECKER = enum.auto()

MISFIRE_GRACE = dict(
    misfire_grace_time=None
)

# --------------------------------------------------------------------------------
# bot context typing
BT: typing.TypeAlias = ExtBot[None]
UD = typing.TypedDict('UD', {})
CD = typing.TypedDict('CD', {
    'menupage': typing.NotRequired['InlineMenuPage'],
})
BD = typing.TypedDict('BD', {})
CCT: typing.TypeAlias = CallbackContext[BT, UD, CD, BD]
CT = ContextTypes(CallbackContext, UD, CD, BD)

class ValidatedContext(typing.TypedDict):
    """ Extra keyword arguments for Telegram command handlers """
    user: User
    chat: Chat
    message: Message
    user_data: UD
    chat_data: CD
    bot_data: BD
    callback_data: str
    job_queue: JobQueue[CCT]

# --------------------------------------------------------------------------------
# SQL insert/update row typing
class ChatValues(typing.TypedDict):
    name: typing.NotRequired[str]
    type: typing.NotRequired[str]
    role: typing.NotRequired[int]
    active: typing.NotRequired[bool]

class ListenerValues(typing.TypedDict):
    name: typing.NotRequired[str]
    classname: typing.NotRequired[str]
    parameters: typing.NotRequired[str]
    active: typing.NotRequired[bool]

class SubscriptionValues(typing.TypedDict):
    active: typing.NotRequired[bool]


# --------------------------------------------------------------------------------
# SQL row
class RowLike(typing.Protocol):
    @property
    def _fields(self) -> tuple[str, ...]: ...
    def _asdict(self) -> dict[str, typing.Any]: ...
    def __getattr__(self, name: str) -> typing.Any: ...

class CustomTableRow:
    def __new__(cls, **kwargs) -> RowLike:
        _class = namedtuple('_CustomTableRow', kwargs.keys())
        instance = _class(**kwargs)
        return instance     # type: ignore

    def __getattr__(self, name: str) -> typing.Any:
        return self.__getattribute__(name)

# --------------------------------------------------------------------------------
# SQL definitions
class _ListenerTable(typing.Protocol):
    """ Specific source for receiving messages """
    __tablename__: str
    listener_id: sa.Column[int]
    name: sa.Column[str]
    classname: sa.Column[str]
    parameters: sa.Column[str]
    cronstring: sa.Column[str]
    active: sa.Column[bool]
    created: sa.Column[dt.datetime]
    updated: sa.Column[dt.datetime]
class ListenerTableRow(RowLike, typing.Protocol):
    """ Listener table row protocol """
    listener_id: int
    name: str
    classname: typing.Literal['FileSystemListener', 'SQLListener']
    parameters: str
    cronstring: str | None
    active: bool
    created: dt.datetime
    updated: dt.datetime

class _ChatTable(typing.Protocol):
    """ Telegram chat (group or private) """
    __tablename__: str
    chat_id: sa.Column[int]
    name: sa.Column[str]
    role: sa.Column[int]
    type: sa.Column[str]
    active: sa.Column[bool]
    created: sa.Column[dt.datetime]
    updated: sa.Column[dt.datetime]
class ChatTableRow(RowLike, typing.Protocol):
    """ Chat table row protocol """
    chat_id: int
    name: str
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
                name = sa.Column(mssql.VARCHAR(500), nullable=False)
                classname = sa.Column(mssql.VARCHAR(50), nullable=False)
                parameters = sa.Column(mssql.VARCHAR, nullable=False, server_default=sa.literal(r'{}'))
                cronstring = sa.Column(mssql.VARCHAR(100))
                active = sa.Column(mssql.BIT, nullable=False, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
            class _MSSQL_Chat:
                __tablename__ = 'chat'
                chat_id = sa.Column(mssql.BIGINT, primary_key=True, autoincrement=False)
                name = sa.Column(mssql.VARCHAR(500), nullable=False)
                role = sa.Column(mssql.SMALLINT, nullable=False, server_default=sa.literal(UserRole.BLOCKED.value))
                type = sa.Column(mssql.VARCHAR(10), nullable=False)
                active = sa.Column(mssql.BIT, nullable=False, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
            class _MSSQL_Subscription:
                __tablename__ = 'subscription'
                subscription_id = sa.Column(mssql.BIGINT, primary_key=True)
                chat_id = sa.Column(mssql.BIGINT, sa.ForeignKey(_MSSQL_Chat.chat_id), nullable=False)
                listener_id = sa.Column(mssql.INTEGER, sa.ForeignKey(_MSSQL_Listener.listener_id), nullable=False)
                active = sa.Column(mssql.BIT, nullable=False, server_default=sa.literal(True))
                created = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(mssql.DATETIME, nullable=False, server_default=sa.func.current_timestamp())

            return (_MSSQL_Listener, _MSSQL_Chat, _MSSQL_Subscription)

        # PostgreSQL definitions
        case ImplementedDialect.POSTGRESQL:
            class _PostgreSQL_Listener:
                __tablename__ = 'listener'
                listener_id = sa.Column(psql.INTEGER, primary_key=True, autoincrement="auto")
                name = sa.Column(psql.VARCHAR(500), nullable=False)
                classname = sa.Column(psql.VARCHAR(50), nullable=False)
                parameters = sa.Column(psql.VARCHAR, nullable=False, server_default=sa.literal(r'{}'))
                cronstring = sa.Column(psql.VARCHAR(100))
                active = sa.Column(psql.BOOLEAN, nullable=False, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
            class _PostgreSQL_Chat:
                __tablename__ = 'chat'
                chat_id = sa.Column(psql.BIGINT, primary_key=True, autoincrement=False)
                name = sa.Column(psql.VARCHAR(500), nullable=False)
                role = sa.Column(psql.SMALLINT, nullable=False, server_default=sa.literal(UserRole.BLOCKED.value))
                type = sa.Column(psql.VARCHAR(10), nullable=False)
                active = sa.Column(psql.BOOLEAN, nullable=False, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
            class _PostgreSQL_Subscription:
                __tablename__ = 'subscription'
                subscription_id = sa.Column(psql.BIGINT, primary_key=True)
                chat_id = sa.Column(psql.BIGINT, sa.ForeignKey(_PostgreSQL_Chat.chat_id), nullable=False)
                listener_id = sa.Column(psql.INTEGER, sa.ForeignKey(_PostgreSQL_Listener.listener_id), nullable=False)
                active = sa.Column(psql.BOOLEAN, nullable=False, server_default=sa.literal(True))
                created = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())
                updated = sa.Column(psql.TIMESTAMP, nullable=False, server_default=sa.func.current_timestamp())

            return (_PostgreSQL_Listener, _PostgreSQL_Chat, _PostgreSQL_Subscription)

        case _:
            raise NotImplementedError(f'No SQL definitions implemented for specified dialect `{dialect}`')
