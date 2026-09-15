"""Add monotonic review revisions without changing existing approved content."""
from django.db import migrations, models


FORWARD_SQL = r"""
CREATE FUNCTION catalog_review_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Always advance, including invalidation and A -> B -> A edits. Clients cannot
  -- supply a previous revision through ORM bulk updates or direct SQL.
  IF TG_OP='INSERT' THEN
    NEW.review_revision := 1;
  ELSE
    NEW.review_revision := OLD.review_revision + 1;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_translation_review_revision BEFORE INSERT OR UPDATE ON catalog_contenttranslation
  FOR EACH ROW EXECUTE FUNCTION catalog_review_revision_guard();
CREATE TRIGGER catalog_label_review_revision BEFORE INSERT OR UPDATE ON catalog_localizedlabel
  FOR EACH ROW EXECUTE FUNCTION catalog_review_revision_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER catalog_translation_review_revision ON catalog_contenttranslation;
DROP TRIGGER catalog_label_review_revision ON catalog_localizedlabel;
DROP FUNCTION catalog_review_revision_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_postgresql_guards")]
    operations = [
        migrations.AddField(
            model_name="contenttranslation", name="review_revision",
            field=models.PositiveBigIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name="localizedlabel", name="review_revision",
            field=models.PositiveBigIntegerField(default=1, editable=False),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
