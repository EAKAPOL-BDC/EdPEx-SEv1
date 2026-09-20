"""One explicitly authorized exception, using the database's shared predicate."""
from django.db import connection

PREFIX='[ADMIN SELF-REVIEW] '
def can_self_review(user, scope):
    if not getattr(user,'pk',None):
        return False
    with connection.cursor() as cursor:
        cursor.execute('SELECT edpex_admin_self_review(%s, %s)',[user.pk,str(scope.pk)])
        return bool(cursor.fetchone()[0])
