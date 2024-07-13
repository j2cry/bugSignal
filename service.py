from __future__ import annotations
import logging
import math
import os
from contextlib import contextmanager
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatType
from telegram.error import BadRequest
from typing import Any, Callable, Concatenate, Coroutine, Unpack

from database import Database
from defaults import LogRecord
from model import (
    UserRole,
    Action,
    CallbackKey,
    CallbackContent,
    CallbackProtocol,
    Emoji,
    UD, CD, BD, BT, CCT, CT,
    ValidatedContext
)


def button(name: str, data: CallbackProtocol, **kwargs: Unpack[CallbackContent]) -> InlineKeyboardButton:
    hashkey = str(hash(str(kwargs)))
    data[hashkey] = kwargs
    return InlineKeyboardButton(name, callback_data=hashkey)


# def logcommand[S: BugSignalService, T](method: Callable[[S, Update, CCT], Coroutine[Any, Any, T]]):
#     """ Decorator for command logging """
#     def _wrapper(self: S, update: Update, context: CCT) -> Coroutine[Any, Any, T]:
#         # user_id = (update.effective_user or User(-1, 'Unknown', False)).id
#         # chat_id = (update.effective_chat or Chat(-1, 'PRIVATE')).id
#         variables = (
#             method.__name__,
#             *((user.id, user.name) if (user := update.effective_user) else (None, None)),
#             chat.id if (chat := update.effective_chat) else None,
#         )
#         self.logger.info('Received command `%s` from user=%s [%s] from chat=`%s`', *variables)
#         result = method(self, update, context)
#         return result
#     return _wrapper


def checkvars[S: BugSignalService, T, **KW](method: Callable[Concatenate[S, Update, CCT, KW], Coroutine[Any, Any, T]]):
    """ Decorator for checking general variables """
    def _wrapper(self: S,
                 update: Update,
                 context: CCT,
                 *args: KW.args,
                 **kwargs: KW.kwargs
                 ) -> Coroutine[Any, Any, T]:
        assert (user := update.effective_user) is not None, LogRecord('CHECKVARS', 'user').EFFECTIVE_IS_NONE
        assert (chat := update.effective_chat) is not None, LogRecord('CHECKVARS', 'chat').EFFECTIVE_IS_NONE
        assert (message := update.effective_message) is not None, LogRecord('CHECKVARS', 'message').EFFECTIVE_IS_NONE
        assert (user_data := context.user_data) is not None, LogRecord('CHECKVARS', 'User').DATA_IS_NONE
        assert (chat_data := context.chat_data) is not None, LogRecord('CHECKVARS', 'Chat').DATA_IS_NONE
        assert (bot_data := context.bot_data) is not None, LogRecord('CHECKVARS', 'Bot').DATA_IS_NONE
        kwargs.update(
            user=user,
            chat=chat,
            message=message,
            user_data=user_data,
            chat_data=chat_data,
            bot_data=bot_data,
        )
        return method(self, update, context, *args, **kwargs)
    return _wrapper


def allowed_for(roles: UserRole, admin: bool):
    """ Decorator for checking permissions

    Parameters
    ----------
    roles : UserRole
        A set of roles that are allowed to execute a command
    admin : bool
        Flag for allowing Telegram chat administrators to execute the command
    """
    def _permission_check[S: BugSignalService, T, **KW](method: Callable[Concatenate[S, Update, CCT, KW], Coroutine[Any, Any, T]]):
        async def _empty_handler(self: S, update: Update, context: CCT, *args: KW.args, **kwargs: KW.kwargs) -> T: ...
        async def _wrapper(self: S, update: Update, context: CCT, *args: KW.args, **kwargs: KW.kwargs) -> T:
            assert (user := update.effective_user) is not None, LogRecord('PERMISSON', 'user').EFFECTIVE_IS_NONE
            assert (chat := update.effective_chat) is not None, LogRecord('PERMISSON', 'chat').EFFECTIVE_IS_NONE
            assert (message := update.effective_message) is not None, LogRecord('PERMISSION', 'message').EFFECTIVE_IS_NONE
            # callback answer
            if (callback_query := update.callback_query) is not None:
                await callback_query.answer('jap-jap-jap')
            # get stored user role
            user_roles = (set(UserRole(stored_chat.role))
                          if (stored_chat := self.db.chat(user.id)) is not None
                          else set())
            # check permissions
            if not user_roles.intersection(roles) and (not admin
                                                       or chat.type == ChatType.PRIVATE
                                                       or user not in await chat.get_administrators()):
                self.logger.warning(LogRecord(user.id, 'menu').UNSECURE_OPERATION)
                await message.reply_text(f'{Emoji.DECLINED} Command rejected for {user.name}.')
                return await _empty_handler(self, update, context, *args, **kwargs)
            return await method(self, update, context, *args, **kwargs)
        return _wrapper
    return _permission_check


class BugSignalService:
    def __init__(self, logger: logging.Logger):
        # load credentials
        os.environ.get('BUGSIGNAL_TOKEN')
        self.logger = logger
        self.db = Database(os.environ['BUGSIGNAL_SQL_CONNECTION_STRING'],
                           schema=os.environ['BUGSIGNAL_SQL_CONNECTION_SCHEMA'],
                           logger=logger)

    @contextmanager
    def run(self, *args, **kwargs):
        yield self
        self.db.dispose()

    @checkvars
    async def start(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Remember chat id """
        self.db.set_chat(kwargs['chat'].id,
                         title=kwargs['chat'].effective_name or str(kwargs['chat'].id),
                         type=kwargs['chat'].type)
        await kwargs['message'].reply_text(f'{Emoji.ENABLED} Current chat information saved.')  # NOTE hardcoded message

    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Show menu """
        self.__drop_context(context, CD)
        chat = kwargs['chat']
        message = kwargs['message']
        chat_data = kwargs['chat_data']
        # build menu
        callback = {}
        menu = InlineKeyboardMarkup(((
            button('Chats', callback, action=Action.CHATS),
            button('Listeners', callback, action=Action.LISTENERS),
        ), (
            button('Subscriptions', callback, action=Action.SUBSCRIPTIONS),
        ), (
            button('Close', callback, action=Action.CLOSE),
        ),))
        chat_data['callback'] = callback
        try:
            await message.edit_text('bugSignal admin panel', reply_markup=menu)
        except BadRequest:
            await context.bot.send_message(chat.id, 'bugSignal admin panel', reply_markup=menu)

    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def callback(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Parse callback data """
        assert (callback_query := update.callback_query) is not None, LogRecord.CALLBACK_IS_NONE
        await callback_query.answer('jap-jap-jap')
        chat_data = kwargs['chat_data']
        # get callback saved data
        data = chat_data.get('callback', {}).get(callback_query.data)
        match data:
            case {CallbackKey.ACTION: Action.MENU}:
                return await self.menu(update, context, **kwargs)
            case {CallbackKey.ACTION: Action.CHATS}:
                # Show Chats list
                chat_data.update(
                    back_action=Action.MENU,
                    default_button_action=Action.SWITCH,
                    menulist=self.db.chats(),
                    menutext='Available chats',
                    marker=True,
                    page=0,
                )
            case {CallbackKey.ACTION: Action.LISTENERS, CallbackKey.CHAT_ID: int(chat_id)}:
                # show listeners' subscriptions for specified chat
                title, subscriptions = self.db.subscriptions(chat_id)
                chat_data.update(
                    back_action=Action.SUBSCRIPTIONS,
                    default_button_action=Action.SWITCH,
                    menulist=subscriptions,
                    menutext=f'Subscriptions for chat {title}',
                    marker=True,
                    page=0,
                )
            case {CallbackKey.ACTION: Action.LISTENERS}:
                # show Listeners list
                chat_data.update(
                    back_action=Action.MENU,
                    default_button_action=Action.SWITCH,
                    menulist=self.db.listeners(),
                    menutext='Available listeners',
                    marker=True,
                    page=0,
                )
            case {CallbackKey.ACTION: Action.SUBSCRIPTIONS}:
                # show Subscriptions list
                chat_data.update(
                    back_action=Action.MENU,
                    default_button_action=Action.LISTENERS,
                    menulist=self.db.chats(active_only=True),
                    menutext='Choose a chat to manage subscriptions',
                    marker=False,
                    page=0,
                )
            # Update active state
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.LISTENER_ID: int(listener_id),
                  CallbackKey.ACTIVE: bool() | None as active,
                  }:
                # insert/update Subscription
                self.logger.debug('Insert/update SUBSCRIPTION')
                self.db.set_subscription(chat_id, listener_id, active=not active)
                _, chat_data['menulist'] = self.db.subscriptions(chat_id)
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.ACTIVE: bool(active)}:
                # update Chat activity
                self.logger.debug('Enable/disable CHAT')
                self.db.set_chat(chat_id, active=not active)
                chat_data['menulist'] = self.db.chats()
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.LISTENER_ID: int(listener_id),
                  CallbackKey.ACTIVE: bool(active)}:
                # update Chat activity
                self.logger.debug('Enable/disable LISTENER')
                self.db.set_listener(listener_id, active=not active)
                chat_data['menulist'] = self.db.listeners()
            # basic menu commands
            case {CallbackKey.ACTION: Action.PREVPAGE}:
                chat_data['page'] -= 1
            case {CallbackKey.ACTION: Action.NEXTPAGE}:
                chat_data['page'] += 1
            case {CallbackKey.ACTION: Action.CLOSE}:
                return await self.__menuclose(update, context, **kwargs)
            case _:
                await kwargs['message'].edit_text('Something is wrong...', reply_markup=None)
                self.__drop_context(context, CD)
                return
        await self.__menupage(update, context, **kwargs)

    async def __menupage(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Build next menu page """
        chat_data = kwargs['chat_data']
        message = kwargs['message']
        # check page overflow
        ITEMS_PER_PAGE = 4
        MAXPAGE = math.ceil(len(chat_data['menulist']) / ITEMS_PER_PAGE) - 1
        if MAXPAGE == 0 and message.text == chat_data['menutext']:
            chat_data['page'] = 0
            return
        elif chat_data['page'] < 0:
            chat_data['page'] = MAXPAGE
        elif chat_data['page'] > MAXPAGE:
            chat_data['page'] = 0
        # build inline keyboard
        start = chat_data['page'] * ITEMS_PER_PAGE
        end = (chat_data['page'] + 1) * ITEMS_PER_PAGE
        buttons = []
        callback = {}
        default_button_action = chat_data.pop('default_button_action', None)
        for item in chat_data['menulist'][start:end]:
            data = CallbackContent(action=default_button_action)
            if chat_data['marker']:
                data[CallbackKey.ACTIVE.value] = item.active
                mark = (Emoji.ENABLED if getattr(item, 'active', False) else Emoji.DISABLED)
            else:
                mark = ''
            if CallbackKey.CHAT_ID in item._fields:
                data[CallbackKey.CHAT_ID.value] = item.chat_id
            if CallbackKey.LISTENER_ID in item._fields:
                data[CallbackKey.LISTENER_ID.value] = item.listener_id
            buttons.append([button(f'{mark}{item.title}', callback, **data)])
        buttons.extend((
            (button('<<', callback, action=Action.PREVPAGE),
             button('>>', callback, action=Action.NEXTPAGE)),
            (button('Back', callback, action=chat_data['back_action']),),
            (button('Close', callback, action=Action.CLOSE),)
        ))
        chat_data['callback'] = callback
        await message.edit_text(chat_data['menutext'], reply_markup=InlineKeyboardMarkup(buttons))

    async def __menuclose(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Close menu """
        await kwargs['message'].edit_text('Menu closed', reply_markup=None)
        # await message.delete()
        # release chat data
        self.__drop_context(context, CD)

    @staticmethod
    def __drop_context[DataSpec: UD | CD | BT](context: CCT, dtype: type[DataSpec]):
        """ Release specified context """
        if dtype is UD:
            assert (data := context.user_data) is not None, LogRecord('RELEASE', 'User').DATA_IS_NONE
            ...
        elif dtype is CD:
            assert (data := context.chat_data) is not None, LogRecord('RELEASE', 'Chat').DATA_IS_NONE
            data.update(
                back_action=None,
                menulist=(),
                menutext='',
                marker=False,
                page=0,
                callback={},
                default_button_action=None,
            )
        elif dtype is BT:
            assert (data := context.bot_data) is not None, LogRecord('RELEASE', 'Bot').DATA_IS_NONE
            ...

    async def _onerror(self, update: object, context: CCT):
        """ Error handler """
        self.logger.error(str(context.error))




    # async def message(self, update: Update, context: CallbackContext):
    #     logging.debug('start command received')
    #     bp = 1


