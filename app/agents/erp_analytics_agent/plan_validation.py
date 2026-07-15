import json
from typing import Any


SCHEMA_FIELD_KEYS = {"fields", "schema", "properties", "columns"}
SCHEMA_COLLECTION_CONTAINERS = {"collections", "schema_catalog"}
AGGREGATION_STAGE_OPERATORS = {
    "$addFields",
    "$count",
    "$group",
    "$limit",
    "$lookup",
    "$match",
    "$project",
    "$set",
    "$skip",
    "$sort",
    "$unwind",
}


def _mcp_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    content = value.get("content")
    if not isinstance(content, list) or not content:
        return value

    first_item = content[0]
    if not isinstance(first_item, dict) or first_item.get("type") != "text":
        return value

    text = first_item.get("text")
    if not isinstance(text, str):
        return value

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _looks_like_collection_definition(value: Any) -> bool:
    return isinstance(value, dict) and any(
        key in value for key in ("fields", "schema", "sample", "indexes", "relationships", "collectionName")
    )


def _field_names_from_definition(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()

    fields = None
    for key in SCHEMA_FIELD_KEYS:
        if key in value:
            fields = value[key]
            break

    names: set[str] = {"_id"}
    if isinstance(fields, dict):
        names.update(str(key) for key in fields.keys())
    elif isinstance(fields, list):
        for field in fields:
            if isinstance(field, str):
                names.add(field)
            elif isinstance(field, dict):
                name = field.get("name") or field.get("field") or field.get("key")
                if name:
                    names.add(str(name))
    return names


def collection_fields(schema_catalog: Any) -> dict[str, set[str]]:
    payload = _mcp_payload(schema_catalog)
    collections: dict[str, set[str]] = {}

    def visit(node: Any, key_name: str | None = None, in_collection_container: bool = False) -> None:
        if isinstance(node, dict):
            child_is_collection = _looks_like_collection_definition(node)
            collection_name = node.get("collectionName") if isinstance(node.get("collectionName"), str) else key_name
            if (
                collection_name
                and collection_name not in SCHEMA_COLLECTION_CONTAINERS
                and (in_collection_container or child_is_collection)
            ):
                fields = _field_names_from_definition(node)
                if fields:
                    collections[collection_name] = fields
            for key, child in node.items():
                visit(child, str(key), in_collection_container=str(key) in SCHEMA_COLLECTION_CONTAINERS)
        elif isinstance(node, list):
            for child in node:
                visit(child, key_name, in_collection_container=in_collection_container)

    visit(payload)
    return collections


def _field_head(field_name: str) -> str:
    return field_name.lstrip("$").split(".", 1)[0]


def _is_known_field(field_name: str, available_fields: set[str]) -> bool:
    head = _field_head(field_name)
    return head in available_fields or field_name in available_fields


def _collect_field_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        if value.startswith("$") and not value.startswith("$$"):
            refs.add(value.lstrip("$"))
        return refs

    if isinstance(value, list):
        for item in value:
            refs.update(_collect_field_refs(item))
        return refs

    if isinstance(value, dict):
        if any(isinstance(key, str) and key.startswith("$") for key in value.keys()):
            for child in value.values():
                refs.update(_collect_field_refs(child))
            return refs
        for key, child in value.items():
            refs.update(_collect_field_refs(child))
        return refs

    return refs


def _collect_query_field_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, list):
        for item in value:
            refs.update(_collect_query_field_refs(item))
        return refs

    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.startswith("$"):
                refs.update(_collect_query_field_refs(child))
            elif isinstance(key, str):
                refs.add(key)
                refs.update(_collect_query_field_refs(child))
        return refs

    return refs


def _validate_field_refs(
    errors: list[str],
    collection_name: str,
    field_refs: set[str],
    available_fields: set[str],
    context: str,
) -> None:
    for field_ref in sorted(field_refs):
        if field_ref.startswith("$") or not field_ref:
            continue
        if "." in field_ref and _field_head(field_ref) not in available_fields:
            errors.append(f"{context} uses unknown field '{field_ref}' on collection '{collection_name}'")
        elif "." not in field_ref and not _is_known_field(field_ref, available_fields):
            errors.append(f"{context} uses unknown field '{field_ref}' on collection '{collection_name}'")


def _validate_find_arguments(
    errors: list[str],
    collection_name: str,
    arguments: dict[str, Any],
    schema_fields: dict[str, set[str]],
) -> None:
    available_fields = schema_fields.get(collection_name, set())
    if not available_fields:
        return

    filter_refs = _collect_query_field_refs(arguments.get("filter") or {})
    projection_refs = {
        key for key in (arguments.get("projection") or {}).keys() if isinstance(key, str) and not key.startswith("$")
    }
    sort_refs = {key for key in (arguments.get("sort") or {}).keys() if isinstance(key, str) and not key.startswith("$")}
    _validate_field_refs(errors, collection_name, filter_refs, available_fields, "find filter")
    _validate_field_refs(errors, collection_name, projection_refs, available_fields, "find projection")
    _validate_field_refs(errors, collection_name, sort_refs, available_fields, "find sort")


def _projected_fields(stage: dict[str, Any], previous_fields: set[str]) -> set[str]:
    projection = stage.get("$project")
    if not isinstance(projection, dict):
        return previous_fields

    excluded = {key for key, value in projection.items() if value in (0, False)}
    included_or_computed = {key for key, value in projection.items() if value not in (0, False)}
    if included_or_computed:
        return set(included_or_computed)
    return previous_fields - excluded


def _validate_aggregation_arguments(
    errors: list[str],
    collection_name: str,
    arguments: dict[str, Any],
    schema_fields: dict[str, set[str]],
) -> None:
    available_fields = set(schema_fields.get(collection_name, set()))
    if not available_fields:
        return

    pipeline = arguments.get("pipeline")
    if not isinstance(pipeline, list):
        errors.append("aggregation pipeline must be a list")
        return

    for index, stage in enumerate(pipeline):
        if not isinstance(stage, dict) or not stage:
            errors.append(f"aggregation stage {index} must be a non-empty object")
            continue

        stage_operator = next(iter(stage.keys()))
        if stage_operator not in AGGREGATION_STAGE_OPERATORS:
            errors.append(f"aggregation stage {index} uses unsupported or invalid operator '{stage_operator}'")
            continue

        context = f"aggregation stage {index} {stage_operator}"
        if stage_operator == "$match":
            refs = _collect_query_field_refs(stage.get("$match") or {})
            _validate_field_refs(errors, collection_name, refs, available_fields, context)
        elif stage_operator == "$sort":
            refs = {key for key in (stage.get("$sort") or {}).keys() if isinstance(key, str) and not key.startswith("$")}
            _validate_field_refs(errors, collection_name, refs, available_fields, context)
        elif stage_operator == "$lookup":
            lookup = stage.get("$lookup")
            if not isinstance(lookup, dict):
                errors.append(f"{context} must be an object")
                continue
            from_collection = lookup.get("from")
            if isinstance(from_collection, str) and from_collection not in schema_fields:
                errors.append(f"{context} references unknown lookup collection '{from_collection}'")
            local_field = lookup.get("localField")
            if isinstance(local_field, str):
                _validate_field_refs(errors, collection_name, {local_field}, available_fields, context)
            foreign_field = lookup.get("foreignField")
            if isinstance(from_collection, str) and isinstance(foreign_field, str) and from_collection in schema_fields:
                _validate_field_refs(errors, from_collection, {foreign_field}, schema_fields[from_collection], context)
            as_field = lookup.get("as")
            if isinstance(as_field, str) and as_field:
                available_fields.add(_field_head(as_field))
        elif stage_operator in {"$addFields", "$set"}:
            new_fields = stage.get(stage_operator)
            if isinstance(new_fields, dict):
                _validate_field_refs(errors, collection_name, _collect_field_refs(new_fields), available_fields, context)
                available_fields.update(str(key) for key in new_fields.keys())
        elif stage_operator == "$project":
            projection = stage.get("$project")
            if isinstance(projection, dict):
                refs = set()
                for key, value in projection.items():
                    if value in (1, True):
                        refs.add(str(key))
                    elif value not in (0, False):
                        refs.update(_collect_field_refs(value))
                _validate_field_refs(errors, collection_name, refs, available_fields, context)
                available_fields = _projected_fields(stage, available_fields)
        elif stage_operator == "$group":
            group = stage.get("$group")
            if isinstance(group, dict):
                refs = _collect_field_refs(group.get("_id"))
                for key, value in group.items():
                    if key != "_id":
                        refs.update(_collect_field_refs(value))
                _validate_field_refs(errors, collection_name, refs, available_fields, context)
                available_fields = {"_id", *(str(key) for key in group.keys() if key != "_id")}
        elif stage_operator == "$count":
            count_field = stage.get("$count")
            available_fields = {count_field} if isinstance(count_field, str) else {"count"}


def validate_query_plan(plan: dict[str, Any], schema_catalog: Any) -> list[str]:
    schema_fields = collection_fields(schema_catalog)
    if not schema_fields:
        return []

    errors: list[str] = []

    def validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> None:
        collection_name = arguments.get("collectionName")
        if not isinstance(collection_name, str) or not collection_name:
            errors.append(f"{tool_name} is missing collectionName")
            return
        if collection_name not in schema_fields:
            errors.append(f"{tool_name} references unknown collection '{collection_name}'")
            return
        if tool_name == "run_find_query":
            _validate_find_arguments(errors, collection_name, arguments, schema_fields)
        elif tool_name == "run_aggregation_query":
            _validate_aggregation_arguments(errors, collection_name, arguments, schema_fields)

    tool = plan.get("tool")
    if tool in {"run_find_query", "run_aggregation_query"}:
        arguments = plan.get("arguments")
        if isinstance(arguments, dict):
            validate_tool_call(tool, arguments)
    elif tool == "multi_step_plan":
        for index, step in enumerate(plan.get("steps") or []):
            if not isinstance(step, dict):
                errors.append(f"multi_step_plan step {index} must be an object")
                continue
            step_tool = step.get("tool")
            step_arguments = step.get("arguments")
            if step_tool not in {"run_find_query", "run_aggregation_query"} or not isinstance(step_arguments, dict):
                errors.append(f"multi_step_plan step {index} has an invalid tool or arguments")
                continue
            validate_tool_call(step_tool, step_arguments)

    return list(dict.fromkeys(errors))
