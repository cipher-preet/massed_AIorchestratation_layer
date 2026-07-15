from app.agents.erp_analytics_agent.plan_validation import collection_fields, validate_query_plan


SCHEMA_CATALOG = {
    "collections": {
        "technicians": {
            "fields": {
                "_id": {"type": "ObjectId"},
                "name": {"type": "string"},
                "branchId": {"type": "ObjectId"},
                "createdAt": {"type": "date"},
            }
        },
        "branches": {
            "fields": {
                "_id": {"type": "ObjectId"},
                "name": {"type": "string"},
                "code": {"type": "string"},
            }
        },
        "leaves": {
            "fields": {
                "_id": {"type": "ObjectId"},
                "technicianId": {"type": "ObjectId"},
                "startDate": {"type": "date"},
                "endDate": {"type": "date"},
            }
        },
    }
}


def test_collection_fields_extracts_schema_catalog_collections():
    assert collection_fields(SCHEMA_CATALOG) == {
        "technicians": {"_id", "name", "branchId", "createdAt"},
        "branches": {"_id", "name", "code"},
        "leaves": {"_id", "technicianId", "startDate", "endDate"},
    }


def test_validate_query_plan_rejects_unknown_find_field():
    errors = validate_query_plan(
        {
            "tool": "run_find_query",
            "arguments": {
                "collectionName": "technicians",
                "filter": {"assignedEngineer": "Aditiarea3"},
                "projection": {"name": 1},
                "limit": 10,
            },
        },
        SCHEMA_CATALOG,
    )

    assert errors == ["find filter uses unknown field 'assignedEngineer' on collection 'technicians'"]


def test_validate_query_plan_rejects_unknown_lookup_collection_and_field():
    errors = validate_query_plan(
        {
            "tool": "run_aggregation_query",
            "arguments": {
                "collectionName": "technicians",
                "pipeline": [
                    {
                        "$lookup": {
                            "from": "locations",
                            "localField": "branch",
                            "foreignField": "_id",
                            "as": "branch",
                        }
                    }
                ],
                "limit": 10,
            },
        },
        SCHEMA_CATALOG,
    )

    assert errors == [
        "aggregation stage 0 $lookup references unknown lookup collection 'locations'",
        "aggregation stage 0 $lookup uses unknown field 'branch' on collection 'technicians'",
    ]


def test_validate_query_plan_accepts_computed_date_diff_fields():
    errors = validate_query_plan(
        {
            "tool": "run_aggregation_query",
            "arguments": {
                "collectionName": "leaves",
                "pipeline": [
                    {
                        "$addFields": {
                            "days": {
                                "$dateDiff": {
                                    "startDate": "$startDate",
                                    "endDate": "$endDate",
                                    "unit": "day",
                                }
                            }
                        }
                    },
                    {"$group": {"_id": "$technicianId", "totalDays": {"$sum": "$days"}}},
                    {"$sort": {"totalDays": -1}},
                ],
                "limit": 1,
            },
        },
        SCHEMA_CATALOG,
    )

    assert errors == []
