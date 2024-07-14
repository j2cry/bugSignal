from __future__ import annotations
import logging
import math
import os
import random
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
    Emoji,
    MenuPattern,
    UD, CD, BD, BT, CCT, CT,
    ValidatedContext
)


def button(name: str,
           chat_data: CD,
           **kwargs: Unpack[CallbackContent],
           ) -> InlineKeyboardButton:
    hashkey = str(hash(str(kwargs)))
    chat_data['callback'][hashkey] = kwargs
    return InlineKeyboardButton(name, callback_data=f'{chat_data["menupattern"]}{hashkey}')


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


def checkvars[S: BugSignalService, T, **KW](
        method: Callable[Concatenate[S, Update, CCT, KW], Coroutine[Any, Any, T]]
        ) -> Callable[[S, Update, CCT], Coroutine[Any, Any, T]]:
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
            administrators = ({_admin.user for _admin in await chat.get_administrators()}
                              if chat.type != ChatType.PRIVATE
                              else set())
            if user_roles.intersection(roles) or (admin and chat.type != ChatType.PRIVATE and user in administrators):
                return await method(self, update, context, *args, **kwargs)
            # restrict command execution
            self.logger.warning(LogRecord(user.id, 'menu').UNSECURE_OPERATION)
            await message.reply_text(f'{Emoji.DECLINED} Command rejected for {user.name}.')
            return await _empty_handler(self, update, context, *args, **kwargs)
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

    # --------------------------------------------------------------------------------
    # common command handlers
    @checkvars
    async def start(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Remember chat id """
        self.db.set_chat(kwargs['chat'].id,
                         title=kwargs['chat'].username or kwargs['chat'].effective_name or str(kwargs['chat'].id),
                         type=kwargs['chat'].type)
        await kwargs['message'].reply_text(f'{Emoji.ENABLED} Current chat information saved.')  # NOTE hardcoded message

    @checkvars
    async def fox(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Send fox emoji """
        privates = tuple(chat.chat_id for chat in self.db.chats(active_only=True, of_types=ChatType.PRIVATE)
                         if chat.chat_id != kwargs['user'].id)
        try:
            chat_id = int(context.args[0])   # type: ignore
            if chat_id not in privates:
                raise ValueError()
        except (IndexError, ValueError):
            chat_id = random.choice(privates)
        self.logger.info('%s sent a fox to %s', kwargs['user'].name, chat_id)
        await context.bot.send_message(chat_id, '🦊')

    # --------------------------------------------------------------------------------
    # Inline main menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def main_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Show main menu """
        chat_data = kwargs['chat_data']
        # get callback saved data
        data, hashkey = self.__get_callback_query_data(update, chat_data)
        # first or back menu open
        if (data or {}).get(CallbackKey.ACTION) in {Action.MENU, None}:
            # check that menu is opened FIXME
            # if await self.__menu_is_opened(update, context):
            #     return
            # build menu
            self.__drop_context(context, CD)
            chat_data['menupattern'] = MenuPattern.MAIN
            menu = InlineKeyboardMarkup(((
                button('Chats', chat_data, action=Action.CHATS),
                button('Listeners', chat_data, action=Action.LISTENERS),
            ), (
                button('Subscriptions', chat_data, action=Action.SUBSCRIPTIONS),
            ), (
                button('Close', chat_data, action=Action.CLOSE),
            ),))
            try:
                await kwargs['message'].edit_text('bugSignal admin panel', reply_markup=menu)
            except BadRequest:
                await context.bot.send_message(kwargs['chat'].id, 'bugSignal admin panel', reply_markup=menu)
            return
        # match inline query callback
        match data:
            case {CallbackKey.ACTION: Action.MENU}:
                return await self.main_menu(update, context)
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

    # --------------------------------------------------------------------------------
    # Inline grant permissions menu
    @checkvars
    async def grant_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Show grant permissions menu

        This was implemented as demo of menu building
        """
        # callback answer NOTE DEBUG
        if (callback_query := update.callback_query) is not None:
            await callback_query.answer('jap-jap-jap')
        chat_data = kwargs['chat_data']
        # get callback saved data
        data, hashkey = self.__get_callback_query_data(update, chat_data)
        # first or back menu open
        if (data or {}).get(CallbackKey.ACTION) in {Action.MENU, None}:
            # check that menu is opened FIXME
            # if await self.__menu_is_opened(update, context):
            #     return
            # build menu
            self.__drop_context(context, CD)
            chat_data['menupattern'] = MenuPattern.GRANT
            chat_data.update(
                back_action=Action.CLOSE,
                default_button_action=Action.ROLES,
                menulist=self.db.chats(active_only=True, of_types=ChatType.PRIVATE),
                menutext='Available private chats',
                page=0,
            )
            return await self.__menupage(update, context, with_back_button=False, **kwargs)
        # match inline query callback
        match data:
            case {CallbackKey.ACTION: Action.ROLES,
                  CallbackKey.CHAT_ID: int(chat_id)}:
                username, roles = self.db.roles(chat_id)
                chat_data.update(
                    back_action=Action.MENU,
                    default_button_action=Action.SWITCH,
                    menulist=roles,
                    menutext=f'User roles for {username}',
                    marker=True,
                    page=0,
                )
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.ROLE: UserRole(role)}:
                # update role
                self.logger.debug('Add/remove PRIVATE role')
                self.db.set_chat(chat_id, role=role)
                _, roles = self.db.roles(chat_id)
                chat_data['menulist'] = roles

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

    # --------------------------------------------------------------------------------
    # common menu methods
    @staticmethod
    def __get_callback_query_data(update: Update, chat_data: CD) -> tuple[CallbackContent | None, str | None]:
        """ Extract and validate inline callback query data """
        if (callback_query := update.callback_query) is not None:
            callback_query_data = (callback_query.data or '').replace(chat_data.get('menupattern', ''), '')
            return chat_data.get('callback', {}).get(callback_query_data), callback_query_data
        return None, None

    @checkvars
    async def __menu_is_opened(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]) -> bool:
        """ Check if menu is already opened """
        message = 'One menu is already opened. Close it before opening another one.'
        if _is_opened := kwargs['chat_data'].get('menupattern', MenuPattern.EMPTY) != MenuPattern.EMPTY:
            try:
                if update.effective_message is None:
                    raise BadRequest('Effective message is None')
                await update.effective_message.reply_text(message)
            except BadRequest:
                await context.bot.send_message(kwargs['chat'].id, message)
        return _is_opened

    async def __menupage(self,
                         update: Update,
                         context: CCT,
                         with_back_button: bool = True,
                         **kwargs: Unpack[ValidatedContext]
                         ):
        """ Build next menu page """
        chat_data = kwargs['chat_data']
        message = kwargs['message']
        # check page overflow
        ITEMS_PER_PAGE = 4
        MAXPAGE = math.ceil(len(chat_data['menulist']) / ITEMS_PER_PAGE) - 1
        # if MAXPAGE == 0 and message.text == chat_data['menutext']:
        #     chat_data['page'] = 0
        #     return
        if chat_data['page'] < 0:
            chat_data['page'] = MAXPAGE
        elif chat_data['page'] > MAXPAGE:
            chat_data['page'] = 0
        # build inline keyboard
        start = chat_data['page'] * ITEMS_PER_PAGE
        end = (chat_data['page'] + 1) * ITEMS_PER_PAGE
        buttons = []
        default_button_action = chat_data.get('default_button_action', None)
        for item in chat_data['menulist'][start:end]:
            # fill callback content
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
            if CallbackKey.ROLE in item._fields:
                data[CallbackKey.ROLE.value] = item.role
            buttons.append([button(f'{mark}{item.title}', chat_data, **data)])
        buttons.extend((
            (button('<<', chat_data, action=Action.PREVPAGE),
             button('>>', chat_data, action=Action.NEXTPAGE)),
            (button('Back', chat_data, action=chat_data['back_action']),) if with_back_button else (),
            (button('Close', chat_data, action=Action.CLOSE),)
        ))
        markup = InlineKeyboardMarkup(buttons)
        if MAXPAGE == 0 and message.text == chat_data['menutext'] and message.reply_markup == markup:
            chat_data['page'] = 0
            return
        try:
            await message.edit_text(chat_data['menutext'], reply_markup=markup)
        except BadRequest:
            await context.bot.send_message(kwargs['chat'].id,
                                           'bugSignal GRANT panel',
                                           reply_markup=markup)

    async def __menuclose(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Close menu """
        await kwargs['message'].edit_text('Menu closed', reply_markup=None)
        # await message.delete()
        # release chat data
        self.__drop_context(context, CD)

    # --------------------------------------------------------------------------------
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
                menupattern=MenuPattern.EMPTY,
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

    # --------------------------------------------------------------------------------
    async def _onerror(self, update: object, context: CCT):
        """ Error handler """
        self.logger.error(str(context.error))




    # async def message(self, update: Update, context: CallbackContext):
    #     logging.debug('start command received')
    #     bp = 1


