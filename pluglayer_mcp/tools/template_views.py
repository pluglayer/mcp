"""Compact discovery views; schemas and authorization remain backend-owned."""


def schema_view(data: dict, section: str) -> dict:
    schemas = data.get("schemas", {})
    if section == "summary":
        return {"sections": list(schemas), "lifecycle": data.get("lifecycle", {}),
                "next": "Call get_template_authoring_schema(section=<name>) for a complete schema including its $defs."}
    if section not in schemas:
        raise ValueError(f"Unknown schema section; choose one of: {', '.join(schemas)}")
    return {"schemas": {section: schemas[section]}, "lifecycle": data.get("lifecycle", {})}


def context_view(data: dict, section: str, offset: int, limit: int) -> dict:
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 50")
    if section == "summary":
        return {"sections": {key: len(value) if isinstance(value, list) else None for key, value in data.items()},
                "next": "Select a section with offset/limit; use get_template_details for full template content."}
    if section not in data or not isinstance(data[section], list):
        raise ValueError(f"Unknown list section; choose one of: {', '.join(data)}")
    values = data[section]
    page = values[offset:offset + limit]
    if section == "templates":
        keys = ("id", "slug", "name", "description", "category", "version")
        page = [{key: item[key] for key in keys if key in item} for item in page]
    return {section: page, "total": len(values), "offset": offset,
            "next_offset": offset + limit if offset + limit < len(values) else None}
