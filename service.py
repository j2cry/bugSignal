from __future__ import annotations
import asyncio
import datetime as dt
import logging
import os
import random
import signal
from contextlib import contextmanager
from telegram import Update
from telegram.ext import Job
from telegram.constants import ChatType
from telegram.error import BadRequest
from typing import Any, Callable, Concatenate, Coroutine, Sequence, Unpack

from database import Database
from defaults import (
    Configuration,
    Emoji,
    Environ,
    Notification,
    DEFAULT
)
from menupage import (
    Action,
    Button,
    CallbackKey,
    InlineMenuPage,
    MenuError,
    MenuPattern,
)
from model import (
    UserRole,
    CustomTableRow,
    # UD, CD, BD, BT, CCT, CT,
    CCT,
    ValidatedContext
)


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
        assert (user := update.effective_user) is not None, f'[checkvars] effective_user is None'
        assert (chat := update.effective_chat) is not None, f'[checkvars] effective_chat is None'
        assert (message := update.effective_message) is not None, f'[checkvars] effective_message is None'
        assert (user_data := context.user_data) is not None, f'[checkvars] user_data is None'
        assert (chat_data := context.chat_data) is not None, f'[checkvars] chat_data is None'
        assert (bot_data := context.bot_data) is not None, f'[checkvars] bot_data is None'
        assert (job_queue := context.job_queue) is not None, f'[checkvars] JobQueue is None'
        if (query := update.callback_query) is not None:
            callback_data = query.data or ''
        else:
            callback_data = ''
        kwargs.update(
            user=user,
            chat=chat,
            message=message,
            user_data=user_data,
            chat_data=chat_data,
            bot_data=bot_data,
            callback_data=callback_data,
            job_queue=job_queue,
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
            assert (user := update.effective_user) is not None, f'[permission_check] effective_user is None'
            assert (chat := update.effective_chat) is not None, f'[permission_check] effective_chat is None'
            assert (message := update.effective_message) is not None, f'[permission_check] effective_message is None'
            # callback answer
            if (callback_query := update.callback_query) is not None:
                await callback_query.answer(Notification.MESSAGE_QUERY_ANSWER)
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
            self.logger.warning(Notification.LOG_COMMAND_REJECTED % (user.name, user.id))
            await message.reply_text(Notification.MESSAGE_COMMAND_REJECTED % user.name)
            return await _empty_handler(self, update, context, *args, **kwargs)
        return _wrapper
    return _permission_check


class BugSignalService:
    def __init__(self, logger: logging.Logger, config: Configuration = DEFAULT):
        # load credentials
        os.environ.get('BUGSIGNAL_TOKEN')
        self.logger = logger
        self.db = Database(os.environ[Environ.SQL_CONNECTION_STRING],
                           schema=config['sqlschema'],
                           logger=logger)
        self.config = config

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
        await kwargs['message'].reply_text(Notification.MESSAGE_CHAT_INFORMATION_SAVED)

    @checkvars
    async def fox(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Send fox emoji """
        chat_id = self.__get_random_user(context.args, kwargs['user'].id)
        self.logger.info(Notification.LOG_SENT_FROM_TO % (kwargs['user'].name, chat_id))
        await context.bot.send_message(chat_id, Emoji.FOX)

    @checkvars
    @allowed_for(UserRole.NECROMANCER, admin=False)
    async def zombie(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Send zombie emoji """
        chat_id = self.__get_random_user(context.args, kwargs['user'].id)
        self.logger.info(Notification.LOG_SENT_FROM_TO % (kwargs['user'].name, chat_id))
        await context.bot.send_message(chat_id, Emoji.ZOMBIE)

    @checkvars
    @allowed_for(UserRole.ACTIVE, admin=False)
    async def check(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Force check all listeners for updates """
        # TODO сделать параметризацию?
        message = await kwargs['message'].reply_text(Notification.MESSAGE_CHECK_LISTENERS)
        tasks = []
        for job in kwargs['job_queue'].jobs():
            if (job.name or '').startswith('listener'):
                tasks.append(asyncio.create_task(job.run(context.application)))
                # await job.run(context.application)
        if tasks:
            await asyncio.wait(tasks, timeout=self.config['timeout']['common'])
        await message.reply_text(Notification.MESSAGE_DONE)

    @checkvars
    @allowed_for(UserRole.ACTIVE, admin=False)
    async def jobstate(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Get current bugSignal state """
        def _jobformat(job: Job[CCT]):
            """ Return formatted job schedule """
            next_t = job.next_t.replace(microsecond=0, tzinfo=None) if job.next_t else None
            return f'{getattr(job.data, "name", job.name)} {next_t}'
        TIMESTAMP = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        STATE = f'[{TIMESTAMP}] Self state:\n' + '\n'.join(map(_jobformat, kwargs['job_queue'].jobs()))
        await kwargs['message'].reply_text(STATE)

    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def actualize(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Actualize listener jobs """
        # TODO

    @checkvars
    @allowed_for(UserRole.MASTER, admin=False)
    async def shutdown(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Get current bugSignal state """
        self.logger.info(Notification.LOG_SHUTDOWN, kwargs['user'].name, kwargs['user'].id)
        await kwargs['message'].reply_text(Notification.MESSAGE_SHUTDOWN)
        kwargs['job_queue'].run_once(self._onclose, when=self.config['timeout']['close'])

    # --------------------------------------------------------------------------------
    # Common inline menu
    @checkvars
    async def __menu_refresh(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Refresh menu page """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        markup = menupage.markup
        if kwargs['message'].text == menupage.title and kwargs['message'].reply_markup == markup:
            return
        try:
            await kwargs['message'].edit_text(menupage.title, reply_markup=markup)
        except BadRequest:
            await context.bot.send_message(kwargs['chat'].id, menupage.title, reply_markup=markup)

    @checkvars
    async def __menu_commons(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle common inline menu callbacks: DO NOT USE AS DIRECT COMMAND HANDLER """
        chat_data = kwargs['chat_data']
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        # match inline query callback
        content = menupage.content(kwargs['callback_data'])
        match content:
            # ----------------------------------------
            # open next page
            case {CallbackKey.ACTION: Action.PREVPAGE}:
                menupage.page -= 1
            # open previous page
            case {CallbackKey.ACTION: Action.NEXTPAGE}:
                menupage.page += 1
            # open previous menu
            case {CallbackKey.ACTION: Action.BACK} if menupage.previous is not None:
                menupage = menupage.previous
                chat_data['menupage'] = menupage
            # close menu
            case {CallbackKey.ACTION: Action.CLOSE}:
                chat_data.pop('menupage')
                return await kwargs['message'].edit_text(Notification.MESSAGE_MENU_CLOSED, reply_markup=None)
            # already opened
            case {CallbackKey.ACTION: None}:
                return await kwargs['message'].reply_text(Notification.MESSAGE_MENU_OPENED)
            # unknown content
            case _:
                raise MenuError(Notification.ERROR_MENU_CALLBACK)
        # refresh menu
        await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # Inline main menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def main_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Show main menu """
        chat_data = kwargs['chat_data']
        # first or back open menu
        if (menupage := chat_data.get('menupage')) is None:
            if kwargs['callback_data']:
                raise MenuError(Notification.ERROR_MENU_PAGE)
            # build menu
            menupage = InlineMenuPage(
                pattern=MenuPattern.MAIN,
                title='bugSignal admin panel',
                items=(CustomTableRow(title='Chats',
                                      action=Action.CHATS,
                                      pattern=MenuPattern.CHATS),
                       CustomTableRow(title='Listeners',
                                      action=Action.LISTENERS,
                                      pattern=MenuPattern.LISTENERS),
                       CustomTableRow(title='Subscriptions',
                                      action=Action.SUBSCRIPTIONS,
                                      pattern=MenuPattern.SUBSCRIPTIONS),
                       CustomTableRow(title='Roles',
                                      action=Action.ROLES,
                                      pattern=MenuPattern.ROLES),
                       )
            )
            chat_data['menupage'] = menupage
            markup = menupage.markup
            try:
                await kwargs['message'].edit_text(menupage.title, reply_markup=markup)
            except BadRequest:
                await context.bot.send_message(kwargs['chat'].id, menupage.title, reply_markup=markup)
            return
        return await self.__menu_commons(update, context)
        # match inline query callback
        # content = menupage.content(kwargs['callback_data'])
        # match content:
        #     case _:
        #         return await self.__menu_commons(update, context)
        # refresh menu
        # await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # Inline listeners menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def listeners_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle LISTENERS menu callback """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        content = menupage.content(kwargs['callback_data'])
        # match inline query callback
        match content:
            # prepare existing Listeners list
            case {CallbackKey.ACTION: Action.LISTENERS}:
                menupage = InlineMenuPage(
                    pattern=MenuPattern.LISTENERS,
                    title='Available listeners',
                    items=self.db.listeners(),
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # switch Listener active state
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.LISTENER_ID: int(listener_id),
                  CallbackKey.ACTIVE: bool() | None as active}:
                self.logger.debug('Enable/disable LISTENER')
                self.db.set_listener(listener_id, active=not active)
                menupage.items = self.db.listeners()
            case _:
                return await self.__menu_commons(update, context)
        # refresh menu
        await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # Inline chats menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def chats_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle CHATS menu callback """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        content = menupage.content(kwargs['callback_data'])
        # match inline query callback
        match content:
            # prepare existing Chats list
            case {CallbackKey.ACTION: Action.CHATS}:
                menupage = InlineMenuPage(
                    pattern=MenuPattern.CHATS,
                    title='Available chats',
                    items=self.db.chats(),      # TODO exclude self
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # switch Chat active state
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.ACTIVE: bool() | None as active}:
                self.logger.debug('Enable/disable LISTENER')
                self.db.set_chat(chat_id, active=not active)
                menupage.items = self.db.chats()
            case _:
                return await self.__menu_commons(update, context)
        # refresh menu
        await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # Inline subscriptions menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, admin=True)
    async def subscriptions_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle SUBSCRIPTIONS menu callback """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        content = menupage.content(kwargs['callback_data'])
        # match inline query callback
        match content:
            # prepare active chats list for subscription managing
            case {CallbackKey.ACTION: Action.SUBSCRIPTIONS}:
                menupage = InlineMenuPage(
                    pattern=MenuPattern.SUBSCRIPTIONS,
                    title='Choose a chat to manage subscriptions',
                    items=self.db.chats(active_only=True),
                    items_action=Action.LISTENERS,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # prepare listeners list for chat with checked subscriptions
            case {CallbackKey.ACTION: Action.LISTENERS,
                  CallbackKey.CHAT_ID: int(chat_id)}:
                title, subscriptions = self.db.subscriptions(chat_id)
                menupage = InlineMenuPage(
                    pattern=MenuPattern.SUBSCRIPTIONS,
                    title=f'Set subscriptions for {title}',
                    items=subscriptions,
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # insert/update Subscription
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.LISTENER_ID: int(listener_id),
                  CallbackKey.ACTIVE: bool() | None as active}:
                # insert/update Subscription
                self.logger.debug('Insert/update SUBSCRIPTION')
                self.db.set_subscription(chat_id, listener_id, active=not active)
                _, menupage.items = self.db.subscriptions(chat_id)
            case _:
                return await self.__menu_commons(update, context)
        await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # Inline roles menu
    @checkvars
    @allowed_for(UserRole.MASTER, admin=False)
    async def roles_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle ROLES menu callback """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        content = menupage.content(kwargs['callback_data'])
        # match inline query callback
        match content:
            # prepare private chats list
            case {CallbackKey.ACTION: Action.ROLES}:
                # build menu
                menupage = InlineMenuPage(
                    pattern=MenuPattern.ROLES,
                    title='Available private chats',
                    items=self.db.chats(active_only=True, of_types=ChatType.PRIVATE),   # TODO exclude self
                    items_action=Action.CHATS,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage
                )
                kwargs['chat_data']['menupage'] = menupage
            # prepare roles list for chat
            case {CallbackKey.ACTION: Action.CHATS,
                  CallbackKey.CHAT_ID: int(chat_id)}:
                username, roles = self.db.roles(chat_id)
                menupage = InlineMenuPage(
                    MenuPattern.ROLES,
                    title=f'Set roles for {username}',
                    items=roles,
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # switch role state
            case {CallbackKey.ACTION: Action.SWITCH,
                  CallbackKey.CHAT_ID: int(chat_id),
                  CallbackKey.ROLE: UserRole(role)}:
                # update role
                self.logger.debug('Add/remove PRIVATE role')
                self.db.set_chat(chat_id, role=role)
                _, menupage.items = self.db.roles(chat_id)
            case _:
                return await self.__menu_commons(update, context)
        # refresh menu
        await self.__menu_refresh(update, context)

    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # event handlers
    async def _onerror(self, update: object, context: CCT):
        """ Error handler """
        match context.error:
            case MenuError() if isinstance(update, Update) and update.effective_message is not None:
                try:
                    await update.effective_message.edit_text(str(context.error), reply_markup=None)
                except Exception as ex:
                    self.logger.error(str(ex))
        # TODO send error to DEVELOPER
        self.logger.error(str(context.error))

    async def _onstart(self, context: CCT):
        """ On start event """
        # TODO

    async def _onclose(self, context: CCT):
        """ On shutdown event """
        if context.job_queue is not None:
            context.job_queue.scheduler.remove_all_jobs()
        os.kill(os.getpid(), signal.SIGTERM)

    # --------------------------------------------------------------------------------
    # private methods
    def __get_random_user(self, args: Sequence[str] | None, exclude_user: int) -> int:
        """ Get random private user """
        chats = self.db.chats(active_only=True, of_types=ChatType.PRIVATE)
        privates = tuple(chat.chat_id for chat in chats
                         if chat.chat_id != exclude_user)
        try:
            if not args:
                raise ValueError('No destination chat set')
            chat_id = int(args[0])
            if chat_id not in privates:
                raise ValueError('Unknown private chat')
        except ValueError:
            chat_id = random.choice(privates)
        return chat_id


    # async def message(self, update: Update, context: CallbackContext):
    #     logging.debug('start command received')
    #     bp = 1


