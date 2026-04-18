create or replace function app_touch_dashboard(user_id text)
returns text
language plpgsql
as $$
begin
  return user_id;
end;
$$;

create or replace function app_refresh_dashboard(user_id text)
returns text
language plpgsql
as $$
begin
  perform app_touch_dashboard(user_id);
  return user_id;
end;
$$;

create materialized view app_dashboard_view as
select app_refresh_dashboard('seed') as dashboard_id;
