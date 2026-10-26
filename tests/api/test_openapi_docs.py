from fastapi import FastAPI

from app.api.v1.router import api_router


def _schema() -> dict[str, object]:
    app = FastAPI(title="DataDict test")
    app.include_router(api_router, prefix="/api/v1")
    return app.openapi()


def test_metadata_and_annotation_operations_have_descriptions() -> None:
    schema = _schema()
    paths = schema["paths"]
    operations = [
        paths["/api/v1/datasources"]["get"],
        paths["/api/v1/tables"]["get"],
        paths["/api/v1/columns"]["get"],
        paths["/api/v1/tables/ddl"]["get"],
        paths["/api/v1/search"]["get"],
        paths["/api/v1/annotations/field"]["get"],
        paths["/api/v1/annotations/field"]["put"],
        paths["/api/v1/annotations/field"]["delete"],
        paths["/api/v1/annotations/table/fields"]["put"],
    ]

    assert all(operation["summary"] for operation in operations)
    assert all(operation.get("description") for operation in operations)


def test_openapi_documents_query_parameter_examples() -> None:
    schema = _schema()
    table_params = schema["paths"]["/api/v1/tables"]["get"]["parameters"]
    column_params = schema["paths"]["/api/v1/columns"]["get"]["parameters"]
    search_params = schema["paths"]["/api/v1/search"]["get"]["parameters"]

    table_urn = next(param for param in table_params if param["name"] == "urn")
    column_urn = next(param for param in column_params if param["name"] == "urn")
    query = next(param for param in search_params if param["name"] == "q")

    assert table_urn["schema"]["examples"] == ["mysql:crm:sales:orders"]
    assert column_urn["schema"]["examples"] == ["mysql:crm:sales:orders:pay_amount"]
    assert query["schema"]["examples"] == ["订单"]


def test_openapi_schema_examples_cover_core_payloads() -> None:
    schema = _schema()
    components = schema["components"]["schemas"]
    paths = schema["paths"]

    assert components["TableOut"]["example"]["urn"] == "mysql:crm:sales:orders"
    assert components["ColumnOut"]["example"]["urn"] == "mysql:crm:sales:orders:pay_amount"
    assert components["SearchOut"]["example"]["query"] == "订单"
    field_body = paths["/api/v1/annotations/field"]["put"]["requestBody"]["content"][
        "application/json"
    ]["examples"]["field_annotation"]["value"]
    batch_body = paths["/api/v1/annotations/table/fields"]["put"]["requestBody"]["content"][
        "application/json"
    ]["examples"]["table_field_annotations"]["value"]
    assert field_body["business_meaning"] == "订单支付金额"
    assert batch_body["items"][0]["urn"] == "mysql:crm:sales:orders:pay_amount"
