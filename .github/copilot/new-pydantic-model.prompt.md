When adding a new Pydantic model to `immermatch/models.py`:

1. **Follow existing patterns** — use `BaseModel` with `Field()` descriptions:
   ```python
   class MyModel(BaseModel):
       name: str = Field(description="Short description of the field")
       items: list[str] = Field(default_factory=list, description="...")
       score: int = Field(ge=0, le=100, description="...")
       status: Literal["active", "inactive"] = "active"
   ```
2. **Use `str | None`** for optional fields (not `Optional[str]` — project uses PEP 604 style)
3. **Default values:** Use `= []` for simple lists, `default_factory=list` for mutable defaults in `Field()`
4. **Add tests in `tests/test_models.py`:**
   - Construction with all fields
   - Construction with defaults only
   - Validation errors for invalid values
   - Round-trip serialization: `MyModel(**model.model_dump())`
5. **Update `AGENTS.md` §6** if the model is part of the pipeline schema
