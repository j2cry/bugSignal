from __future__ import annotations
import enum
import math
import typing
from collections import namedtuple
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from defaults import Emoji
from model import RowLike


class MenuPattern(enum.StrEnum):
    """ Menu pattern: will not contain `:` symbol """
    EMPTY = ''
    MAIN = enum.auto()
    CHATS = enum.auto()
    LISTENERS = enum.auto()
    SUBSCRIPTIONS = enum.auto()
    ROLES = enum.auto()
    SHUTDOWN = enum.auto()


class Action(enum.IntEnum):
    """ Action identifiers """
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
    CONFIRM = enum.auto()


class CallbackKey(enum.StrEnum):
    """ Callback content keys """
    ACTION = enum.auto()
    CHAT_ID = enum.auto()
    LISTENER_ID = enum.auto()
    ROLE = enum.auto()
    ACTIVE = enum.auto()


class CallbackContent(typing.TypedDict):
    """ Callback content typings """
    action: Action | None
    chat_id: typing.NotRequired[int]
    listener_id: typing.NotRequired[int]
    role: typing.NotRequired[int]
    active: typing.NotRequired[bool]


CallbackProtocol = typing.MutableMapping[int, CallbackContent]


class Button(enum.IntFlag):
    """ Additional buttons """
    EMPTY = 0
    NAVIGATION = enum.auto()
    BACK = enum.auto()
    CLOSE = enum.auto()


@typing.final
class InlineMenuPage:
    """ Inline menu instance """
    ITEMS_PER_PAGE = 4

    _ItemMetadata = namedtuple('_ItemMetadata', 'action,pattern')

    def __init__(self,
                 pattern: str,
                 title: str,
                 *,
                 items: typing.Sequence[RowLike],
                 checkmark: bool = False,
                 items_action: Action | typing.Sequence[Action] | None = None,
                 items_pattern: MenuPattern | typing.Sequence[MenuPattern] | None = None,
                 additional_buttons: Button = Button.EMPTY,
                 previous: InlineMenuPage | None = None,
                 ):
        __assert_message = '`%s` must contain either one or as many values as items'
        self.__pattern = pattern
        self.title = title
        self.items = items
        self.__checkmark = checkmark
        __items_action = (items_action if isinstance(items_action, typing.Sequence)
                          else [items_action] * len(items))
        assert len(__items_action) in {1, len(items)}, __assert_message % '`items_action`'
        __items_pattern = (items_pattern if isinstance(items_pattern, typing.Sequence)
                           else [items_pattern or pattern] * len(items))
        assert len(__items_pattern) in {1, len(items)}, __assert_message % '`items_pattern`'
        self.__metadata = tuple(self._ItemMetadata(action, pattern)
                                for action, pattern in zip(__items_action, __items_pattern))
        self.__additional_buttons = additional_buttons
        self.previous = previous
        self.__page = 0
        self.__callback_content: CallbackProtocol = {}

    @property
    def page(self) -> int:
        return self.__page

    @page.setter
    def page(self, value: int):
        """ Set page preventing overflow """
        MAXPAGE = math.ceil(len(self.items) / self.ITEMS_PER_PAGE) - 1
        if value < 0:
            self.__page = MAXPAGE
        elif value > MAXPAGE:
            self.__page = 0
        else:
            self.__page = value

    def __set_button_content(self,
                             title: str,
                             content: CallbackContent,
                             pattern: str | None = None,
                             ) -> InlineKeyboardButton:
        """ Create inline button and save its callback content """
        _pattern = pattern or self.__pattern
        _button_id = max(self.__callback_content.keys() or [-1]) + 1
        self.__callback_content[_button_id] = content
        return InlineKeyboardButton(title, callback_data=f'{_pattern}:{_button_id}')

    @property
    def markup(self) -> InlineKeyboardMarkup:
        """ Build markup from page items with additional buttons """
        # build inline keyboard
        self.__callback_content.clear()
        buttons = []
        START = self.page * self.ITEMS_PER_PAGE
        END = (self.page + 1) * self.ITEMS_PER_PAGE
        for n, (item, meta) in enumerate(zip(self.items[START:END], self.__metadata[START:END])):
            # collect button callback content
            _item_dict = item._asdict()
            _content = CallbackContent(**{_param_name: _item_dict[_param_name]
                                          for _param_name in CallbackContent.__annotations__.keys()
                                          if _param_name in _item_dict})
            if meta.action is not None:
                _content['action'] = meta.action
            if self.__checkmark:
                mark = f'{(Emoji.ENABLED if _content.get(CallbackKey.ACTIVE) else Emoji.DISABLED)} '
            else:
                mark = ''
            title = mark + (getattr(item, 'title', None) or f'Unknown {n}')
            _pattern = _item_dict.get('pattern', meta.pattern)
            buttons.append((self.__set_button_content(title, _content, _pattern),))

        # append service buttons
        if Button.NAVIGATION in self.__additional_buttons:
            buttons.append((self.__set_button_content('<<', {'action': Action.PREVPAGE}),
                            self.__set_button_content('>>', {'action': Action.NEXTPAGE})
                            ))
        if Button.BACK in self.__additional_buttons:
            buttons.append((self.__set_button_content('Back', {'action': Action.BACK}),))
        # add CLOSE button
        if Button.CLOSE in self.__additional_buttons:
            buttons.append((self.__set_button_content('Close', {'action': Action.CLOSE}),))
        return InlineKeyboardMarkup(buttons)

    def content(self, key: str) -> CallbackContent:
        """ Get button content for specified callback data """
        try:
            _key = int(key[key.index(':') + 1:])
            return self.__callback_content[_key]
        except (ValueError, KeyError):
            return CallbackContent(action=None)

class MenuError(Exception): ...
