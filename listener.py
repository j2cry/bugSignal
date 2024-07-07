import datetime as dt
import enum
import pathlib
import sqlalchemy as sa
import typing as t



@t.final
class FilesListener:
    """ Listen for files update """
    def __init__(self,
                 updated: dt.datetime,
                 filepaths: t.Sequence[str],
                 single_message: bool = False,
                 ):
        self.updated = updated or dt.datetime.now()
        self.__filepaths = tuple(pathlib.Path(p) for p in filepaths)
        self.__single_message = single_message

    def check(self) -> tuple[str, ...]:
        # TODO listening for file create/delete events
        _updated = dt.datetime.now()
        params = ((p.as_posix(), modtime.strftime('%Y-%m-%d %H:%M:%S')) for p in self.__filepaths
                  if p.exists() and (modtime := dt.datetime.fromtimestamp(p.stat().st_mtime)) > self.updated)
        if self.__single_message:
            messages = ('Modified files:\n' + '\n'.join((f'{p} at {t}' for p, t in params)),)
        else:
            messages = tuple(f'File {p} was modified at {t}.' for p, t in params)
        self.updated = _updated
        return messages

    def close(self) -> None:
        return

    # @property
    # def state(self) -> t.Mapping[str, t.Any]:
    #     return {
    #         'updated': self.updated,
    #         'filepaths': tuple(p.as_posix() for p in self.__filepaths),
    #         'single_message': self.__single_message,
    #     }


@t.final
class FoldersListener:
    """ Listen for folders update """
    def __init__(self,
                 updated: dt.datetime,
                 folderpaths: t.Sequence[str],
                 files: t.MutableMapping[str, set[str]] | None = None,
                #  single_message: bool = False,
                 ):
        self.updated = updated or dt.datetime.now()
        self.__folderpaths = tuple(pathlib.Path(p) for p in folderpaths)
        self.__files = files or {p.as_posix(): self.__folder_content(p)
                                 for p in self.__folderpaths}

    @staticmethod
    def __folder_content(path: pathlib.Path) -> set[str]:
        files = set()
        for root, _, _files in path.walk():
            files.update(root.joinpath(f).as_posix() for f in _files)
        return files

    def check(self) -> tuple[str, ...]:
        _updated = dt.datetime.now()
        messages = []
        for p in self.__folderpaths:
            path = p.as_posix()
            # check for folder content changes
            files = self.__folder_content(p)
            added = files.difference(self.__files[path])
            removed = self.__files[path].difference(files)
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
            self.__files[path] = files
        self.updated = _updated
        return tuple(messages)

    def close(self) -> None:
        return


@t.final
class SQLListener:
    """ Listen for SQL destination update.
    Applicable for tables, views, table-valued functions and procedures
    """
    def __init__(self,
                 updated: dt.datetime,
                 connection: str,
                 orderby: str,
                 query: str,
                 ):
        self.updated = updated or dt.datetime.now()
        self.__engine = sa.create_engine(connection)
        self.__orderby = orderby
        self.__query = sa.text(query)

    def check(self) -> tuple[str, ...]:
        _updated = dt.datetime.now()
        # TODO
        # NOTE не обновлять self.updated, если данные из SQL не были получены
        self.updated = _updated
        return ()

    def close(self) -> None:
        self.__engine.dispose()

    # @property
    # def state(self) -> t.Mapping[str, t.Any]:
    #     return {}


# ============================ Factory definition ==============================
@t.runtime_checkable
class Listener[**P](t.Protocol):
    updated: dt.datetime
    def check(self) -> tuple[str, ...]: ...
    def close(self) -> None: ...
    def __init__(self, *args: P.args, **kwargs: P.kwargs): ...
    # @property
    # def state(self) -> t.Mapping[str, t.Any]: ...     # NOTE нужен для пересоздания в actualize

class ListenerFactory:
    def __new__[L: Listener, **P](cls, ltype: t.Callable[P, L], *args: P.args, **kwargs: P.kwargs) -> L:
        return ltype(*args, **kwargs)


# # usage example
# class ListenerType(enum.Enum):
#     FILES = FilesListener
#     FOLDERS = FoldersListener
#     SQL = SQLListener
# s = 'SQL'
# cf = {
#     'updated': dt.datetime.now(),
#     'folderpaths': (),
# }
# # ListenerType[s].value типизируется как Union, поэтому идентифицируется ошибка
# obj = ListenerFactory(ListenerType[s].value, updated=dt.datetime.now(), connection='', orderby='', query='')
# obj = ListenerFactory(ListenerType[s].value, **cf)
# # при точном указании ошибок нет
# obj = ListenerFactory(ListenerType.FILES.value, **cf)
# obj = ListenerFactory(FoldersListener, folderpaths=(), updated=dt.datetime.now())







# another way
class FType(enum.IntEnum):
    FILES = enum.auto()
    FOLDERS = enum.auto()
    SQL = enum.auto()


@t.overload
def factory(ltype: t.Literal[FType.FILES], **kwargs: t.Any) -> FilesListener: ...
@t.overload
def factory(ltype: t.Literal[FType.FOLDERS], **kwargs: t.Any) -> FoldersListener: ...
@t.overload
def factory(ltype: t.Literal[FType.SQL], **kwargs: t.Any) -> SQLListener: ...
@t.overload
def factory(ltype: FType, **kwargs: t.Any) -> Listener: ...
def factory(ltype: FType, **kwargs: t.Any) -> Listener:
    match ltype:
        case FType.FILES:
            return FilesListener(**kwargs)
        case FType.FOLDERS:
            return FoldersListener(**kwargs)
        case FType.SQL:
            return SQLListener(**kwargs)
        case _:
            raise NotImplementedError()


# s = 'FILES'
# cf = {}
# obj = factory(FType[s], **cf)
# obj = factory(FType.SQL, **cf)


