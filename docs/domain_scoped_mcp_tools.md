# Domain-Scoped MCP Tools

The Python agent now selects a schema domain before loading schema context. To reduce hallucination, the Node MCP server should expose domain-scoped schema tools that return only the collections and relationships relevant to that ERP area.

## Recommended Domains

- `technician_hr`: technicians, users, employees, branches, designations, attendance, leave, salaries.
- `service_operations`: services, tickets, jobs, visits, complaints, assignments, schedules.
- `customers_locations`: clients, customers, sites, areas, locations, contacts, addresses.
- `finance_inventory`: invoices, payments, sales, purchases, products, stock, vendors.
- `general`: compact global index only.

## Tools To Expose

```text
get_schema_catalog_by_domain(domain)
get_relationship_map_by_domain(domain)
```

Aliases also work:

```text
get_schema_catalog_for_domain(domain)
get_relationship_map_for_domain(domain)
```

If these tools are not present, the Python agent falls back to the current full-schema tools:

```text
get_schema_catalog()
get_relationship_map()
```

## Expected Behavior

For a query like:

```text
give me designation detail about aditiarea3
```

The agent selects `technician_hr`, then Node should return related collections such as:

```text
technicians
technician_designations
branches
users/employees, if used by references
```

The relationship map should include the real link fields between `technician_designations` and `technicians`, for example:

```json
{
  "from": "technician_designations",
  "localField": "technician",
  "to": "technicians",
  "foreignField": "_id"
}
```

This keeps planner context small and makes the final query target the requested collection instead of stopping at the lookup collection.
