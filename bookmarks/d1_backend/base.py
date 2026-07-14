"""
Django database backend for Cloudflare D1.

D1 is SQLite, so this backend reuses Django's sqlite3 backend (SQL dialect,
schema editor, introspection) and only swaps out the connection layer: instead
of the stdlib sqlite3 module, statements are sent to the D1 HTTP API through
the DB-API shim in bookmarks.d1_backend.dbapi.

Because the D1 HTTP API is stateless, transactions are not supported - every
statement is committed individually. transaction.atomic() blocks still work
but do not provide atomicity or rollback.

Configuration is done through the OPTIONS dict of the database settings:

    DATABASES = {
        "default": {
            "ENGINE": "bookmarks.d1_backend",
            "NAME": "<database id>",
            "OPTIONS": {
                "account_id": "<Cloudflare account id>",
                "database_id": "<D1 database id>",
                "api_token": "<API token with D1 edit permission>",
            },
        }
    }
"""

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.sqlite3 import base as sqlite3_base
from django.db.backends.sqlite3 import features as sqlite3_features
from django.db.backends.sqlite3 import operations as sqlite3_operations
from django.utils.asyncio import async_unsafe

from . import dbapi as Database


class DatabaseFeatures(sqlite3_features.DatabaseFeatures):
    # The D1 HTTP API executes every statement in its own implicit
    # transaction; interactive transactions and savepoints are not available.
    supports_transactions = False
    uses_savepoints = False
    can_release_savepoints = False
    atomic_transactions = False
    can_rollback_ddl = False
    can_clone_databases = False
    # https://developers.cloudflare.com/d1/platform/limits/
    max_query_params = Database.MAX_BOUND_PARAMETERS
    # D1 runs a recent SQLite version, don't gate these on the version of the
    # locally installed sqlite3 module
    can_alter_table_drop_column = True
    can_return_columns_from_insert = True
    supports_aggregate_order_by_clause = True


class DatabaseOperations(sqlite3_operations.DatabaseOperations):
    def last_executed_query(self, cursor, sql, params):
        # The sqlite3 implementation quotes parameters by executing a
        # "SELECT QUOTE(?)" query, which would cause an extra HTTP request
        # per logged query. Interpolate locally instead.
        if params:
            if isinstance(params, (list, tuple)):
                params = tuple(Database._literal(param) for param in params)
            else:
                params = {
                    name: Database._literal(value) for name, value in params.items()
                }
            return sql % params
        return sql


class DatabaseWrapper(sqlite3_base.DatabaseWrapper):
    display_name = "Cloudflare D1"

    Database = Database
    features_class = DatabaseFeatures
    ops_class = DatabaseOperations

    def get_connection_params(self):
        options = self.settings_dict.get("OPTIONS") or {}
        conn_params = {
            "account_id": options.get("account_id"),
            "database_id": options.get("database_id") or self.settings_dict.get("NAME"),
            "api_token": options.get("api_token"),
            "api_url": options.get("api_url"),
        }
        if not (
            conn_params["account_id"]
            and conn_params["database_id"]
            and conn_params["api_token"]
        ):
            raise ImproperlyConfigured(
                "The Cloudflare D1 backend requires the account_id, database_id "
                "and api_token options. Set the LD_CF_ACCOUNT_ID, "
                "LD_CF_D1_DATABASE_ID and LD_CF_API_TOKEN environment variables."
            )
        # Attributes normally set up by the sqlite3 backend
        self.transaction_mode = None
        self.init_commands = []
        return conn_params

    def get_database_version(self):
        return Database.sqlite_version_info

    @async_unsafe
    def get_new_connection(self, conn_params):
        return Database.connect(**conn_params)

    def create_cursor(self, name=None):
        return self.connection.cursor()

    @async_unsafe
    def close(self):
        self.validate_thread_sharing()
        BaseDatabaseWrapper.close(self)

    def _set_autocommit(self, autocommit):
        # The D1 HTTP API always runs in autocommit mode
        pass

    def _start_transaction_under_autocommit(self):
        # Transactions are not supported over the D1 HTTP API
        pass

    def disable_constraint_checking(self):
        # Enables deferred foreign key enforcement on the connection instead
        # of the unsupported "PRAGMA foreign_keys = OFF", see dbapi.Cursor
        self.ensure_connection()
        self.connection.defer_foreign_keys = True
        return True

    def enable_constraint_checking(self):
        self.ensure_connection()
        self.connection.defer_foreign_keys = False

    def is_usable(self):
        return True

    def is_in_memory_db(self):
        return False
