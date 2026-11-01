"""
Minimal DB-API 2.0 shim that executes SQL statements against a Cloudflare D1
database using the D1 HTTP API (/raw endpoint).

The D1 HTTP API is stateless: every request runs in its own implicit
transaction, and interactive transaction statements (BEGIN / COMMIT /
ROLLBACK / SAVEPOINT) are not supported. The cursor therefore treats
transaction control statements as no-ops, and the connection effectively
always runs in autocommit mode.

D1 also does not support "PRAGMA foreign_keys". Instead, foreign key
enforcement can be deferred with "PRAGMA defer_foreign_keys". The cursor
translates Django's "PRAGMA foreign_keys = ON/OFF" statements into a
connection flag, and while the flag is active prefixes statements with
"PRAGMA defer_foreign_keys = true" in the same request, which is the
pattern Cloudflare recommends for schema migrations.
"""

import datetime
import decimal
import re
import uuid
from collections.abc import Mapping

import requests  # noqa: TID251 - talks to the fixed Cloudflare D1 API URL, not user URLs

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"

# Maximum number of bound parameters D1 accepts per query, see
# https://developers.cloudflare.com/d1/platform/limits/
MAX_BOUND_PARAMETERS = 100

DEFAULT_API_URL = "https://api.cloudflare.com/client/v4"


class Error(Exception):
    pass


class Warning(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


# D1 is SQLite. Version reported for compatibility checks; actual version on
# Cloudflare's side is always recent.
sqlite_version_info = (3, 45, 0)

FORMAT_QMARK_REGEX = re.compile(r"(?<!%)%s")
PYFORMAT_REGEX = re.compile(r"%\((\w+)\)s")

TRANSACTION_CONTROL_REGEX = re.compile(
    r"^\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b", re.IGNORECASE
)
PRAGMA_FK_WRITE_REGEX = re.compile(
    r"^\s*PRAGMA\s+foreign_keys\s*=\s*(\w+)\s*;?\s*$", re.IGNORECASE
)
PRAGMA_FK_READ_REGEX = re.compile(r"^\s*PRAGMA\s+foreign_keys\s*;?\s*$", re.IGNORECASE)

INTEGRITY_ERROR_MARKERS = (
    "UNIQUE constraint failed",
    "NOT NULL constraint failed",
    "FOREIGN KEY constraint failed",
    "CHECK constraint failed",
)


def connect(**kwargs):
    return Connection(**kwargs)


def _map_error_message(message):
    for marker in INTEGRITY_ERROR_MARKERS:
        if marker in message:
            return IntegrityError(message)
    return OperationalError(message)


def _adapt_param(value):
    """Convert a Python value into a JSON-serializable D1 parameter."""
    if isinstance(value, bool):
        # bool is a subclass of int, check it first
        return int(value)
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, datetime.datetime):
        return value.isoformat(" ")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise NotSupportedError("BLOB parameters are not supported by the D1 HTTP API")
    return str(value)


def _literal(value):
    """Render a parameter as a SQL literal, used when a query exceeds the
    D1 bound parameter limit."""
    value = _adapt_param(value)
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'{}'".format(value.replace("'", "''"))


class Connection:
    def __init__(
        self,
        account_id,
        database_id,
        api_token,
        api_url=None,
        timeout=(10, 35),
    ):
        if not (account_id and database_id and api_token):
            raise InterfaceError(
                "Cloudflare D1 requires account_id, database_id and api_token"
            )
        base = (api_url or DEFAULT_API_URL).rstrip("/")
        self.url = f"{base}/accounts/{account_id}/d1/database/{database_id}/raw"
        self.timeout = timeout
        # While True, statements are executed with deferred foreign key
        # enforcement (used by Django's schema editor during migrations).
        self.defer_foreign_keys = False
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }
        )

    def cursor(self, factory=None):
        return Cursor(self)

    # The D1 HTTP API is stateless / autocommit, transaction control is a no-op
    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.session.close()

    def execute(self, sql, params=None):
        """Convenience method mirroring sqlite3.Connection.execute()."""
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def raw_query(self, sql, params):
        try:
            response = self.session.post(
                self.url,
                json={"sql": sql, "params": params or []},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise OperationalError(f"Error connecting to Cloudflare D1: {e}") from e

        try:
            data = response.json()
        except ValueError as e:
            raise OperationalError(
                f"Invalid response from Cloudflare D1 API (HTTP {response.status_code})"
            ) from e

        if not data.get("success"):
            messages = (
                "; ".join(
                    error.get("message", str(error)) for error in data.get("errors", [])
                )
                or f"HTTP {response.status_code}"
            )
            raise _map_error_message(messages)

        results = data.get("result") or []
        if not results:
            raise OperationalError("Cloudflare D1 API returned no results")
        # When multiple statements are sent as a batch, the result of the
        # last statement is the relevant one.
        result = results[-1]
        if not result.get("success", True):
            raise _map_error_message(str(result))

        payload = result.get("results") or {}
        columns = payload.get("columns") or []
        rows = payload.get("rows") or []
        meta = result.get("meta") or {}
        return columns, rows, meta


class Cursor:
    arraysize = 1

    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self._rows = []
        self._row_index = 0
        self._closed = False

    def _reset(self):
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self._rows = []
        self._row_index = 0

    def _set_local_result(self, columns, rows):
        self.description = tuple(
            (name, None, None, None, None, None, None) for name in columns
        )
        self._rows = [tuple(row) for row in rows]
        self._row_index = 0
        self.rowcount = len(rows)

    def execute(self, query, params=None):
        if self._closed:
            raise ProgrammingError("Cannot operate on a closed cursor.")
        self._reset()

        # Convert Django's "format" / "pyformat" param styles to positional
        # qmark style as used by D1.
        if params is not None:
            if isinstance(params, Mapping):
                names = []
                query = PYFORMAT_REGEX.sub(
                    lambda match: names.append(match.group(1)) or "?", query
                )
                params = [params[name] for name in names]
            else:
                params = list(params)
                if len(params) > MAX_BOUND_PARAMETERS:
                    # D1 rejects queries with more than 100 bound parameters.
                    # Fall back to inlining values as escaped literals.
                    param_iter = iter(params)
                    query = FORMAT_QMARK_REGEX.sub(
                        lambda match: _literal(next(param_iter)), query
                    ).replace("%%", "%")
                    params = []
                else:
                    query = FORMAT_QMARK_REGEX.sub("?", query).replace("%%", "%")

        # Transaction control statements are not supported by the stateless
        # D1 HTTP API; every statement is committed individually.
        if TRANSACTION_CONTROL_REGEX.match(query):
            return self

        # D1 does not support "PRAGMA foreign_keys". Django's schema editor
        # uses it to disable constraint checking during migrations; emulate
        # it with D1's "PRAGMA defer_foreign_keys" instead.
        write_match = PRAGMA_FK_WRITE_REGEX.match(query)
        if write_match:
            value = write_match.group(1).lower()
            self.connection.defer_foreign_keys = value in ("off", "0", "false")
            return self
        if PRAGMA_FK_READ_REGEX.match(query):
            enabled = 0 if self.connection.defer_foreign_keys else 1
            self._set_local_result(["foreign_keys"], [(enabled,)])
            return self

        if self.connection.defer_foreign_keys and not params:
            query = "PRAGMA defer_foreign_keys = true; " + query

        adapted_params = [_adapt_param(value) for value in params] if params else []
        columns, rows, meta = self.connection.raw_query(query, adapted_params)

        if columns:
            self._set_local_result(columns, rows)
        # For writes, expose the affected row count and last inserted row id
        if not columns or not rows:
            changes = meta.get("changes")
            self.rowcount = changes if isinstance(changes, int) else len(rows)
        self.lastrowid = meta.get("last_row_id")
        return self

    def executemany(self, query, param_list):
        for params in param_list:
            self.execute(query, params)
        return self

    def executescript(self, script):
        self._reset()
        self.connection.raw_query(script, [])
        return self

    def fetchone(self):
        if self._row_index < len(self._rows):
            row = self._rows[self._row_index]
            self._row_index += 1
            return row
        return None

    def fetchmany(self, size=None):
        size = size or self.arraysize
        result = self._rows[self._row_index : self._row_index + size]
        self._row_index += len(result)
        return result

    def fetchall(self):
        result = self._rows[self._row_index :]
        self._row_index = len(self._rows)
        return result

    def close(self):
        self._closed = True
        self._rows = []

    def setinputsizes(self, sizes):
        pass

    def setoutputsize(self, size, column=None):
        pass

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
