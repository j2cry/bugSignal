import datetime as dt
import logging
import pytz
import sqlalchemy as sa
import sqlalchemy.orm as orm
import typing
# from contextlib import contextmanager
from functools import wraps
from telegram import Chat, User
from telegram.constants import ChatType

from model import UserRole, ListenerTable, ChatTable, SubscriptionTable, AnyTable, definitions_loader


# declare SQL table definitions
LISTENER: ListenerTable
CHAT: ChatTable
SUBSCRIPTION: SubscriptionTable


CHAT_KW = typing.TypedDict('CHAT_KW', {
    'title': typing.NotRequired[str],
    'type': typing.NotRequired[str],
    'active': typing.NotRequired[bool],
})
LISTENER_KW = typing.TypedDict('LISTENER_KW', {
    'title': typing.NotRequired[str],
    'classname': typing.NotRequired[str],
    'parameters': typing.NotRequired[str],
    'active': typing.NotRequired[bool],
})


class Database:
    """ Class for BugSignal SQL connection management """

    def __init__(self,
                 connection_string: str,
                 schema: str | None = None,
                 *,
                 logger: logging.Logger):
        self.__engine = sa.create_engine(connection_string)
        self.__logger = logger
        # load table definitions for used dialect
        global LISTENER, CHAT, SUBSCRIPTION
        try:
            _definitions = definitions_loader(self.__engine.dialect.name)
        except NotImplementedError as ex:
            self.__logger.error(str(ex))
            raise
        # map SQL structure
        metadata = sa.MetaData(schema)
        self.__registry = orm.registry(metadata=metadata)
        # self.__mappers = {}
        for _class in _definitions:
            # self.__mappers[_class] = self.__registry.map_declaratively(_class)
            self.__registry.map_declaratively(_class)
        # create schema NOTE does not work for MSSQL
        with self.__engine.begin() as session:
            if schema and not session.dialect.has_schema(session, schema):
                session.execute(sa.schema.CreateSchema(schema))
            # session.execute(sa.schema.CreateSchema(schema, if_not_exists=True))   # this does not work for MSSQL
        metadata.create_all(self.__engine)
        LISTENER, CHAT, SUBSCRIPTION = _definitions

    def dispose(self):
        """ Dispose registry and engine """
        self.__registry.dispose()
        self.__engine.dispose()

    def __insert_or_update(self, table: AnyTable, *keys: sa.ColumnExpressionArgument[bool], **values):
        """ Insert or update basic method """
        query = sa.select(table).where(*keys)
        self.__logger.debug(str(query))
        with self.__engine.begin() as session:
            if session.execute(query).first():
                values['updated'] = sa.func.current_timestamp()
                query = sa.update(table).where(*keys).values(**values)
            else:
                query = sa.insert(table).values(**values)
            self.__logger.debug(str(query))
            session.execute(query)
        self.__logger.info('Updated data for %s: %s', table.__tablename__, values)

    def chats(self, active_only: bool = False) -> typing.Sequence[sa.Row]:
    # def chats(self, active_only: bool = False) -> Sequence[Row[Tuple[ChatTable]]]:
        """ Request for all active chats """
        query = sa.select(CHAT).where(CHAT.active.in_((True, active_only))).order_by(CHAT.chat_id)
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return tuple(conn.execute(query).all())

    def set_chat(self, chat_id: int, **values: typing.Unpack[CHAT_KW]):
        """ Insert or update chat """
        self.__insert_or_update(CHAT, CHAT.chat_id == chat_id, **values)

    def listeners(self, active_only: bool = False) -> typing.Sequence[sa.Row]:
        """ Request for all listeners for specified chat """
        query = sa.select(LISTENER).where(LISTENER.active.in_((True, active_only))).order_by(LISTENER.listener_id)
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return tuple(conn.execute(query).all())

    def set_listener(self, listener_id: int, **values: typing.Unpack[LISTENER_KW]):
        """ Insert or update listener """
        self.__insert_or_update(LISTENER, LISTENER.listener_id == listener_id, **values)

    def subscriptions(self, chat_id: int) -> tuple[str, typing.Sequence[sa.Row]]:
        """"""
        with self.__engine.connect() as conn:
            query = sa.select(CHAT.title).where(CHAT.chat_id == chat_id)
            self.__logger.debug(str(query))
            chat = conn.execute(query).first()
            if chat is None:
                return '', ()
            query = sa.select(
                LISTENER.title,
                SUBSCRIPTION.subscription_id,
                sa.case((SUBSCRIPTION.chat_id == None, chat_id),
                        else_=SUBSCRIPTION.chat_id
                        ).label('chat_id'),
                LISTENER.listener_id,
                SUBSCRIPTION.active
            ).join(SUBSCRIPTION, isouter=True).where(
                LISTENER.active == True,
                sa.or_(SUBSCRIPTION.chat_id == chat_id,
                       SUBSCRIPTION.chat_id == None)
            ).order_by(LISTENER.title)

            self.__logger.debug(str(query))
            return chat.title, tuple(conn.execute(query).all())

    @typing.overload
    def set_subscription(self, subscription_id: int, **values: typing.Unpack[LISTENER_KW]) -> None: ...
    @typing.overload
    def set_subscription(self, chat_id: int, listener_id: int, **values: typing.Unpack[LISTENER_KW]) -> None: ...
    def set_subscription(self, *identifiers: typing.Tuple[int], **values: typing.Unpack[LISTENER_KW]) -> None:  # type: ignore
        """ Insert or update listener """
        match identifiers:
            case (int(subscription_id),):
                self.__insert_or_update(SUBSCRIPTION, SUBSCRIPTION.subscription_id == subscription_id, **values)
            case (int(chat_id), int(listener_id)):
                self.__insert_or_update(SUBSCRIPTION,
                                        SUBSCRIPTION.chat_id == chat_id,
                                        SUBSCRIPTION.listener_id == listener_id,
                                        chat_id=chat_id,
                                        listener_id=listener_id,
                                        **values)
