from __future__ import annotations
import datetime as dt
import pathlib
import sqlalchemy as sa
import typing
from collections import defaultdict
from croniter import croniter


# ============================ Exceptions definition ===========================
class ListenerCheckError(Exception):
    """ Listener check exception """
    def __init__(self, listener_id: int, title: str, chat_id: int | None) -> None:
        super().__init__(listener_id, title, chat_id)


# ============================ Factory definition ==============================
class CronMixin(typing.Protocol):
    @property
    def next_t(self) -> tuple[bool, dt.datetime]: ...


@typing.runtime_checkable
class Listener(CronMixin, typing.Protocol):
    identifier: int
    name: str
    updated: dt.datetime
    def inherit(self, other: typing.Self): ...
    def check(self) -> tuple[str, ...]: ...
    def close(self) -> None: ...


class ListenerFactory:
    """ Listener factory """
    @typing.overload
    def __new__(cls, ltype: typing.Literal['FileSystemListener']) -> type[FileSystemListener]: ...
    @typing.overload
    def __new__(cls, ltype: typing.Literal['SQLListener']) -> type[SQLListener]: ...
    @typing.overload
    def __new__[L: Listener, **P](cls, ltype: typing.Callable[P, L]) -> typing.Callable[P, L]: ...
    def __new__[L: Listener, **P](cls, ltype: typing.Literal['FileSystemListener', 'SQLListener'] | typing.Callable[P, L]) -> ...:
        match ltype:
            case 'FileSystemListener':
                return FileSystemListener
            case 'SQLListener':
                return SQLListener
            case _:
                return ltype


# ============================ Listeners definition ============================
class CronSchedule:
    def __init__(self, cronsting: str, tzinfo: dt.tzinfo):
        """ Init croniter """
        self.__cron = croniter(cronsting, dt.datetime.now(tzinfo))
        self.__tzinfo = tzinfo
        self.__cron.get_next()  # init next_t

    @property
    def next_t(self) -> tuple[bool, dt.datetime]:
        """ Provides the current expiration status and the following schedule entry [always in the future] """
        _current_t = self.__cron.get_current(dt.datetime)
        _expired = _current_t <= dt.datetime.now(self.__tzinfo)
        if _expired:
            return _expired, self.__cron.get_next(dt.datetime)
        else:
            return _expired, _current_t


class BaseListener:
    def __init__(self,
                 listener_id: int,
                 title: str,
                 ):
        """ Base listener init """
        self.identifier = listener_id
        self.name = title
        self.updated = dt.datetime.now()


@typing.final
class FileSystemListener(BaseListener, CronSchedule):
    """ Listen for files and folders update

    Parameters
    ----------
    title : listener name
    cronstring : schedule string in cron syntax
    tzinfo : server timezone
    path : tracked file or folder path
    mask : mask for recursive selecting subfolders or files in path; \
        takes no effect if path is a file path; \
        when `None`, the path will be tracked as a single folder \
    """
    def __init__(self,
                 listener_id: int,
                 title: str,
                 cronstring: str,
                 tzinfo: dt.tzinfo,
                 path: str,
                 mask: str | None = None,
                 **kwargs: typing.Any
                 ):
        BaseListener.__init__(self, listener_id, title)
        CronSchedule.__init__(self, cronstring, tzinfo)
        self._state: dict[pathlib.Path, set[str] | dt.datetime | None] = defaultdict(lambda: None)
        self._path = path
        self._mask = mask
        # collect starting state
        for item in self.__filesystem_items():
            self._state[item] = self.__default(item)

    @staticmethod
    def __folder_content(path: pathlib.Path) -> set[str]:
        files = set()
        for root, _, _files in path.walk():
            files.update(root.joinpath(f).as_posix() for f in _files)
        return files

    def __filesystem_items(self) -> tuple[pathlib.Path, ...]:
        """ Collect file system items """
        if (_path := pathlib.Path(self._path)).is_dir() and self._mask:
            return tuple(_path.rglob(self._mask))
        else:
            return (_path,)

    def __default(self, item: pathlib.Path) -> dt.datetime | set[str] | None:
        if item.is_file():
            return dt.datetime.fromtimestamp(item.stat().st_mtime)
        elif item.is_dir():
            return self.__folder_content(item)

    def inherit(self, other: FileSystemListener):
        """ Inherit state from other listener """
        for item in self._state.keys():
            if item in other._state:
                self._state[item] = other._state[item]
        self.updated = other.updated

    def check(self) -> tuple[str, ...]:
        _updated = dt.datetime.now()
        messages = []
        _items = {*self.__filesystem_items(), *self._state.keys()}
        for item in _items:
            # item was removed
            if not item.exists():
                messages.append(f'Removed: {item.absolute()}')
                self._state.pop(item)
            # item was created
            elif self._state[item] is None:
                messages.append(f'Created: {item.absolute()}')
                self._state[item] = self.__default(item)
            # item is a file
            elif item.is_file():
                self._state[item] = file_updated = dt.datetime.fromtimestamp(item.stat().st_mtime)
                if file_updated > self.updated:
                    messages.append(f'File modified: {item.absolute()}')
            # item is a folder
            elif item.is_dir():
                assert isinstance(_state := self._state[item], set), 'Invalid state'
                self._state[item] = content = self.__folder_content(item)
                added = content.difference(_state)
                removed = _state.difference(content)
                if not (added or removed):
                    continue
                # build message
                _message = f'[{item.absolute()}]\n'
                if added:
                    _message += f'created {len(added)} file(s);\n'
                if removed:
                    _message += f'removed {len(removed)} file(s);\n'
                messages.append(_message)
        self.updated = _updated
        return tuple(messages)

    def close(self) -> None:
        return


@typing.final
class SQLListener(BaseListener, CronSchedule):
    """ Listen for SQL destination update

    Parameters
    ----------
    title : listener name
    cronstring : schedule string in cron syntax
    tzinfo : server timezone
    connection : SQLAlchemy connection string
    query : SQL query for receiving messages; it may contain `:timestamp` variable for accessing last update timestamp. \
        The result of specified query must match the following table model:
        - column 1 is a message datetime
        - column 2 is a message text
    continual : when True, update timestamp will be set as the max timestamp of the collected messages, \
        otherwise it will be set as current timestamp.
    """
    def __init__(self,
                 listener_id: int,
                 title: str,
                 cronstring: str,
                 tzinfo: dt.tzinfo,
                 connection: str,
                 query: str,
                 continual: bool = True,
                 **kwargs: typing.Any
                 ):
        BaseListener.__init__(self, listener_id, title)
        CronSchedule.__init__(self, cronstring, tzinfo)
        self.__engine = sa.create_engine(connection, poolclass=sa.NullPool)
        self.__query = sa.text(query)
        self.__continual = continual

    def inherit(self, other: SQLListener):
        """ Inherit state from other listener """
        self.updated = other.updated

    def check(self) -> tuple[str, ...]:
        # don't set self.updated, if SQL query failed
        _updated = dt.datetime.now()
        with self.__engine.connect() as conn:
            rows = conn.execute(self.__query, dict(timestamp=self.updated)).all()
        content = tuple(f'[{row[0].strftime("%d.%m.%Y %H:%M:%S")}]\n{row[1]}' for row in rows)
        if not self.__continual:
            self.updated = _updated
        elif rows:
            self.updated = max(row[0] for row in rows)
        return content

    def close(self) -> None:
        self.__engine.dispose()
