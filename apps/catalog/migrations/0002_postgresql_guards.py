"""PostgreSQL invariants frozen in Django migration history."""
from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION catalog_assert_bundle_complete(bundle_uuid uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v uuid; curated boolean;
BEGIN
  SELECT b.instrument_version_id, iv.instructions_curated INTO v, curated
  FROM catalog_translationbundle b JOIN catalog_instrumentversion iv ON iv.id=b.instrument_version_id WHERE b.id=bundle_uuid;
  IF NOT curated OR NOT EXISTS (SELECT 1 FROM catalog_instrumentcontent WHERE version_id=v AND active AND audience='respondent' AND kind='instruction') THEN
    RAISE EXCEPTION 'Respondent instructions require curation' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    WITH required_content AS (
      SELECT question_id||'.text' AS key,text_th AS original FROM catalog_question WHERE version_id=v AND active AND audience='respondent'
      UNION ALL
      SELECT q.question_id||'.option.'||o.code,o.label_th FROM catalog_questionoption o JOIN catalog_question q ON q.id=o.question_id WHERE q.version_id=v AND q.active AND q.audience='respondent'
      UNION ALL
      SELECT content_key,text_th FROM catalog_instrumentcontent WHERE version_id=v AND active AND audience='respondent' AND kind<>'source_section'
    )
    SELECT 1 FROM required_content r CROSS JOIN (VALUES ('th'),('en')) AS locales(locale)
    LEFT JOIN catalog_contenttranslation t ON t.bundle_id=bundle_uuid AND t.content_key=r.key AND t.locale=locales.locale
    WHERE t.id IS NULL OR t.status<>'approved' OR trim(t.text)='' OR t.reviewed_by_id IS NULL OR t.reviewed_at IS NULL
      OR t.source_hash<>encode(sha256(convert_to(r.original,'UTF8')),'hex') OR (t.locale='th' AND t.text<>r.original)
  ) THEN
    RAISE EXCEPTION 'Translation coverage or approval is incomplete' USING ERRCODE='23514';
  END IF;
END $$;

CREATE FUNCTION catalog_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE instrument_code text; bundle_uuid uuid; lineage_id uuid; lineage_instrument uuid; visited uuid[];
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.status<>'draft' OR EXISTS(SELECT 1 FROM catalog_translationbundle WHERE instrument_version_id=OLD.id AND status<>'draft') THEN
      RAISE EXCEPTION 'Published instrument version cannot be deleted' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  SELECT code INTO instrument_code FROM catalog_instrument WHERE id=NEW.instrument_id;
  lineage_id := NEW.based_on_id;
  visited := ARRAY[NEW.id];
  WHILE lineage_id IS NOT NULL LOOP
    IF lineage_id=ANY(visited) THEN RAISE EXCEPTION 'Version lineage cannot contain cycles' USING ERRCODE='23514'; END IF;
    visited := array_append(visited,lineage_id);
    SELECT instrument_id,based_on_id INTO lineage_instrument,lineage_id FROM catalog_instrumentversion WHERE id=lineage_id;
    IF NOT FOUND OR lineage_instrument<>NEW.instrument_id THEN RAISE EXCEPTION 'Version lineage must share an instrument' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF instrument_code='F06' AND (NEW.assessment_method<>'self_report' OR NEW.evidence_required OR NEW.assessor_scoring OR NEW.workflow ?| ARRAY['verified','rejected','assessor_scored']) THEN
    RAISE EXCEPTION 'F06 must remain self-report without mandatory evidence or assessors' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.instrument_id<>NEW.instrument_id OR OLD.version<>NEW.version OR OLD.based_on_id IS DISTINCT FROM NEW.based_on_id THEN
      RAISE EXCEPTION 'Version identity cannot change' USING ERRCODE='23514';
    END IF;
    IF OLD.status<>'draft' THEN
      IF NOT (OLD.status='published' AND NEW.status='retired' AND (to_jsonb(OLD)-'status')=(to_jsonb(NEW)-'status')) THEN
        RAISE EXCEPTION 'Published instrument version is immutable' USING ERRCODE='23514';
      END IF;
    ELSIF EXISTS(SELECT 1 FROM catalog_translationbundle WHERE instrument_version_id=OLD.id AND status='published')
      AND (to_jsonb(OLD)-ARRAY['status','checksum','published_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['status','checksum','published_at']) THEN
      RAISE EXCEPTION 'Source with a published bundle is immutable' USING ERRCODE='23514';
    END IF;
    IF OLD.status='draft' AND NEW.status='draft'
      AND (to_jsonb(OLD)-ARRAY['status','checksum','published_at','created_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['status','checksum','published_at','created_at']) THEN
      UPDATE catalog_contenttranslation SET status='stale',reviewed_by_id=NULL,reviewed_at=NULL
        WHERE bundle_id IN (SELECT id FROM catalog_translationbundle WHERE instrument_version_id=NEW.id AND status='draft');
    END IF;
  END IF;
  IF NEW.status='published' AND (TG_OP='INSERT' OR OLD.status='draft') THEN
    IF NOT EXISTS(SELECT 1 FROM catalog_question WHERE version_id=NEW.id AND active) THEN
      RAISE EXCEPTION 'Publication requires questions' USING ERRCODE='23514';
    END IF;
    SELECT id INTO bundle_uuid FROM catalog_translationbundle WHERE instrument_version_id=NEW.id AND status='published' LIMIT 1;
    IF bundle_uuid IS NULL THEN RAISE EXCEPTION 'Publication requires approved bilingual bundle' USING ERRCODE='23514'; END IF;
    PERFORM catalog_assert_bundle_complete(bundle_uuid);
    IF EXISTS(SELECT 1 FROM catalog_indicatorbinding b JOIN catalog_formulaversion f ON f.id=b.formula_id WHERE b.version_id=NEW.id AND f.status<>'published') THEN
      RAISE EXCEPTION 'Publication requires frozen formulas' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_version_immutable BEFORE INSERT OR UPDATE OR DELETE ON catalog_instrumentversion FOR EACH ROW EXECUTE FUNCTION catalog_version_guard();

CREATE FUNCTION catalog_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row_data jsonb; v uuid; state text; code text; binding_scope uuid; formula_scope uuid; indicator_scope uuid;
BEGIN
  row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  IF TG_OP='UPDATE' AND (
    (to_jsonb(OLD)->>TG_ARGV[0]) IS DISTINCT FROM (to_jsonb(NEW)->>TG_ARGV[0]) OR
    (TG_NARGS>1 AND (to_jsonb(OLD)->>TG_ARGV[1]) IS DISTINCT FROM (to_jsonb(NEW)->>TG_ARGV[1]))
  ) THEN RAISE EXCEPTION 'Content stable ID or parent cannot change' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='catalog_questionoption' THEN
    SELECT version_id INTO v FROM catalog_question WHERE id=(row_data->>'question_id')::uuid;
  ELSIF TG_TABLE_NAME='catalog_bindingquestion' THEN
    SELECT version_id INTO v FROM catalog_indicatorbinding WHERE id=(row_data->>'binding_id')::uuid;
    IF TG_OP<>'DELETE' AND v<>(SELECT version_id FROM catalog_question WHERE id=(row_data->>'question_id')::uuid) THEN
      RAISE EXCEPTION 'Binding question must share the instrument version' USING ERRCODE='23514';
    END IF;
  ELSE v := (row_data->>'version_id')::uuid;
  END IF;
  SELECT iv.status,i.code,i.scope_id INTO state,code,binding_scope FROM catalog_instrumentversion iv JOIN catalog_instrument i ON i.id=iv.instrument_id WHERE iv.id=v FOR UPDATE OF iv;
  IF state<>'draft' OR EXISTS(SELECT 1 FROM catalog_translationbundle WHERE instrument_version_id=v AND status='published') THEN
    RAISE EXCEPTION 'Published catalog content is immutable' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME='catalog_question' AND TG_OP<>'DELETE' THEN
    IF left(NEW.question_id,4)<>code||'-' THEN RAISE EXCEPTION 'Question belongs to another instrument' USING ERRCODE='23514'; END IF;
    IF code='F06' AND NEW.answer_type IN ('evidence_reference','review_metadata','assessor_score') THEN
      RAISE EXCEPTION 'F06 assessor/evidence fields forbidden' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_TABLE_NAME='catalog_indicatorbinding' AND TG_OP<>'DELETE' THEN
    SELECT scope_id INTO indicator_scope FROM catalog_indicator WHERE id=NEW.indicator_id;
    SELECT scope_id INTO formula_scope FROM catalog_formulaversion WHERE id=NEW.formula_id;
    IF binding_scope<>indicator_scope OR binding_scope<>formula_scope THEN RAISE EXCEPTION 'Indicator binding crosses scopes' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('catalog_question','catalog_questionoption','catalog_instrumentcontent') AND to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN
    UPDATE catalog_contenttranslation SET status='stale',reviewed_by_id=NULL,reviewed_at=NULL
      WHERE bundle_id IN (SELECT id FROM catalog_translationbundle WHERE instrument_version_id=v AND status='draft');
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_question_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_question FOR EACH ROW EXECUTE FUNCTION catalog_content_guard('version_id','question_id');
CREATE TRIGGER catalog_option_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_questionoption FOR EACH ROW EXECUTE FUNCTION catalog_content_guard('question_id','code');
CREATE TRIGGER catalog_content_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_instrumentcontent FOR EACH ROW EXECUTE FUNCTION catalog_content_guard('version_id','content_key');
CREATE TRIGGER catalog_binding_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_indicatorbinding FOR EACH ROW EXECUTE FUNCTION catalog_content_guard('version_id','indicator_id');
CREATE TRIGGER catalog_binding_question_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_bindingquestion FOR EACH ROW EXECUTE FUNCTION catalog_content_guard('binding_id','question_id');

CREATE FUNCTION catalog_bundle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' AND NEW.status<>'draft' THEN RAISE EXCEPTION 'New bundles must be drafts' USING ERRCODE='23514'; END IF;
  IF TG_OP<>'INSERT' AND OLD.status<>'draft' THEN RAISE EXCEPTION 'Published bundle is immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.instrument_version_id<>NEW.instrument_version_id OR OLD.bundle_version<>NEW.bundle_version THEN RAISE EXCEPTION 'Bundle identity cannot change' USING ERRCODE='23514'; END IF;
    IF NEW.status='published' THEN
      PERFORM 1 FROM catalog_instrumentversion WHERE id=NEW.instrument_version_id FOR UPDATE;
      PERFORM catalog_assert_bundle_complete(NEW.id);
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_bundle_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_translationbundle FOR EACH ROW EXECUTE FUNCTION catalog_bundle_guard();

CREATE FUNCTION catalog_translation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b uuid; state text;
BEGIN
  b := CASE WHEN TG_OP='DELETE' THEN OLD.bundle_id ELSE NEW.bundle_id END;
  SELECT status INTO state FROM catalog_translationbundle WHERE id=b FOR UPDATE;
  IF state<>'draft' THEN RAISE EXCEPTION 'Published translation is immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.bundle_id<>NEW.bundle_id OR OLD.content_key<>NEW.content_key OR OLD.locale<>NEW.locale THEN RAISE EXCEPTION 'Translation identity cannot change' USING ERRCODE='23514'; END IF;
    IF OLD.text<>NEW.text AND NEW.status='approved' THEN RAISE EXCEPTION 'Edited translation needs review' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_translation_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_contenttranslation FOR EACH ROW EXECUTE FUNCTION catalog_translation_guard();

CREATE FUNCTION catalog_identity_formula_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='catalog_formulaversion' AND TG_OP<>'INSERT' THEN
    IF OLD.status<>'draft' THEN RAISE EXCEPTION 'Published formula is immutable' USING ERRCODE='23514'; END IF;
    IF TG_OP='UPDATE' AND (OLD.scope_id<>NEW.scope_id OR OLD.key<>NEW.key OR OLD.version<>NEW.version) THEN RAISE EXCEPTION 'Formula identity cannot change' USING ERRCODE='23514'; END IF;
  ELSIF TG_OP='UPDATE' THEN
    IF OLD.scope_id<>NEW.scope_id OR OLD.code<>NEW.code THEN RAISE EXCEPTION 'Catalog identity cannot move scopes or codes' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_formula_frozen BEFORE UPDATE OR DELETE ON catalog_formulaversion FOR EACH ROW EXECUTE FUNCTION catalog_identity_formula_guard();
CREATE TRIGGER catalog_instrument_identity BEFORE UPDATE ON catalog_instrument FOR EACH ROW EXECUTE FUNCTION catalog_identity_formula_guard();
CREATE TRIGGER catalog_indicator_identity BEFORE UPDATE ON catalog_indicator FOR EACH ROW EXECUTE FUNCTION catalog_identity_formula_guard();

CREATE FUNCTION catalog_label_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP<>'INSERT' AND OLD.published THEN RAISE EXCEPTION 'Published label is immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  IF TG_OP='INSERT' AND NEW.published THEN RAISE EXCEPTION 'New labels must be unpublished' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.scope_id<>NEW.scope_id OR OLD.namespace<>NEW.namespace OR OLD.key<>NEW.key OR OLD.version<>NEW.version THEN
      RAISE EXCEPTION 'Label identity cannot change' USING ERRCODE='23514';
    END IF;
    IF OLD.source_th<>NEW.source_th OR OLD.text_en<>NEW.text_en THEN
      NEW.status := CASE WHEN OLD.source_th<>NEW.source_th THEN 'stale' ELSE 'needs_review' END;
      NEW.reviewed_by_id := NULL; NEW.reviewed_at := NULL;
      NEW.source_hash := encode(sha256(convert_to(NEW.source_th,'UTF8')),'hex');
    END IF;
  END IF;
  IF NEW.status='approved' AND (trim(NEW.source_th)='' OR trim(NEW.text_en)='' OR NEW.source_hash<>encode(sha256(convert_to(NEW.source_th,'UTF8')),'hex')) THEN
    RAISE EXCEPTION 'Approved label must match current nonempty source pair' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER catalog_label_frozen BEFORE INSERT OR UPDATE OR DELETE ON catalog_localizedlabel FOR EACH ROW EXECUTE FUNCTION catalog_label_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS catalog_label_frozen ON catalog_localizedlabel;
DROP FUNCTION IF EXISTS catalog_label_guard();
DROP TRIGGER IF EXISTS catalog_indicator_identity ON catalog_indicator;
DROP TRIGGER IF EXISTS catalog_instrument_identity ON catalog_instrument;
DROP TRIGGER IF EXISTS catalog_formula_frozen ON catalog_formulaversion;
DROP TRIGGER IF EXISTS catalog_translation_frozen ON catalog_contenttranslation;
DROP TRIGGER IF EXISTS catalog_bundle_frozen ON catalog_translationbundle;
DROP TRIGGER IF EXISTS catalog_binding_question_frozen ON catalog_bindingquestion;
DROP TRIGGER IF EXISTS catalog_binding_frozen ON catalog_indicatorbinding;
DROP TRIGGER IF EXISTS catalog_content_frozen ON catalog_instrumentcontent;
DROP TRIGGER IF EXISTS catalog_option_frozen ON catalog_questionoption;
DROP TRIGGER IF EXISTS catalog_question_frozen ON catalog_question;
DROP TRIGGER IF EXISTS catalog_version_immutable ON catalog_instrumentversion;
DROP FUNCTION IF EXISTS catalog_identity_formula_guard();
DROP FUNCTION IF EXISTS catalog_translation_guard();
DROP FUNCTION IF EXISTS catalog_bundle_guard();
DROP FUNCTION IF EXISTS catalog_content_guard();
DROP FUNCTION IF EXISTS catalog_version_guard();
DROP FUNCTION IF EXISTS catalog_assert_bundle_complete(uuid);
"""

class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
