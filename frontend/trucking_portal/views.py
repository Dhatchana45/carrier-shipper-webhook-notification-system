
from django.contrib import messages
from django.shortcuts import render, redirect

from core.api import api_request, get_api_list
from core.decorators import login_required, role_required


LOAD_STATUSES = [
    "created",
    "assigned",
    "dispatched",
    "at_pickup",
    "picked_up",
    "in_transit",
    "detention",
    "at_delivery",
    "delivered",
    "cancelled",
]


def fetch_list(request, endpoint, label):
    """Fetch authenticated API data and report errors."""

    data, error = get_api_list(request, endpoint)

    if error:
        messages.error(
            request,
            f"Could not load {label}: {error}",
        )
        return []

    return data


def create_record(request, endpoint, redirect_name, page_title, fields):
    """Reusable authenticated create handler."""

    role = request.session.get("api_role", "")

    # --------------------------------------------------
    # Role-based form fields
    # --------------------------------------------------

    fields = list(fields)

    if page_title == "driver" and role == "carrier":
        # Carrier users create drivers under their own organisation.
        fields = [
            field for field in fields
            if field != "carrier_id"
        ]

    if page_title == "load" and role == "shipper":
        # Shipper users create loads under their own organisation.
        # They cannot select a carrier or driver.
        fields = [
            field for field in fields
            if field not in ("shipper_id", "carrier_id", "driver_id")
        ]

    # --------------------------------------------------
    # Dropdown data
    # --------------------------------------------------

    carriers = []
    shippers = []
    drivers = []

    if "carrier_id" in fields:
        carriers = fetch_list(
            request,
            "/carriers/",
            "carriers",
        )

    if "shipper_id" in fields:
        shippers = fetch_list(
            request,
            "/shippers/",
            "shippers",
        )

    if "driver_id" in fields:
        drivers = fetch_list(
            request,
            "/drivers/",
            "drivers",
        )

    # --------------------------------------------------
    # Field labels and validation
    # --------------------------------------------------

    labels = {
        "name": "Name",
        "code": "Code",
        "contact_email": "Contact Email",
        "phone": "Phone",
        "carrier_id": "Carrier",
        "shipper_id": "Shipper",
        "driver_id": "Driver",
        "license_number": "License Number",
        "load_number": "Load Number",
        "origin": "Origin",
        "destination": "Destination",
    }

    required_fields = {
        "carrier": ["name", "code"],
        "shipper": ["name", "code"],
        "driver": ["name"],
        "load": ["load_number", "origin", "destination"],
    }

    if page_title == "driver" and role == "admin":
        required_fields["driver"].append("carrier_id")

    if page_title == "load" and role == "admin":
        required_fields["load"] += ["shipper_id"]

    # --------------------------------------------------
    # Handle POST
    # --------------------------------------------------

    if request.method == "POST":

        payload = {}

        for field in fields:
            value = request.POST.get(field, "").strip()

            if value:
                payload[field] = value

        missing_fields = [
            field
            for field in required_fields.get(page_title, [])
            if not payload.get(field)
        ]

        if missing_fields:
            error = (
                "Please complete the required fields: "
                + ", ".join(
                    labels.get(field, field)
                    for field in missing_fields
                )
            )

            messages.error(request, error)

            return render(
                request,
                "trucking/record_form.html",
                {
                    "page_title": page_title.replace(
                        "_", " "
                    ).title(),
                    "form_fields": build_form_fields(
                        fields,
                        labels,
                        required_fields,
                        carriers,
                        shippers,
                        drivers,
                    ),
                    "active_page": page_title + "s",
                    "form_data": request.POST,
                    "error": error,
                },
            )

        data, error = api_request(
            request,
            "POST",
            endpoint,
            json=payload,
        )

        if error:
            messages.error(
                request,
                f"Unable to create {page_title}: {error}",
            )

            return render(
                request,
                "trucking/record_form.html",
                {
                    "page_title": page_title.replace(
                        "_", " "
                    ).title(),
                    "form_fields": build_form_fields(
                        fields,
                        labels,
                        required_fields,
                        carriers,
                        shippers,
                        drivers,
                    ),
                    "active_page": page_title + "s",
                    "form_data": request.POST,
                    "error": error,
                },
            )

        messages.success(
            request,
            f"{page_title.title()} created successfully.",
        )

        return redirect(redirect_name)

    # --------------------------------------------------
    # Render form
    # --------------------------------------------------

    return render(
        request,
        "trucking/record_form.html",
        {
            "page_title": page_title.replace(
                "_", " "
            ).title(),
            "form_fields": build_form_fields(
                fields,
                labels,
                required_fields,
                carriers,
                shippers,
                drivers,
            ),
            "active_page": page_title + "s",
            "form_data": {},
        },
    )


def build_form_fields(
    fields,
    labels,
    required_fields,
    carriers,
    shippers,
    drivers,
):
    """Build template fields and dropdown choices."""

    form_fields = []

    for field in fields:

        choices = []

        if field == "carrier_id":
            choices = [
                {
                    "value": item["id"],
                    "label": item["name"],
                }
                for item in carriers
                if item.get("id") and item.get("name")
            ]

        elif field == "shipper_id":
            choices = [
                {
                    "value": item["id"],
                    "label": item["name"],
                }
                for item in shippers
                if item.get("id") and item.get("name")
            ]

        elif field == "driver_id":
            choices = [
                {
                    "value": item["id"],
                    "label": item["name"],
                }
                for item in drivers
                if item.get("id") and item.get("name")
            ]

        form_fields.append({
            "name": field,
            "label": labels.get(
                field,
                field.replace("_", " ").title(),
            ),
            "required": field in required_fields.get(
                "carrier", []
            ) or field in required_fields.get(
                "shipper", []
            ) or field in required_fields.get(
                "driver", []
            ) or field in required_fields.get(
                "load", []
            ),
            "choices": choices,
            "is_select": field in (
                "carrier_id",
                "shipper_id",
                "driver_id",
            ),
        })

    return form_fields


# ---------------------------------------------------------
# CARRIERS
# ---------------------------------------------------------

@login_required
@role_required("admin", "carrier")
def carrier_list(request):

    context = {
        "carriers": fetch_list(
            request,
            "/carriers/",
            "carriers",
        ),
        "active_page": "carriers",
    }

    return render(
        request,
        "trucking/carrier_list.html",
        context,
    )


@login_required
@role_required("admin")
def carrier_create(request):

    return create_record(
        request,
        "/carriers/",
        "carrier_list",
        "carrier",
        [
            "name",
            "code",
            "contact_email",
            "phone",
        ],
    )


# ---------------------------------------------------------
# SHIPPERS
# ---------------------------------------------------------

@login_required
@role_required("admin", "shipper")
def shipper_list(request):

    context = {
        "shippers": fetch_list(
            request,
            "/shippers/",
            "shippers",
        ),
        "active_page": "shippers",
    }

    return render(
        request,
        "trucking/shipper_list.html",
        context,
    )


@login_required
@role_required("admin")
def shipper_create(request):

    return create_record(
        request,
        "/shippers/",
        "shipper_list",
        "shipper",
        [
            "name",
            "code",
            "contact_email",
            "phone",
        ],
    )


# ---------------------------------------------------------
# DRIVERS
# ---------------------------------------------------------

@login_required
@role_required("admin", "carrier")
def driver_list(request):

    context = {
        "drivers": fetch_list(
            request,
            "/drivers/",
            "drivers",
        ),
        "active_page": "drivers",
    }

    if request.session.get("api_role") == "admin":
        context["carriers"] = fetch_list(
            request,
            "/carriers/",
            "carriers",
        )

    return render(
        request,
        "trucking/driver_list.html",
        context,
    )


@login_required
@role_required("admin", "carrier")
def driver_create(request):

    return create_record(
        request,
        "/drivers/",
        "driver_list",
        "driver",
        [
            "carrier_id",
            "name",
            "phone",
            "license_number",
        ],
    )


# ---------------------------------------------------------
# LOADS
# ---------------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def load_list(request):

    role = request.session.get("api_role", "")

    context = {
        "loads": fetch_list(
            request,
            "/loads/",
            "loads",
        ),
        "load_statuses": LOAD_STATUSES,
        "active_page": "loads",
    }

    if role == "admin":
        context["carriers"] = fetch_list(
            request,
            "/carriers/",
            "carriers",
        )

        context["shippers"] = fetch_list(
            request,
            "/shippers/",
            "shippers",
        )

        context["drivers"] = fetch_list(
            request,
            "/drivers/",
            "drivers",
        )

    elif role == "carrier":
        context["drivers"] = fetch_list(
            request,
            "/drivers/",
            "drivers",
        )

    return render(
        request,
        "trucking/load_list.html",
        context,
    )


@login_required
@role_required("admin", "shipper")
def load_create(request):

    return create_record(
        request,
        "/loads/",
        "load_list",
        "load",
        [
            "load_number",
            "shipper_id",
            "carrier_id",
            "driver_id",
            "origin",
            "destination",
        ],
    )


@login_required
@role_required("admin")
def load_assign(request, load_id):
    """Assign a carrier and driver to a load."""

    if request.method != "POST":
        return redirect("load_list")

    carrier_id = request.POST.get(
        "carrier_id", ""
    ).strip()

    driver_id = request.POST.get(
        "driver_id", ""
    ).strip()

    if not carrier_id or not driver_id:
        messages.error(
            request,
            "Please select both a carrier and a driver.",
        )
        return redirect("load_list")

    payload = {
        "carrier_id": carrier_id,
        "driver_id": driver_id,
    }

    data, error = api_request(
        request,
        "PATCH",
        f"/loads/{load_id}/assign",
        json=payload,
    )

    if error:
        messages.error(
            request,
            f"Unable to assign load: {error}",
        )
    else:
        messages.success(
            request,
            "Carrier and driver assigned successfully.",
        )

    return redirect("load_list")


@login_required
@role_required("admin", "carrier")
def load_update_status(request, load_id):
    """Update the status of an accessible load."""

    if request.method != "POST":
        return redirect("load_list")

    new_status = request.POST.get(
        "status", ""
    ).strip()

    if new_status not in LOAD_STATUSES:
        messages.error(
            request,
            "Please select a valid load status.",
        )
        return redirect("load_list")

    data, error = api_request(
        request,
        "PATCH",
        f"/loads/{load_id}/status",
        json={"status": new_status},
    )

    if error:
        messages.error(
            request,
            f"Unable to update load status: {error}",
        )
    else:
        messages.success(
            request,
            (
                "Load status updated to "
                f"{new_status.replace('_', ' ').title()}."
            ),
        )

    return redirect("load_list")
