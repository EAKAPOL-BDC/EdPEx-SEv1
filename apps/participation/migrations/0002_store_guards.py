from django.db import migrations

SQL = r"""
CREATE FUNCTION nexora_participation_guard() RETURNS trigger AS $$
DECLARE p participation_receiptpolicy; c participation_verifierclient;
        r participation_participationreceipt; binding_scope uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Participation records require the controlled retention workflow' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME='participation_receiptpolicy' THEN
        IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'enabled') IS DISTINCT FROM (to_jsonb(OLD)-'enabled') THEN
            RAISE EXCEPTION 'Receipt policy terms are immutable' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    ELSIF TG_TABLE_NAME='participation_verifierclient' THEN
        IF NEW.key_hash !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid verifier hash' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' AND (NEW.id<>OLD.id OR NEW.scope_id<>OLD.scope_id OR NEW.realm<>OLD.realm) THEN
            RAISE EXCEPTION 'Stable verifier scope and realm' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    ELSIF TG_TABLE_NAME='participation_participationreceipt' THEN
        IF NEW.token_hash !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid receipt hash' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-'revoked') IS DISTINCT FROM (to_jsonb(OLD)-'revoked') OR (OLD.revoked AND NOT NEW.revoked)) THEN
            RAISE EXCEPTION 'Receipt immutable except irreversible revocation' USING ERRCODE='23514';
        END IF;
        SELECT * INTO p FROM participation_receiptpolicy WHERE id=NEW.policy_id;
        IF TG_OP='INSERT' AND (NOT p.enabled OR p.expires_at<=CURRENT_TIMESTAMP) THEN
            RAISE EXCEPTION 'Receipt policy unavailable' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    ELSIF TG_TABLE_NAME='participation_verifiergrant' THEN
        IF TG_OP='UPDATE' AND (NEW.client_id<>OLD.client_id OR NEW.policy_id<>OLD.policy_id OR NEW.purpose<>OLD.purpose) THEN
            RAISE EXCEPTION 'Stable grant identity' USING ERRCODE='23514';
        END IF;
        SELECT * INTO c FROM participation_verifierclient WHERE id=NEW.client_id;
        SELECT * INTO p FROM participation_receiptpolicy WHERE id=NEW.policy_id;
    ELSE
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Redemption is immutable' USING ERRCODE='23514'; END IF;
        IF NEW.idempotency_hash !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid idempotency hash' USING ERRCODE='23514'; END IF;
        SELECT * INTO c FROM participation_verifierclient WHERE id=NEW.client_id;
        SELECT * INTO r FROM participation_participationreceipt WHERE id=NEW.receipt_id;
        SELECT * INTO p FROM participation_receiptpolicy WHERE id=r.policy_id;
        IF r.revoked OR NOT p.enabled OR p.expires_at<=CURRENT_TIMESTAMP OR NOT c.active OR c.expires_at<=CURRENT_TIMESTAMP
           OR NOT EXISTS(SELECT 1 FROM participation_verifiergrant g WHERE g.client_id=c.id AND g.policy_id=p.id
                         AND g.purpose=NEW.purpose AND g.active AND g.can_redeem) THEN
            RAISE EXCEPTION 'Receipt or verifier unavailable' USING ERRCODE='23514';
        END IF;
    END IF;
    SELECT cr.scope_id INTO binding_scope FROM rounds_roundinstrument ri
        JOIN rounds_collectionround cr ON cr.id=ri.collection_round_id WHERE ri.id=p.binding_id;
    IF c.scope_id IS DISTINCT FROM binding_scope OR c.realm IS DISTINCT FROM p.realm
       OR (NEW.purpose='workload' AND NOT p.workload) OR (NEW.purpose='prize' AND NOT p.prize) THEN
        RAISE EXCEPTION 'Grant must match receipt scope realm and purpose' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
TABLES = ['receiptpolicy', 'participationreceipt', 'verifierclient', 'verifiergrant', 'receiptredemption']
for table in TABLES:
    SQL += f'CREATE TRIGGER participation_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_{table} FOR EACH ROW EXECUTE FUNCTION nexora_participation_guard();\n'
REVERSE = '\n'.join(f'DROP TRIGGER participation_{table}_guard ON participation_{table};' for table in TABLES)
REVERSE += '\nDROP FUNCTION nexora_participation_guard();'

class Migration(migrations.Migration):
    dependencies = [('participation', '0001_initial')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
