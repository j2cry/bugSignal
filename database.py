import logging
import sqlalchemy as sa
import sqlalchemy.orm as orm
import typing

from model import (
    UserRole,
    CustomTableRow,
    RowLike,
    ListenerTable, ListenerTableRow,
    ChatTable, ChatTableRow,
    SubscriptionTable, SubscriptionTableRow,
    AnyTable, AnyTableRow,
    definitions_loader,
    ChatValues,
    ListenerValues,
    SubscriptionValues,
)


# declare SQL table definitions
LISTENER: ListenerTable
CHAT: ChatTable
SUBSCRIPTION: SubscriptionTable


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

    def chats(self,
              active_only: bool = False,
              of_types: str | typing.Sequence[str] | None = None,
              exclude: int | typing.Sequence[int] | None = None,
              ) -> typing.Sequence[ChatTableRow]:
        """ Request for chats """
        clauses = [CHAT.active.in_((True, active_only))]
        if of_types is not None:
            clauses.append(CHAT.type.in_((of_types,) if isinstance(of_types, str) else of_types))
        if exclude is not None:
            clauses.append(CHAT.chat_id.not_in((exclude,) if isinstance(exclude, int) else exclude))
        query = sa.select(CHAT).where(*clauses).order_by(CHAT.chat_id)
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return tuple(conn.execute(query).all()) # type: ignore

    def set_chat(self, chat_id: int, **values: typing.Unpack[ChatValues]):
        """ Insert or update chat """
        self.__insert_or_update(CHAT, CHAT.chat_id == chat_id, chat_id=chat_id, **values)

    def listeners(self, active_only: bool = False) -> typing.Sequence[ListenerTableRow]:
        """ Request for all listeners for specified chat """
        query = sa.select(LISTENER).where(LISTENER.active.in_((True, active_only))).order_by(LISTENER.listener_id)
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return tuple(conn.execute(query).all()) # type: ignore

    def set_listener(self, listener_id: int, **values: typing.Unpack[ListenerValues]):
        """ Insert or update listener """
        self.__insert_or_update(LISTENER, LISTENER.listener_id == listener_id, **values)

    def subscriptions(self, chat_id: int) -> tuple[str, typing.Sequence[SubscriptionTableRow]]:
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
            ).join(SUBSCRIPTION,
                   onclause=sa.and_(SUBSCRIPTION.listener_id == LISTENER.listener_id,
                                    SUBSCRIPTION.chat_id == chat_id),
                   isouter=True,
            ).where(
                LISTENER.active == True
            ).order_by(LISTENER.title)

            self.__logger.debug(str(query))
            return chat.title, tuple(conn.execute(query).all()) # type: ignore

    @typing.overload
    def set_subscription(self, subscription_id: int, **values: typing.Unpack[SubscriptionValues]) -> None: ...
    @typing.overload
    def set_subscription(self, chat_id: int, listener_id: int, **values: typing.Unpack[SubscriptionValues]) -> None: ...
    def set_subscription(self, *identifiers: typing.Tuple[int], **values: typing.Unpack[SubscriptionValues]) -> None:  # type: ignore
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

    def subscribers(self, listener_id: int, *, active_only: bool = False) -> typing.Sequence[ChatTableRow]:
        """ Get listener subscribers """
        query = sa.select(CHAT).join(SUBSCRIPTION).where(SUBSCRIPTION.listener_id == listener_id,
                                                         SUBSCRIPTION.active.in_((True, active_only)),
                                                         CHAT.active.in_((True, active_only)))
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return conn.execute(query).all()    # type: ignore

    def chat(self, chat_id: int) -> ChatTableRow | None:
        """ Request for specified chat info """
        query = sa.select(CHAT).where(CHAT.chat_id == chat_id)
        self.__logger.debug(str(query))
        with self.__engine.connect() as conn:
            return conn.execute(query).first()  # type: ignore

    def roles(self, chat_id: int) -> tuple[str, typing.Sequence[RowLike]]:
        # get stored user roles
        if (stored_chat := self.chat(chat_id)) is None:
            raise ValueError('Incorrect stored chat')
        # build roles list
        user_roles = UserRole(stored_chat.role)
        return (stored_chat.title,
                tuple(CustomTableRow(chat_id=stored_chat.chat_id,
                                     title=role.name,
                                     role=user_roles ^ role,
                                     active=role in user_roles)
                      for role in UserRole)
                )
