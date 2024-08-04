from __future__ import annotations
import datetime as dt
import pathlib
import sqlalchemy as sa
import typing
from croniter import croniter


# ============================ Factory definition ==============================
class CronMixin(typing.Protocol):
    _cronstring: str
    _tzinfo: dt.tzinfo
    @property
    def next_t(self) -> dt.datetime: ...


@typing.runtime_checkable
class Listener(CronMixin, typing.Protocol):
    name: str
    updated: dt.datetime
    def inherit(self, other: typing.Self): ...
    def check(self) -> tuple[str, ...]: ...
    def close(self) -> None: ...


class ListenerFactory:
    """ Listener factory """
    @typing.overload
    def __new__(cls, ltype: typing.Literal['FilesListener']) -> type[FilesListener]: ...
    @typing.overload
    def __new__(cls, ltype: typing.Literal['FoldersListener']) -> type[FoldersListener]: ...
    @typing.overload
    def __new__(cls, ltype: typing.Literal['SQLListener']) -> type[SQLListener]: ...
    @typing.overload
    def __new__[L: Listener, **P](cls, ltype: typing.Callable[P, L]) -> typing.Callable[P, L]: ...
    def __new__[L: Listener, **P](cls, ltype: typing.Literal['FilesListener', 'FoldersListener', 'SQLListener'] | typing.Callable[P, L]) -> ...:
        match ltype:
            case 'FilesListener':
                return FilesListener
            case 'FoldersListener':
                return FoldersListener
            case 'SQLListener':
                return SQLListener
            case _:
                return ltype


# ============================ Listeners definition ============================
class CronSchedule:
    _cronstring: str
    _tzinfo: dt.tzinfo

    @property
    def next_t(self) -> dt.datetime:
        """ Get the next scheduled datetime """
        return croniter(self._cronstring, dt.datetime.now(dt.UTC)).get_next(dt.datetime).astimezone(self._tzinfo)


@typing.final
class FilesListener(CronSchedule):
    """ Listen for files update """
    def __init__(self,
                 cronstring: str,
                 tzinfo: dt.tzinfo,
                 filepaths: typing.Sequence[str],
                 single_message: bool = False,
                 **kwargs: typing.Any
                 ):
        self.name = kwargs.get('title', 'unnamed')
        self._cronstring = cronstring
        self._tzinfo = tzinfo
        self._filepaths = tuple(pathlib.Path(p) for p in filepaths)
        self._single_message = single_message
        self.updated = dt.datetime.now()

    def inherit(self, other: FilesListener):
        """ Inherit state from other listener """
        self.updated = other.updated

    def check(self) -> tuple[str, ...]:
        # TODO listening for file create/delete events
        _updated = dt.datetime.now()
        params = ((p.as_posix(), modtime.strftime('%Y-%m-%d %H:%M:%S')) for p in self._filepaths
                  if p.exists() and (modtime := dt.datetime.fromtimestamp(p.stat().st_mtime)) > self.updated)
        if self._single_message:
            messages = ('Modified files:\n' + '\n'.join((f'{p} at {t}' for p, t in params)),)
        else:
            messages = tuple(f'File {p} was modified at {t}.' for p, t in params)
        self.updated = _updated
        return messages

    def close(self) -> None:
        return


@typing.final
class FoldersListener(CronSchedule):
    """ Listen for folders update """
    def __init__(self,
                 cronstring: str,
                 tzinfo: dt.tzinfo,
                 folderpaths: typing.Sequence[str],
                #  single_message: bool = False,
                 **kwargs: typing.Any
                 ):
        self.name = kwargs.get('title', 'unnamed')
        self._cronstring = cronstring
        self._tzinfo = tzinfo
        self._folderpaths = tuple(pathlib.Path(p) for p in folderpaths)
        self._files = {p.as_posix(): self.__folder_content(p) for p in self._folderpaths}
        self.updated = dt.datetime.now()

    @staticmethod
    def __folder_content(path: pathlib.Path) -> set[str]:
        files = set()
        for root, _, _files in path.walk():
            files.update(root.joinpath(f).as_posix() for f in _files)
        return files

    def inherit(self, other: FoldersListener):
        """ Inherit state from other listener """
        self._files = {p.as_posix(): other._files.get(p.as_posix(), self.__folder_content(p))
                       for p in self._folderpaths}
        self.updated = other.updated

    def check(self) -> tuple[str, ...]:
        _updated = dt.datetime.now()
        messages = []
        for p in self._folderpaths:
            path = p.as_posix()
            # check for folder content changes
            files = self.__folder_content(p)
            added = files.difference(self._files[path])
            removed = self._files[path].difference(files)
            if not (added or removed):
                continue
            # build message
            msg = f'[{p.absolute()}]\n'
            if added:
                msg += f'added {len(added)} file(s);\n'
            if removed:
                msg += f'removed {len(removed)} file(s);\n'
            messages.append(msg)
            # remember folder content
            self._files[path] = files
        self.updated = _updated
        return tuple(messages)

    def close(self) -> None:
        return


@typing.final
class SQLListener(CronSchedule):
    """ Listen for SQL destination update

    The specified query parameter may contain :timestamp variable for accessing last update datetime
    The result of specified query must match the following table model:
        - column 1 is a message datetime
        - column 2 is a message text
    """
    def __init__(self,
                 cronstring: str,
                 tzinfo: dt.tzinfo,
                 connection: str,
                 query: str,
                 **kwargs: typing.Any
                 ):
        self.name = kwargs.get('title', 'unnamed')
        self._cronstring = cronstring
        self._tzinfo = tzinfo
        self.__engine = sa.create_engine(connection, poolclass=sa.NullPool)
        self.__query = sa.text(query)
        self.updated = dt.datetime.now()

    def inherit(self, other: SQLListener):
        """ Inherit state from other listener """
        self.updated = other.updated

    def check(self) -> tuple[str, ...]:
        # don't set self.updated, if SQL query failed
        _updated = dt.datetime.now()
        with self.__engine.connect() as conn:
            rows = conn.execute(self.__query, dict(timestamp=self.updated)).all()
        content = tuple(f'[{row[0].strftime("%d.%m.%Y %H:%M:%S")}]\n{row[1]}' for row in rows)
        self.updated = _updated
        return content

    def close(self) -> None:
        self.__engine.dispose()
