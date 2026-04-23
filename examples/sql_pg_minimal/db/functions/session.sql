CREATE OR REPLACE FUNCTION app.normalize_user_name(user_name text)
RETURNS text
AS $$
BEGIN
  RETURN lower(trim(user_name));
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.issue_session_token(user_name text)
RETURNS text
AS $$
DECLARE
  normalized_name text;
BEGIN
  SELECT app.normalize_user_name(user_name) INTO normalized_name;
  RETURN normalized_name || '-token';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.audit_session_trigger()
RETURNS trigger
AS $$
BEGIN
  PERFORM app.issue_session_token(NEW.user_name);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER session_audit_trigger
AFTER INSERT ON app.sessions
FOR EACH ROW
EXECUTE FUNCTION app.audit_session_trigger();

-- stage5 demo marker: baseline
