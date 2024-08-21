from __future__ import annotations
import asyncio
import datetime as dt
import json
import logging
import os
import pytz
import random
import signal
import sqlalchemy.exc as sqlex
import time
import traceback
from contextlib import contextmanager
from telegram import Update
from telegram.ext import Job
from telegram.constants import ChatType
from telegram.error import BadRequest
from typing import (
    Any,
    Callable,
    Concatenate,
    Coroutine,
    MutableMapping,
    Sequence,
    Unpack,
)

from database import Database
from defaults import (
    Configuration,
    Emoji,
    Environ,
    Notification,
    DEFAULT,
)
from listener import (
    CronSchedule,
    Listener,
    ListenerCheckError,
    ListenerFactory,
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
    CustomTableRow,
    JobData,
    JobName,
    UserRole,
    ValidatedContext,
    MISFIRE_GRACE,
    # UD, CD, BD, BT, CCT, CT,
    BT, CCT,
)


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
        assert (job_queue := context.job_queue) is not None, f'[checkvars] job_queue is None'
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


def allowed_for(roles: UserRole, chat_admin: bool):
    """ Decorator for checking permissions

    Parameters
    ----------
    roles : UserRole
        A set of roles that are allowed to execute a command
    chat_admin : bool
        Flag for allowing Telegram chat administrators to execute the command
    """
    def _permission_check[S: BugSignalService, T, **KW](method: Callable[Concatenate[S, Update, CCT, KW], Coroutine[Any, Any, T]]):
        async def _empty_handler(self: S, update: Update, context: CCT, *args: KW.args, **kwargs: KW.kwargs) -> T: ...
        async def _wrapper(self: S, update: Update, context: CCT, *args: KW.args, **kwargs: KW.kwargs) -> T:
            assert (user := update.effective_user) is not None, '[permission_check] effective_user is None'
            assert (chat := update.effective_chat) is not None, '[permission_check] effective_chat is None'
            assert (message := update.effective_message) is not None, '[permission_check] effective_message is None'
            # callback answer
            if (callback_query := update.callback_query) is not None:
                await callback_query.answer(Notification.MESSAGE_QUERY_ANSWER)
            # get stored user role
            user_roles = (set(UserRole(stored_chat.role))
                          if (stored_chat := self.db.chat(user.id)) is not None
                          else set())
            # allowed by UserRole
            if bool(user_roles.intersection(roles)):
                return await method(self, update, context, *args, **kwargs)
            # otherwise check chat permissions
            administrators = ({_admin.user for _admin in await chat.get_administrators()}
                              if chat.type != ChatType.PRIVATE
                              else set())
            if chat_admin and user in administrators and user_roles:
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
        self.logger = logger
        self.db = Database(os.environ[Environ.SQL_CONNECTION_STRING],
                           schema=config['sqlSchema'],
                           logger=logger)
        self.config = config
        self.__developers: tuple[int, ...] = ()
        try:
            self.timezone = pytz.timezone(self.config['timezone'])
        except:
            self.timezone = pytz.UTC
            self.logger.warning(Notification.LOG_INCORRECT_TIMEZONE, self.config['timezone'])
        self.__actualizer_cron = CronSchedule(self.config['timeout']['actualizerCron'], self.timezone)
        self.__listeners: MutableMapping[int, Listener] = {}

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
                         name=kwargs['chat'].username or kwargs['chat'].effective_name or str(kwargs['chat'].id),
                         type=kwargs['chat'].type)
        await kwargs['message'].reply_text(Notification.MESSAGE_CHAT_INFORMATION_SAVED)

    @checkvars
    @allowed_for(UserRole.ACTIVE, chat_admin=False)
    async def fox(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Send fox emoji """
        chat_id = self.__get_random_user(context.args, kwargs['user'].id)
        self.logger.info(Notification.LOG_SENT_FROM_TO % (kwargs['user'].name, chat_id))
        await context.bot.send_message(chat_id, Emoji.FOX)

    @checkvars
    @allowed_for(UserRole.NECROMANCER, chat_admin=False)
    async def zombie(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Send zombie emoji """
        chat_id = self.__get_random_user(context.args, kwargs['user'].id)
        self.logger.info(Notification.LOG_SENT_FROM_TO % (kwargs['user'].name, chat_id))
        await context.bot.send_message(chat_id, Emoji.ZOMBIE)

    @checkvars
    @allowed_for(UserRole.ACTIVE, chat_admin=True)
    async def check(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Force check all listeners for updates """
        message = await kwargs['message'].reply_text(Notification.MESSAGE_CHECK_LISTENERS)
        _ids = set(int(arg) for arg in (context.args or ()) if arg.isdigit())
        for listener in self.__listeners.values():
            if _ids and listener.id not in _ids:
                continue
            kwargs['job_queue'].run_once(self.__check_listener,
                                         when=0,
                                         data=JobData(listener.id),
                                         name=JobName.CHECKER,
                                         chat_id=kwargs['chat'].id,
                                         job_kwargs=MISFIRE_GRACE)
        # await for all forced listeners done
        started = time.monotonic()
        while time.monotonic() - started < self.config['timeout']['common']:
            if not any(j for j in kwargs['job_queue'].jobs() if (j.name or '').startswith(JobName.CHECKER)):
                break
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError()
        await message.reply_text(Notification.MESSAGE_DONE)

    @checkvars
    @allowed_for(UserRole.ACTIVE, chat_admin=False)
    async def jobstate(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Get current bugSignal state """
        def _jobformat(job: Job[CCT]):
            """ Return formatted job schedule """
            _args = (
                self.__listeners.get(job.data.listener_id, job).name if isinstance(job.data, JobData) else job.name,
                job.next_t.replace(microsecond=0) if job.next_t else None
            )
            return Notification.MESSAGE_JOB_STATE % (*_args,)
        # collect self state args
        _jobs = sorted(kwargs['job_queue'].jobs(), key=lambda j: j.name or '')
        _args = (
            dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '\n'.join(map(_jobformat, _jobs)),
            len(self.__listeners),
        )
        await kwargs['message'].reply_text(Notification.MESSAGE_SELF_STATE % (*_args,))

    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR, chat_admin=False)
    async def actualize(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Actualize listener jobs """
        await self.__actualize(context)
        await self.jobstate(update, context)

    # --------------------------------------------------------------------------------
    # Common inline menu
    @checkvars
    async def __menu_refresh(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Refresh menu page """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        markup = menupage.markup
        if kwargs['message'].text == menupage.name and kwargs['message'].reply_markup == markup:
            return
        try:
            await kwargs['message'].edit_text(menupage.name, reply_markup=markup)
        except BadRequest:
            await context.bot.send_message(kwargs['chat'].id, menupage.name, reply_markup=markup)

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
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR | UserRole.DEVELOPER, chat_admin=True)
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
                name='bugSignal admin panel',
                items=(CustomTableRow(name='Chats',
                                      action=Action.CHATS,
                                      pattern=MenuPattern.CHATS),
                       CustomTableRow(name='Listeners',
                                      action=Action.LISTENERS,
                                      pattern=MenuPattern.LISTENERS),
                       CustomTableRow(name='Subscriptions',
                                      action=Action.SUBSCRIPTIONS,
                                      pattern=MenuPattern.SUBSCRIPTIONS),
                       CustomTableRow(name='Private roles',
                                      action=Action.ROLES,
                                      pattern=MenuPattern.ROLES),
                       ),
                additional_buttons=Button.CLOSE,
            )
            chat_data['menupage'] = menupage
            markup = menupage.markup
            try:
                await kwargs['message'].edit_text(menupage.name, reply_markup=markup)
            except BadRequest:
                await context.bot.send_message(kwargs['chat'].id, menupage.name, reply_markup=markup)
            return
        return await self.__menu_commons(update, context)

    # --------------------------------------------------------------------------------
    # Inline listeners menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR | UserRole.DEVELOPER, chat_admin=False)
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
                    name='Available listeners',
                    items=self.db.listeners(),
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
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
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR | UserRole.DEVELOPER, chat_admin=False)
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
                    name='Available chats',
                    items=self.db.chats(exclude=kwargs['chat'].id),
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
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
    @allowed_for(UserRole.MASTER | UserRole.MODERATOR | UserRole.DEVELOPER, chat_admin=True)
    async def subscriptions_menu(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Handle SUBSCRIPTIONS menu callback """
        if (menupage := kwargs['chat_data'].get('menupage')) is None:
            raise MenuError(Notification.ERROR_MENU_PAGE)
        # restricting subscription editing for group chats
        if kwargs['chat'].type == ChatType.PRIVATE:
            available_chats = self.db.chats(active_only=True)
        elif (_current_chat := self.db.chat(kwargs['chat'].id)) is not None:
            available_chats = (_current_chat,)
        else:
            raise MenuError('Chat is undefined')
        content = menupage.content(kwargs['callback_data'])
        # match inline query callback
        match content:
            # prepare active chats list for subscription managing
            case {CallbackKey.ACTION: Action.SUBSCRIPTIONS}:
                menupage = InlineMenuPage(
                    pattern=MenuPattern.SUBSCRIPTIONS,
                    name='Choose a chat to manage subscriptions',
                    items=available_chats,
                    items_action=Action.LISTENERS,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
                    previous=menupage,
                )
                kwargs['chat_data']['menupage'] = menupage
            # prepare listeners list for chat with checked subscriptions
            case {CallbackKey.ACTION: Action.LISTENERS,
                  CallbackKey.CHAT_ID: int(chat_id)}:
                name, subscriptions = self.db.subscriptions(chat_id)
                menupage = InlineMenuPage(
                    pattern=MenuPattern.SUBSCRIPTIONS,
                    name=f'Set subscriptions for {name}',
                    items=subscriptions,
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
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
    @allowed_for(UserRole.MASTER | UserRole.DEVELOPER, chat_admin=False)
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
                    name='Available private chats',
                    items=self.db.chats(active_only=True,
                                        of_types=ChatType.PRIVATE,
                                        exclude=kwargs['chat'].id),
                    items_action=Action.CHATS,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
                    previous=menupage
                )
                kwargs['chat_data']['menupage'] = menupage
            # prepare roles list for chat
            case {CallbackKey.ACTION: Action.CHATS,
                  CallbackKey.CHAT_ID: int(chat_id)}:
                username, roles = self.db.roles(chat_id)
                menupage = InlineMenuPage(
                    MenuPattern.ROLES,
                    name=f'Set roles for {username}',
                    items=roles,
                    items_action=Action.SWITCH,
                    checkmark=True,
                    additional_buttons=Button.NAVIGATION | Button.BACK | Button.CLOSE,
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
    # shutdown approve menu
    @checkvars
    @allowed_for(UserRole.MASTER | UserRole.DEVELOPER, chat_admin=False)
    async def shutdown(self, update: Update, context: CCT, **kwargs: Unpack[ValidatedContext]):
        """ Open shutdown confirmation """
        chat_data = kwargs['chat_data']
        if (menupage := chat_data.get('menupage')) is None:
            if kwargs['callback_data']:
                raise MenuError(Notification.ERROR_MENU_PAGE)
            # build confirmation menu
            menupage = InlineMenuPage(
                pattern=MenuPattern.SHUTDOWN,
                name=Notification.MESSAGE_SHUTDOWN_CONFIRM,
                items=(CustomTableRow(name=f'{Emoji.ENABLED} Yes',
                                      action=Action.CONFIRM),
                       CustomTableRow(name=f'{Emoji.DISABLED} No',
                                      action=Action.CLOSE),
                      ),
            )
            chat_data['menupage'] = menupage
            markup = menupage.markup
            try:
                await kwargs['message'].edit_text(menupage.name,
                                                  parse_mode='HTML',
                                                  reply_markup=markup)
            except BadRequest:
                await context.bot.send_message(kwargs['chat'].id, menupage.name,
                                               parse_mode='HTML',
                                               reply_markup=markup)
            return
        else:
            content = menupage.content(kwargs['callback_data'])
            # match inline query callback
            match content:
                # schedule shutdown job
                case {CallbackKey.ACTION: Action.CONFIRM}:
                    self.logger.info(Notification.LOG_SHUTDOWN, kwargs['user'].name, kwargs['user'].id)
                    await kwargs['message'].edit_text(Notification.MESSAGE_SHUTDOWN, reply_markup=None)
                    kwargs['job_queue'].run_once(self._onclose,
                                                 when=self.config['timeout']['close'],
                                                 job_kwargs=MISFIRE_GRACE)
                # close menu
                case _:
                    return await self.__menu_commons(update, context)

    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # event handlers
    async def _onerror(self, update: object, context: CCT):
        """ Error handler """
        error = context.error
        while error is not None:
            self.logger.error(Notification.ERROR_TRACEBACK, *self.__exception_args(error))
            error = error.__cause__
        tasks = ()
        match context.error:
            # drop menu inline
            case MenuError() if isinstance(update, Update) and update.effective_message is not None:
                try:
                    await update.effective_message.edit_text(str(context.error), reply_markup=None)
                except Exception as ex:
                    self.logger.error(str(ex))
            case ListenerCheckError():
                *args, caller_chat_id = context.error.args
                message = Notification.MESSAGE_CHECK_FAILED % (*args,)
                subscribers = {*self.__developers, caller_chat_id} if caller_chat_id is not None else self.__developers
                tasks = tuple(
                    asyncio.create_task(self.__send_messages(context.bot, chat_id, (message,)))
                    for chat_id in subscribers
                )
            # SQL error
            case sqlex.DBAPIError():
                tasks = tuple(
                    asyncio.create_task(self.__send_messages(context.bot,
                                                             chat_id,
                                                             (Notification.MESSAGE_SOMETHING_WRONG,)))
                    for chat_id in self.__developers
                )
            # # http error
            # case httpx.NetworkError():
            #     ...
            # unhandled error
            case _:
                ...
        # await for tasks
        if tasks:
            try:
                await asyncio.wait(tasks, timeout=self.config['timeout']['common'])
            except Exception as ex:
                self.logger.error(Notification.ERROR_TRACEBACK, *self.__exception_args(ex))

    async def _onstart(self, context: CCT):
        """ On start event """
        await self.__actualize(context)
        # collect developers
        self.__developers = tuple(
            chat.chat_id for chat in self.db.chats(active_only=True, of_types=ChatType.PRIVATE)
            if UserRole.DEVELOPER in UserRole(chat.role)
        )

    async def _onclose(self, context: CCT):
        """ On shutdown event """
        if context.job_queue is not None:
            context.job_queue.scheduler.remove_all_jobs()
        os.kill(os.getpid(), signal.SIGTERM)

    # --------------------------------------------------------------------------------
    # private methods
    def __exception_args(self, ex: Exception | BaseException | None) -> tuple[str, str, str]:
        """ Collect exception info for logging """
        return (
            'UnknownException' if ex is None else ex.__class__.__name__,
            str(ex),
            traceback.format_exc()
        )

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

    async def __send_messages(self, bot: BT, chat_id: int, messages: tuple[str, ...]):
        """ Send messages to chat by parts """
        LENGTH = 4096   # max telegram message length
        for message in messages:
            for bound in range(0, len(message), LENGTH):
                part = message[bound:bound + LENGTH]
                started = time.monotonic()
                error = None
                while time.monotonic() - started <= self.config['timeout']['lifetime']:
                    try:
                        await bot.send_message(chat_id, part)
                        self.logger.info(Notification.LOG_MESSAGE_SENT, chat_id)
                        break
                    except Exception as ex:
                        error = ex
                        self.logger.warning(Notification.ERROR_NOT_SENT_TRACEBACK, *self.__exception_args(ex))
                        await asyncio.sleep(self.config['timeout']['retryInterval'])
                else:
                    self.logger.error(Notification.ERROR_NOT_SENT_TRACEBACK, *self.__exception_args(error))

    async def __actualize(self, context: CCT):
        """ Actualize listeners """
        assert (job_queue := context.job_queue) is not None, '[__actualize] job_queue is None'
        # get listeners info from database
        try:
            listeners = self.db.listeners(active_only=True)
        except:
            _next_t = self.config['timeout']['retryInterval']
            raise
        else:
            _next_t = self.__actualizer_cron.next_t
        finally:
            # reschedule actualizer if it is not scheduled
            if _next_t and not any(job_queue.get_jobs_by_name(JobName.ACTUALIZER)):
                job = job_queue.run_once(self.__actualize,
                                         when=_next_t,
                                         name=JobName.ACTUALIZER,
                                         job_kwargs=MISFIRE_GRACE)
                self.logger.info(Notification.LOG_JOB_SCHEDULED, job.name, '--', '--', job.next_t)
        # remove all scheduled listener jobs
        for job in job_queue.get_jobs_by_name(JobName.LISTENER):
            job.schedule_removal()
        # refresh listeners
        __listeners = {**self.__listeners}
        self.__listeners.clear()
        for row in listeners:
            current_listener = __listeners.get(row.listener_id)
            # create listener
            kwargs = row._asdict()
            try:
                kwargs.update(json.loads(kwargs.pop('parameters')), tzinfo=self.timezone)
                listener = ListenerFactory(row.classname)(**kwargs)
            except Exception as ex:
                _args = (row.name, row.listener_id, *self.__exception_args(ex))
                self.logger.error(Notification.ERROR_LISTENER, *_args)
                continue
            # inherit listener state
            if isinstance(current_listener, type(listener)):
                listener.inherit(current_listener)     # type: ignore
                self.logger.info(Notification.LOG_LISTENER_INHERITED, listener.name, listener.id)
            # last check for current listener
            elif current_listener is not None:
                job = job_queue.run_once(self.__check_listener,
                                         when=0,
                                         data=JobData(row.listener_id),
                                         name=JobName.CHECKER,
                                         job_kwargs=MISFIRE_GRACE)
                self.logger.info(Notification.LOG_JOB_SCHEDULED, job.name, listener.name, listener.id, job.next_t)
            # save listener
            self.__listeners[row.listener_id] = listener
            # refresh jobs
            if (_next_t := listener.next_t) is not None:
                # schedule new job
                job = job_queue.run_once(self.__check_listener,
                                         when=_next_t,
                                         data=JobData(row.listener_id),
                                         name=JobName.LISTENER,
                                         job_kwargs=MISFIRE_GRACE)
                self.logger.info(Notification.LOG_JOB_SCHEDULED, job.name, listener.name, listener.id, job.next_t)

    async def __check_listener(self, context: CCT):
        """ Check for listener updates and send notifications """
        assert context.job_queue is not None, '[__check_listener] job_queue is None'
        assert context.job is not None and isinstance(context.job.data, JobData), \
            '[__check_listener] job is None or job.data has incorrect type'
        assert (listener := self.__listeners.get(context.job.data.listener_id)) is not None, \
            f'[__check_listener] unknown listener {context.job.data.listener_id}'
        # start checking
        self.logger.debug(Notification.LOG_CHECK_LISTENER, listener.name, listener.id, listener.updated)
        try:
            if messages := listener.check():
                subscribers = self.db.subscribers(listener.id, active_only=True)
            else:
                subscribers = ()
        except Exception as ex:
            raise ListenerCheckError(listener.id, listener.name, context.job.chat_id) from ex
        finally:
            # reschedule listener job
            if (context.job.name == JobName.LISTENER
                and (_next_t := listener.next_t)
                and not any(context.job_queue.get_jobs_by_name(JobName.LISTENER))
            ):
                job = context.job_queue.run_once(self.__check_listener,
                                                 when=_next_t,
                                                 data=JobData(listener.id),
                                                 name=JobName.LISTENER,
                                                 job_kwargs=MISFIRE_GRACE)
                self.logger.info(Notification.LOG_JOB_SCHEDULED, job.name, listener.name, listener.id, job.next_t)
        # send messages
        if not messages:
            self.logger.info(Notification.LOG_NO_UPDATES, listener.name, listener.id)
            return
        tasks = tuple(asyncio.create_task(self.__send_messages(context.bot, chat.chat_id, messages))
                      for chat in subscribers)
        if tasks:
            await asyncio.wait(tasks, timeout=self.config['timeout']['common'])

    # async def message(self, update: Update, context: CallbackContext):
    #     logging.debug('start command received')
    #     bp = 1
