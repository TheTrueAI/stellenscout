When adding a new function to `immermatch/db.py`:

1. **Always use `get_admin_client()`** for DB operations (bypasses RLS)
2. **Never use the anon client** (`get_client()`) for writes
3. **Log subscriber UUIDs**, never email addresses:
   ```python
   logger.info("Updated subscriber sub=%s", subscriber_id)
   ```
4. **Follow the existing pattern** — most functions look like:
   ```python
   def my_function(param: str) -> ReturnType | None:
       client = get_admin_client()
       result = client.table("table_name").select("*").eq("col", param).execute()
       if not result.data:
           return None
       return result.data[0]
   ```
5. **Add tests in `tests/test_db.py`** — mock at the Supabase client level:
   ```python
   @patch("immermatch.db.get_admin_client")
   def test_my_function(mock_client):
       mock_table = MagicMock()
       mock_client.return_value.table.return_value = mock_table
       mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[...])
   ```
6. **Update `AGENTS.md` §11** if the function is part of the public API (subscriber lifecycle, job operations)
