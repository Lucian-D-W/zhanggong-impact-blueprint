CREATE OR REPLACE FUNCTION app.normalize_user_name(user_name text)
RETURNS text
AS $$
BEGIN
  RETURN lower(trim(user_name));
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.get_session_label(user_name text)
RETURNS text
AS $$
DECLARE
  normalized_name text;
BEGIN
  SELECT app.normalize_user_name(user_name) INTO normalized_name;
  RETURN normalized_name || '-label';
END;
$$ LANGUAGE plpgsql;
