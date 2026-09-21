"""Set release schema after connecting, including through a session pooler."""
import re

from django.db import DatabaseError
from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper


class DatabaseWrapper(PostgreSQLWrapper):
    def init_connection_state(self):
        super().init_connection_state()
        schema = self.settings_dict.get('NEXORA_SCHEMA', '')
        # Supavisor may ignore startup options. Set state on the established
        # session and fail closed before any application table is accessed.
        try:
            if not re.fullmatch(r'nexora_[a-z0-9_]{1,48}', schema):
                raise DatabaseError('Invalid isolated database schema configuration.')
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT set_config('search_path', %s, false)", (schema,))
                cursor.execute('SELECT current_schema()')
                if cursor.fetchone() != (schema,):
                    raise DatabaseError('The configured isolated schema is unavailable.')
            if not self.get_autocommit():
                self.connection.commit()
        except Exception:
            self.connection.close()
            self.connection = None
            raise
