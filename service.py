from __future__ import annotations
import json
import logging
import math
import os
import typing as t
from contextlib import contextmanager
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatType
from telegram.error import BadRequest

from database import Database
from defaults import LogRecord
from model import (
    UserRole,
    Action,
    CallbackData,
    Emoji,
    UD, CD, BT,
    CCT,
    CT,
)


def button(name: str, **kwargs) -> InlineKeyboardButton:
    serialized = json.dumps({CallbackData[k.upper()]: v for k, v in kwargs.items()}).replace(' ', '')
    return InlineKeyboardButton(name, callback_data=serialized)


# def logcommand[S: BugSignalService, T](method: t.Callable[[S, Update, CCT], t.Coroutine[t.Any, t.Any, T]]):
#     """ Decorator for command logging """
#     def _wrapper(self: S, update: Update, context: CCT) -> t.Coroutine[t.Any, t.Any, T]:
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

    async def start(self, update: Update, context: CCT):
        """ Remember chat id """
        assert (chat := update.effective_chat) is not None, LogRecord('START', 'chat').EFFECTIVE_IS_NONE
        assert (message := update.effective_message) is not None, LogRecord('MENU', 'message').EFFECTIVE_IS_NONE
        self.db.set_chat(chat.id, title=chat.effective_name or str(chat.id), type=chat.type)
        await message.reply_text(f'{Emoji.ENABLED} Current chat information saved.')  # NOTE hardcoded message

    # TODO user role checking decorator: or make it dynamically?
    async def menu(self, update: Update, context: CCT):
        """ Show menu """
        assert (chat := update.effective_chat) is not None, LogRecord('MENU', 'chat').EFFECTIVE_IS_NONE
        assert (user := update.effective_user) is not None, LogRecord('MENU', 'user').EFFECTIVE_IS_NONE
        assert (message := update.effective_message) is not None, LogRecord('MENU', 'message').EFFECTIVE_IS_NONE
        # discard opening menu
        if chat.type != ChatType.PRIVATE:
            self.logger.warning(LogRecord(user.id, 'menu').UNSECURE_OPERATION)
            await message.reply_text(f'{Emoji.DECLINED} Opening menu is allowed only in private chat.')    # NOTE hardcoded message
            return
        # build menu
        menu = InlineKeyboardMarkup(((
            button('Chats', action=Action.CHATS),
            button('Listeners', action=Action.LISTENERS),
        ), (
            button('Subscriptions', action=Action.SUBSCRIPTIONS),
        ), (
            button('Close', action=Action.CLOSE),
        ),))
        try:
            await message.edit_text('bugSignal admin panel', reply_markup=menu)
        except BadRequest:
            await context.bot.send_message(chat.id, 'bugSignal admin panel', reply_markup=menu)

    async def callback(self, update: Update, context: CCT):
        """ Parse callback data """
        assert (user := update.effective_user) is not None, LogRecord('CALLBACK', 'user').EFFECTIVE_IS_NONE
        assert (message := update.effective_message) is not None, LogRecord('CALLBACK', 'message').EFFECTIVE_IS_NONE
        assert update.callback_query is not None, LogRecord.CALLBACK_IS_NONE
        assert (chat_data := context.chat_data) is not None, LogRecord('CALLBACK', 'Chat').DATA_IS_NONE
        await update.callback_query.answer('jap-jap-jap')
        # deserialize
        data = {int(k): v for k, v in json.loads(update.callback_query.data or '{}').items()}
        match data:
            case {CallbackData.ACTION: Action.MENU}:
                return await self.menu(update, context)
            case {CallbackData.ACTION: Action.CHATS}:
                # Show Chats list
                chat_data.update(
                    back=Action.MENU,
                    menulist=self.db.chats(),
                    menutext='Available chats',
                    marker=True,
                    action=Action.SWITCH,
                    page=0,
                )
            case {CallbackData.ACTION: Action.LISTENERS, CallbackData.CHAT_ID: int(chat_id)}:
                # show listeners' subscriptions for specified chat
                title, subscriptions = self.db.subscriptions(chat_id)
                chat_data.update(
                    back=Action.SUBSCRIPTIONS,
                    menulist=subscriptions,
                    menutext=f'Subscriptions for chat {title}',
                    marker=True,
                    action=Action.SWITCH,
                    page=0,
                )
            case {CallbackData.ACTION: Action.LISTENERS}:
                # show Listeners list
                chat_data.update(
                    back=Action.MENU,
                    menulist=self.db.listeners(),
                    menutext='Available listeners',
                    marker=True,
                    action=Action.SWITCH,
                    page=0,
                )
            case {CallbackData.ACTION: Action.SUBSCRIPTIONS}:
                # show Subscriptions list
                chat_data.update(
                    back=Action.MENU,
                    menulist=self.db.chats(active_only=True),
                    menutext='Choose a chat to manage subscriptions',
                    marker=False,
                    action=Action.LISTENERS,
                    page=0,
                )
            # Update active state
            case {CallbackData.ACTION: Action.SWITCH,
                  CallbackData.CHAT_ID: int(chat_id),
                  CallbackData.LISTENER_ID: int(listener_id),
                  CallbackData.ACTIVE: bool() | None as active,
                  }:
                # insert/update Subscription
                self.logger.debug('Insert/update SUBSCRIPTION')
                self.db.set_subscription(chat_id, listener_id, active=not active)
                _, chat_data['menulist'] = self.db.subscriptions(chat_id)
            case {CallbackData.ACTION: Action.SWITCH,
                  CallbackData.CHAT_ID: int(chat_id),
                  CallbackData.ACTIVE: bool(active)}:
                # update Chat activity
                self.logger.debug('Enable/disable CHAT')
                self.db.set_chat(chat_id, active=not active)
                chat_data['menulist'] = self.db.chats()
            case {CallbackData.ACTION: Action.SWITCH,
                  CallbackData.LISTENER_ID: int(listener_id),
                  CallbackData.ACTIVE: bool(active)}:
                # update Chat activity
                self.logger.debug('Enable/disable LISTENER')
                self.db.set_listener(listener_id, active=not active)
                chat_data['menulist'] = self.db.listeners()
            # basic menu commands
            case {CallbackData.ACTION: Action.PREVPAGE}:
                chat_data['page'] -= 1
            case {CallbackData.ACTION: Action.NEXTPAGE}:
                chat_data['page'] += 1
            case {CallbackData.ACTION: Action.CLOSE}:
                return await self.menuclose(update, context)
            case _:
                await message.edit_text('Something is wrong...', reply_markup=None)
                self.__drop_context(context, CD)
                return
        await self.menupage(update, context)

    async def menupage(self, update: Update, context: CCT):
        """ Build next menu page """
        assert (chat_data := context.chat_data) is not None, LogRecord('MENUPAGE', 'Chat').DATA_IS_NONE
        assert (message := update.effective_message) is not None, LogRecord('CALLBACK', 'message').EFFECTIVE_IS_NONE
        # check page overflow
        ITEMS_PER_PAGE = 4
        max_pages = math.ceil(len(chat_data['menulist']) / ITEMS_PER_PAGE)
        if chat_data['page'] < 0:
            chat_data['page'] = max_pages - 1
        elif chat_data['page'] >= max_pages:
            chat_data['page'] = 0
        # build inline keyboard
        start = chat_data['page'] * ITEMS_PER_PAGE
        end = (chat_data['page'] + 1) * ITEMS_PER_PAGE
        buttons = []
        for item in chat_data['menulist'][start:end]:
            data = dict(action=chat_data['action'])
            if chat_data.get('marker'):
                data['active'] = item.active
                mark = (Emoji.ENABLED if getattr(item, 'active', False) else Emoji.DISABLED)
            else:
                mark = ''
            if 'chat_id' in item._fields:
                data['chat_id'] = item.chat_id
            if 'listener_id' in item._fields:
                data['listener_id'] = item.listener_id
            buttons.append([button(f'{mark}{item.title}', **data)])
        buttons.extend((
            (button('<<', action=Action.PREVPAGE), button('>>', action=Action.NEXTPAGE)),
            (button('Back', action=chat_data['back']),),
            (button('Close', action=Action.CLOSE),)
        ))
        await message.edit_text(chat_data['menutext'], reply_markup=InlineKeyboardMarkup(buttons))

    async def menuclose(self, update: Update, context: CCT):
        """ Close menu """
        assert (message := update.effective_message) is not None, LogRecord('MENU', 'message').EFFECTIVE_IS_NONE
        await message.edit_text('Menu closed', reply_markup=None)
        # await message.delete()
        # release chat data
        self.__drop_context(context, CD)

    @staticmethod
    def __drop_context[DataSpec: UD | CD | BT](context: CCT, dtype: type[DataSpec]):
        if dtype is UD:
            assert context.user_data is not None, LogRecord('RELEASE', 'User').DATA_IS_NONE
            # context.user_data
            ...
        elif dtype is CD:
            assert context.chat_data is not None, LogRecord('RELEASE', 'Chat').DATA_IS_NONE
            context.chat_data['action'] = Action.CLOSE
            context.chat_data['menulist'] = tuple()
            context.chat_data['menutext'] = ''
            context.chat_data['back'] = Action.CLOSE
            context.chat_data['page'] = 0
        elif dtype is BT:
            assert context.bot_data is not None, LogRecord('RELEASE', 'Bot').DATA_IS_NONE
            # context.bot_data
            ...

    async def _onerror(self, update: object, context: CCT):
        """ Error handler """
        self.logger.error(str(context.error))




    # async def message(self, update: Update, context: CallbackContext):
    #     logging.debug('start command received')
    #     bp = 1


