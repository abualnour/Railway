# NourAxis REST API

The NourAxis API is available under `/api/v1/` and uses Django REST Framework.

## Authentication

The API uses Django session authentication.

- Authentication class: `SessionAuthentication`
- Default permission: authenticated users only
- Pagination: page number pagination
- Page size: 25 records per page

Use an authenticated browser session or a client that sends the same session cookie and CSRF rules required by Django.

## Pagination Format

List endpoints return DRF paginated responses:

```json
{
  "count": 100,
  "next": "https://example.com/api/v1/employees/?page=2",
  "previous": null,
  "results": []
}
```

## Employees

### List employees

```http
GET /api/v1/employees/
```

Returns a paginated list of employees with compact display fields:

- `id`
- `employee_id`
- `full_name`
- `branch`
- `department`
- `job_title`
- `employment_status`
- `photo_url`

### Retrieve employee detail

```http
GET /api/v1/employees/<id>/
```

Returns the full employee model payload for the selected employee.

## Employee Leave

### List leave records

```http
GET /api/v1/employees/leaves/
```

Returns paginated leave records with employee display fields, leave type/status labels, workflow stage, requester/reviewer IDs, and timestamps.

### Retrieve leave detail

```http
GET /api/v1/employees/leaves/<id>/
```

Returns one leave record.

## Payroll Lines

### List payroll lines

```http
GET /api/v1/employees/payroll-lines/
```

Returns paginated payroll lines with employee display fields, payroll period title, salary components, PIFSS values, gross total, total deductions, and net pay.

### Retrieve payroll line detail

```http
GET /api/v1/employees/payroll-lines/<id>/
```

Returns one payroll line.

## Notes

- These endpoints are read-only.
- No migrations are required for the API layer.
- The API currently uses the system-wide authenticated session permission. Add role-scoped API permissions later if external integrations need stricter access boundaries.
